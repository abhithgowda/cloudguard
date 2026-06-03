"""Unit tests for src/resource_cleanup/.

zombie_finder.py — pure detection logic, mock the ec2 client.
handler.py     — the two-gate auto-remediate matrix is the unique surface
                 (every other thing is shared with the cost/security tests).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from botocore.exceptions import ClientError

import zombie_finder


# ---------------------------------------------------------------------------
# zombie_finder — find_zombie_ebs_volumes
# ---------------------------------------------------------------------------


def _ec2_paginator(pages):
    paginator = MagicMock()
    paginator.paginate.return_value = iter(pages)
    return paginator


class TestFindZombieEbsVolumes:
    def _ec2_with_volumes(self, volumes):
        client = MagicMock()
        paginator = _ec2_paginator([{"Volumes": volumes}])
        client.get_paginator.return_value = paginator
        return client, paginator

    def test_small_volume_is_low_severity(self):
        # 100 GiB gp3 in ap-south-1 = $9.12/mo → LOW (< $10 threshold).
        ec2, paginator = self._ec2_with_volumes([{
            "VolumeId": "vol-1", "Size": 100, "VolumeType": "gp3",
            "AvailabilityZone": "ap-south-1a",
            "CreateTime": datetime.now(timezone.utc) - timedelta(days=30),
        }])
        findings = zombie_finder.find_zombie_ebs_volumes(ec2)
        assert len(findings) == 1
        f = findings[0]
        assert f["severity"] == "LOW"
        assert f["resource_id"] == "vol-1"
        assert f["resource_type"] == "aws_ebs_volume"
        assert f["category"] == "cleanup"
        assert f["metadata"]["monthly_cost_usd"] == 9.12

    def test_huge_io1_volume_is_high_severity(self):
        # 600 GiB io1 = 600 * 0.142 = $85.20/mo → HIGH (>= $50 threshold).
        ec2, _ = self._ec2_with_volumes([{
            "VolumeId": "vol-2", "Size": 600, "VolumeType": "io1",
            "AvailabilityZone": "ap-south-1a",
            "CreateTime": datetime.now(timezone.utc) - timedelta(days=30),
        }])
        findings = zombie_finder.find_zombie_ebs_volumes(ec2)
        assert findings[0]["severity"] == "HIGH"
        assert findings[0]["metadata"]["monthly_cost_usd"] == 85.20

    def test_filters_to_available_state_only(self):
        # The paginator is called with `Filters=[{Name=status, Values=[available]}]`
        # so AWS only returns available volumes — verified by inspecting the call.
        ec2, paginator = self._ec2_with_volumes([])
        zombie_finder.find_zombie_ebs_volumes(ec2)
        paginator.paginate.assert_called_once_with(
            Filters=[{"Name": "status", "Values": ["available"]}]
        )


class TestFindUnusedElasticIps:
    def test_unattached_eip_flagged(self):
        ec2 = MagicMock()
        ec2.describe_addresses.return_value = {
            "Addresses": [
                {"AllocationId": "eipalloc-1", "PublicIp": "1.2.3.4",
                 "Domain": "vpc"},
            ]
        }
        findings = zombie_finder.find_unused_elastic_ips(ec2)
        assert len(findings) == 1
        assert findings[0]["resource_id"] == "eipalloc-1"
        assert findings[0]["resource_type"] == "aws_eip"
        # $3.65/mo → LOW (under the $10 MEDIUM threshold).
        assert findings[0]["severity"] == "LOW"
        assert findings[0]["metadata"]["monthly_cost_usd"] == 3.65

    def test_attached_eip_skipped(self):
        ec2 = MagicMock()
        ec2.describe_addresses.return_value = {
            "Addresses": [
                {"AllocationId": "eipalloc-2", "PublicIp": "1.2.3.4",
                 "AssociationId": "eipassoc-x", "Domain": "vpc"},
            ]
        }
        assert zombie_finder.find_unused_elastic_ips(ec2) == []


class TestFindOldSnapshots:
    def _ec2_with_snapshots(self, snaps):
        client = MagicMock()
        paginator = _ec2_paginator([{"Snapshots": snaps}])
        client.get_paginator.return_value = paginator
        return client

    def test_old_standard_snapshot_flagged(self):
        # 200 days old, 500 GiB at $0.05/GB-mo = $25/mo → MEDIUM (>= $10).
        old_time = datetime.now(timezone.utc) - timedelta(days=200)
        ec2 = self._ec2_with_snapshots([{
            "SnapshotId": "snap-1", "StartTime": old_time, "VolumeSize": 500,
            "StorageTier": "standard",
        }])
        findings = zombie_finder.find_old_snapshots(ec2, age_days=180)
        assert len(findings) == 1
        assert findings[0]["severity"] == "MEDIUM"
        assert findings[0]["metadata"]["monthly_cost_usd"] == 25.0

    def test_new_snapshot_skipped(self):
        new_time = datetime.now(timezone.utc) - timedelta(days=10)
        ec2 = self._ec2_with_snapshots([{
            "SnapshotId": "snap-2", "StartTime": new_time, "VolumeSize": 100,
        }])
        assert zombie_finder.find_old_snapshots(ec2, age_days=180) == []

    def test_archive_tier_snapshot_skipped(self):
        # Archive tier has different pricing — honestly skipped per zombie_finder docstring.
        old_time = datetime.now(timezone.utc) - timedelta(days=200)
        ec2 = self._ec2_with_snapshots([{
            "SnapshotId": "snap-3", "StartTime": old_time, "VolumeSize": 500,
            "StorageTier": "archive",
        }])
        assert zombie_finder.find_old_snapshots(ec2, age_days=180) == []

    def test_default_storage_tier_treated_as_standard(self):
        # StorageTier absent → defaults to "standard" in the checker.
        old_time = datetime.now(timezone.utc) - timedelta(days=200)
        ec2 = self._ec2_with_snapshots([{
            "SnapshotId": "snap-4", "StartTime": old_time, "VolumeSize": 100,
        }])
        findings = zombie_finder.find_old_snapshots(ec2, age_days=180)
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# handler.py — the two-gate auto-remediate matrix (the unique surface)
# ---------------------------------------------------------------------------


@pytest.fixture
def cleanup_env(monkeypatch):
    """Wire the env vars the handler reads."""
    monkeypatch.setenv("FINDINGS_TABLE", "cloudguard-dev-findings")
    monkeypatch.setenv("REMEDIATION_LOG_TABLE", "cloudguard-dev-remediation-log")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("LOG_LEVEL", "INFO")


@pytest.fixture
def cleanup_handler(cleanup_env, handler_loader):
    """Load the resource_cleanup handler fresh after env is configured."""
    return handler_loader("resource_cleanup")


class TestAutoRemediateGate:
    """Two-gate matrix: env var × event flag. Only [TRUE, TRUE] deletes."""

    @pytest.mark.parametrize(
        "env_var,event_flag,expected",
        [
            ("false", False, False),
            ("false", True, False),   # env says no — event can't override
            ("true",  False, False),  # event says no — env can't act alone
            ("true",  True,  True),   # both opted in → armed
        ],
    )
    def test_two_gate_matrix(self, cleanup_handler, monkeypatch, env_var, event_flag, expected):
        monkeypatch.setenv("AUTO_REMEDIATE", env_var)
        event = {"auto_remediate": event_flag}
        assert cleanup_handler._auto_remediate_enabled(event) is expected

    def test_missing_env_var_defaults_to_false(self, cleanup_handler, monkeypatch):
        monkeypatch.delenv("AUTO_REMEDIATE", raising=False)
        assert cleanup_handler._auto_remediate_enabled({"auto_remediate": True}) is False

    def test_non_dict_event_treated_as_no_flag(self, cleanup_handler, monkeypatch):
        monkeypatch.setenv("AUTO_REMEDIATE", "true")
        # If EventBridge or a Step Functions Pass state sends a bare string,
        # the handler must not trip into remediation.
        assert cleanup_handler._auto_remediate_enabled("not a dict") is False


class TestRemediate:
    """Direct tests of _remediate(): dry-run, success, failure paths."""

    def test_dry_run_logs_skipped_records_no_delete_calls(
        self, cleanup_handler
    ):
        findings = [{
            "finding_id": "f1", "resource_id": "vol-1",
            "resource_type": "aws_ebs_volume", "severity": "LOW",
        }]
        # Patch the ec2 client to prove no delete is called in dry-run.
        cleanup_handler.ec2 = MagicMock()
        with patch.object(cleanup_handler, "batch_put_findings") as mock_bpf:
            counts = cleanup_handler._remediate(
                findings, "log-table", dry_run=True
            )
        assert counts == {"success": 0, "failed": 0, "skipped_dry_run": 1}
        cleanup_handler.ec2.delete_volume.assert_not_called()
        # The dry-run skip IS still written to the remediation log.
        records = mock_bpf.call_args.args[1]
        assert records[0]["status"] == "SKIPPED_DRY_RUN"
        assert records[0]["action"] == "delete_volume"
        assert records[0]["linked_finding_id"] == "f1"

    def test_success_path_calls_delete_and_logs_success(self, cleanup_handler):
        findings = [{
            "finding_id": "f1", "resource_id": "vol-1",
            "resource_type": "aws_ebs_volume", "severity": "HIGH",
        }]
        cleanup_handler.ec2 = MagicMock()
        cleanup_handler.ec2.delete_volume.return_value = {}

        with patch.object(cleanup_handler, "batch_put_findings") as mock_bpf:
            counts = cleanup_handler._remediate(
                findings, "log-table", dry_run=False
            )
        assert counts == {"success": 1, "failed": 0, "skipped_dry_run": 0}
        cleanup_handler.ec2.delete_volume.assert_called_once_with(VolumeId="vol-1")
        records = mock_bpf.call_args.args[1]
        assert records[0]["status"] == "SUCCESS"
        assert "error_message" not in records[0]

    def test_failed_delete_logs_failure_with_error_message(self, cleanup_handler):
        findings = [{
            "finding_id": "f1", "resource_id": "vol-1",
            "resource_type": "aws_ebs_volume", "severity": "HIGH",
        }]
        cleanup_handler.ec2 = MagicMock()
        cleanup_handler.ec2.delete_volume.side_effect = ClientError(
            {"Error": {"Code": "VolumeInUse",
                       "Message": "Volume is currently attached"}},
            "DeleteVolume",
        )

        with patch.object(cleanup_handler, "batch_put_findings") as mock_bpf:
            counts = cleanup_handler._remediate(
                findings, "log-table", dry_run=False
            )
        assert counts == {"success": 0, "failed": 1, "skipped_dry_run": 0}
        records = mock_bpf.call_args.args[1]
        assert records[0]["status"] == "FAILED"
        assert "Volume is currently attached" in records[0]["error_message"]

    def test_unknown_resource_type_skipped_no_record(self, cleanup_handler):
        findings = [{
            "finding_id": "f1", "resource_id": "x",
            "resource_type": "aws_unknown", "severity": "LOW",
        }]
        cleanup_handler.ec2 = MagicMock()
        with patch.object(cleanup_handler, "batch_put_findings") as mock_bpf:
            counts = cleanup_handler._remediate(
                findings, "log-table", dry_run=False
            )
        # No handler for this type → no remediation attempt, no record.
        assert counts == {"success": 0, "failed": 0, "skipped_dry_run": 0}
        assert mock_bpf.call_args.args[1] == []


# ---------------------------------------------------------------------------
# STEP 25 — invocation modes (scan default / detect / remediate)
# ---------------------------------------------------------------------------

_FAKE_VOLUME = {
    "resource_id": "vol-1",
    "resource_type": "aws_ebs_volume",
    "check_name": "zombie_ebs_volume",
    "category": "cleanup",
    "severity": "HIGH",
    "description": "EBS volume vol-1 is available.",
    "metadata": {"monthly_cost_usd": 85.20},
}


class TestDetectMode:
    """mode='detect' returns the resource list and does NOT remediate."""

    def test_detect_returns_resources_and_skips_remediation(self, cleanup_handler):
        with patch.object(cleanup_handler, "find_zombie_ebs_volumes", return_value=[dict(_FAKE_VOLUME)]), \
             patch.object(cleanup_handler, "find_unused_elastic_ips", return_value=[]), \
             patch.object(cleanup_handler, "find_old_snapshots", return_value=[]), \
             patch.object(cleanup_handler, "batch_upsert_findings",
                          return_value={"total": 1, "inserted": 1, "updated": 0}), \
             patch.object(cleanup_handler, "_remediate") as mock_remediate:
            result = cleanup_handler.lambda_handler({"mode": "detect"}, None)

        assert result["mode"] == "detect"
        assert result["resource_count"] == 1
        # The slim resource summary carries what the email + delete step need.
        res = result["resources"][0]
        assert res["resource_id"] == "vol-1"
        assert res["resource_type"] == "aws_ebs_volume"
        assert res["monthly_cost_usd"] == 85.20
        assert "finding_id" in res  # deterministic id stamped in
        # Detection only — no remediation, not even a dry-run row.
        mock_remediate.assert_not_called()
        assert "remediations" not in result

    def test_detect_empty_returns_zero(self, cleanup_handler):
        with patch.object(cleanup_handler, "find_zombie_ebs_volumes", return_value=[]), \
             patch.object(cleanup_handler, "find_unused_elastic_ips", return_value=[]), \
             patch.object(cleanup_handler, "find_old_snapshots", return_value=[]), \
             patch.object(cleanup_handler, "batch_upsert_findings",
                          return_value={"total": 0, "inserted": 0, "updated": 0}):
            result = cleanup_handler.lambda_handler({"mode": "detect"}, None)
        assert result["resource_count"] == 0
        assert result["resources"] == []


class TestRemediateMode:
    """mode='remediate' deletes an EXPLICIT list, gated, with NO re-detection."""

    def _event(self, armed_flag=True):
        return {
            "mode": "remediate",
            "auto_remediate": armed_flag,
            "resources": [{
                "resource_id": "vol-1", "resource_type": "aws_ebs_volume",
                "finding_id": "f1",
            }],
        }

    def test_armed_deletes_explicit_list_without_redetecting(self, cleanup_handler, monkeypatch):
        monkeypatch.setenv("AUTO_REMEDIATE", "true")
        cleanup_handler.ec2 = MagicMock()
        cleanup_handler.ec2.delete_volume.return_value = {}

        with patch.object(cleanup_handler, "find_zombie_ebs_volumes") as mock_find, \
             patch.object(cleanup_handler, "batch_put_findings"):
            result = cleanup_handler.lambda_handler(self._event(True), None)

        assert result["mode"] == "remediate"
        assert result["auto_remediate_armed"] is True
        assert result["remediations"]["success"] == 1
        cleanup_handler.ec2.delete_volume.assert_called_once_with(VolumeId="vol-1")
        # Critically: remediate must NOT re-run detection (TOCTOU guard).
        mock_find.assert_not_called()

    def test_gate_still_applies_dry_run_when_env_false(self, cleanup_handler, monkeypatch):
        # Even with the event flag + human approval, the STEP 12 env gate alone
        # forces a dry-run in dev (AUTO_REMEDIATE='false').
        monkeypatch.setenv("AUTO_REMEDIATE", "false")
        cleanup_handler.ec2 = MagicMock()

        with patch.object(cleanup_handler, "batch_put_findings"):
            result = cleanup_handler.lambda_handler(self._event(True), None)

        assert result["auto_remediate_armed"] is False
        assert result["remediations"]["skipped_dry_run"] == 1
        cleanup_handler.ec2.delete_volume.assert_not_called()


class TestScanModeUnchanged:
    """Default (no mode) must behave exactly like the pre-STEP-25 scan path."""

    def test_default_mode_scans_and_dry_runs(self, cleanup_handler, monkeypatch):
        monkeypatch.setenv("AUTO_REMEDIATE", "false")
        cleanup_handler.ec2 = MagicMock()
        with patch.object(cleanup_handler, "find_zombie_ebs_volumes", return_value=[dict(_FAKE_VOLUME)]), \
             patch.object(cleanup_handler, "find_unused_elastic_ips", return_value=[]), \
             patch.object(cleanup_handler, "find_old_snapshots", return_value=[]), \
             patch.object(cleanup_handler, "batch_upsert_findings",
                          return_value={"total": 1, "inserted": 1, "updated": 0}), \
             patch.object(cleanup_handler, "batch_put_findings"):
            result = cleanup_handler.lambda_handler({}, None)

        # Original summary shape — no "mode" key, has volumes_found + remediations.
        assert "mode" not in result
        assert result["volumes_found"] == 1
        assert result["auto_remediate_armed"] is False
        assert result["remediations"]["skipped_dry_run"] == 1
        cleanup_handler.ec2.delete_volume.assert_not_called()
