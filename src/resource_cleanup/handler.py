"""CloudGuard Resource Cleanup — Lambda entrypoint.

Detects zombie AWS resources (unattached EBS volumes, idle EIPs, old EBS
snapshots) and OPTIONALLY remediates them. Every finding is written to
`cloudguard-<env>-findings` with category="cleanup"; every remediation
attempt (success, failure, or dry-run skip) is logged to
`cloudguard-<env>-remediation-log`.

Auto-remediate is GUARDED by two independent gates (defense in depth):
  1. Environment variable AUTO_REMEDIATE must be "true"  (per-env hard stop)
  2. Event input  auto_remediate  must be truthy         (per-invocation flag)

Either gate alone is not enough. In dev the env var is "false" — no event
input can flip it. In production the env var is "true" but EventBridge omits
the event flag for scheduled scans, so the default is still detect-only;
manual Step Functions invocations pass the flag explicitly when remediation
is intended.

Invocation modes (STEP 25 — human-in-the-loop split; `event["mode"]`):
  - "scan"      (default, UNCHANGED): detect zombies, upsert findings, then
                remediate IF both gates are armed (else dry-run log). This is
                exactly the pre-STEP-25 behaviour the 6-hourly EventBridge scan
                relies on — omitting `mode` keeps the old path bit-for-bit.
  - "detect":   detect + upsert findings ONLY, and RETURN the resource list.
                No remediation, not even a dry-run log row — the delete
                decision belongs to the human approving downstream. Feeds the
                approval email + the later "remediate" call.
  - "remediate": delete an EXPLICIT, pre-approved `event["resources"]` list.
                Does NOT re-detect (avoids a TOCTOU gap between detect and
                approval). The two gates above STILL apply, so dev stays
                dry-run until AUTO_REMEDIATE is flipped. STEP 25 adds human
                approval as a FOURTH gate upstream in the Step Functions graph;
                STEP 18.5's IAM AutoCleanup tag is the third at the API layer.

Wiring: env vars FINDINGS_TABLE, REMEDIATION_LOG_TABLE, SNS_TOPIC_ARN,
ENVIRONMENT, LOG_LEVEL, AUTO_REMEDIATE injected by the lambda Terraform
module (terraform/environments/dev/main.tf).
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from zombie_finder import (
    find_old_snapshots,
    find_unused_elastic_ips,
    find_zombie_ebs_volumes,
)

from shared.dynamo_client import (
    batch_put_findings,
    batch_upsert_findings,
    compute_finding_id,
)

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

FINDING_TTL_DAYS = 90

ec2 = boto3.client("ec2")


# -- Stamping ----------------------------------------------------------------
def _stamp_findings(raw_findings):
    """Add deterministic finding_id / timestamp / expires_at to each finding.

    STEP 21.5: ``finding_id`` is a stable hash of (category, resource_id,
    check_name). The same zombie volume re-detected next scan keeps the
    same ID, so the upsert path bumps last_seen instead of inserting a
    duplicate row. Remediation_log entries below keep uuid — each remediation
    attempt IS a discrete event with its own audit row.
    """
    now = datetime.now(timezone.utc)
    timestamp_iso = now.isoformat()
    expires_at = int((now + timedelta(days=FINDING_TTL_DAYS)).timestamp())

    for f in raw_findings:
        f["finding_id"] = compute_finding_id(
            f["category"], f["resource_id"], f["check_name"]
        )
        f["timestamp"] = timestamp_iso
        f["expires_at"] = expires_at
        if f.get("metadata") in (None, {}):
            f.pop("metadata", None)
    return raw_findings


# -- Auto-remediate gating ---------------------------------------------------
def _auto_remediate_enabled(event):
    """Both env var AND event flag must opt-in for any deletion to happen."""
    env_flag = os.environ.get("AUTO_REMEDIATE", "false").lower() == "true"
    event_flag = bool(event.get("auto_remediate")) if isinstance(event, dict) else False
    return env_flag and event_flag


# -- Per-resource remediators ------------------------------------------------
# Each returns (status, error_message_or_none). status is one of:
#   SUCCESS  — delete API returned without error
#   FAILED   — delete API raised; resource still exists
def _delete_volume(ec2_client, volume_id):
    try:
        ec2_client.delete_volume(VolumeId=volume_id)
        return "SUCCESS", None
    except ClientError as e:
        return "FAILED", e.response.get("Error", {}).get("Message", str(e))


def _release_eip(ec2_client, allocation_id):
    try:
        ec2_client.release_address(AllocationId=allocation_id)
        return "SUCCESS", None
    except ClientError as e:
        return "FAILED", e.response.get("Error", {}).get("Message", str(e))


def _delete_snapshot(ec2_client, snapshot_id):
    try:
        ec2_client.delete_snapshot(SnapshotId=snapshot_id)
        return "SUCCESS", None
    except ClientError as e:
        return "FAILED", e.response.get("Error", {}).get("Message", str(e))


_ACTION_FOR_TYPE = {
    "aws_ebs_volume": ("delete_volume", _delete_volume),
    "aws_eip": ("release_address", _release_eip),
    "aws_ebs_snapshot": ("delete_snapshot", _delete_snapshot),
}


def _build_remediation_record(finding, status, action, error_message=None):
    now = datetime.now(timezone.utc)
    record = {
        "remediation_id": str(uuid.uuid4()),
        "timestamp": now.isoformat(),
        "resource_id": finding["resource_id"],
        "resource_type": finding["resource_type"],
        "action": action,
        "status": status,
        "linked_finding_id": finding.get("finding_id"),
        "environment": os.environ.get("ENVIRONMENT", "unknown"),
    }
    if error_message:
        record["error_message"] = error_message
    return record


def _remediate(findings, remediation_log_table_name, dry_run):
    """Run remediations OR record dry-run skips. Returns counts + records."""
    success = 0
    failed = 0
    skipped = 0
    records = []

    for f in findings:
        rtype = f["resource_type"]
        spec = _ACTION_FOR_TYPE.get(rtype)
        if not spec:
            logger.warning("No remediation handler for %s — skipping", rtype)
            continue
        action_name, action_fn = spec

        if dry_run:
            records.append(_build_remediation_record(f, "SKIPPED_DRY_RUN", action_name))
            skipped += 1
            continue

        status, error_message = action_fn(ec2, f["resource_id"])
        records.append(_build_remediation_record(f, status, action_name, error_message))
        if status == "SUCCESS":
            success += 1
            logger.info("Remediated %s %s", rtype, f["resource_id"])
        else:
            failed += 1
            logger.error("Failed to remediate %s %s: %s", rtype, f["resource_id"], error_message)

    batch_put_findings(remediation_log_table_name, records)

    return {"success": success, "failed": failed, "skipped_dry_run": skipped}


# -- Detection ---------------------------------------------------------------
def _detect(findings_table_name, snapshot_age_days):
    """Run all three zombie finders, stamp + upsert findings, return them.

    Shared by the "scan" and "detect" modes — detection is identical; only
    what happens AFTER (remediate vs hand the list to a human) differs.
    """
    volumes = find_zombie_ebs_volumes(ec2)
    eips = find_unused_elastic_ips(ec2)
    snapshots = find_old_snapshots(ec2, age_days=snapshot_age_days)
    all_findings = volumes + eips + snapshots

    _stamp_findings(all_findings)
    # STEP 21.5: idempotent upsert (deterministic finding_id). Same zombie
    # volume re-detected next scan updates last_seen instead of inserting
    # a duplicate. Float→Decimal coercion is still recursive via the helper.
    upsert_counts = batch_upsert_findings(findings_table_name, all_findings)

    counts = {"volumes": len(volumes), "eips": len(eips), "snapshots": len(snapshots)}
    return all_findings, upsert_counts, counts


def _to_resource_summary(finding):
    """Slim, JSON-safe view of a finding for the approval email + delete step.

    Carries only what the operator needs to decide and what `_remediate`
    needs to act (resource_id + resource_type). `monthly_cost_usd` is coerced
    to float so the value round-trips cleanly through Step Functions / API
    Gateway JSON.
    """
    metadata = finding.get("metadata") or {}
    return {
        "resource_id": finding["resource_id"],
        "resource_type": finding["resource_type"],
        "finding_id": finding.get("finding_id"),
        "severity": finding.get("severity"),
        "monthly_cost_usd": float(metadata.get("monthly_cost_usd", 0) or 0),
        "description": finding.get("description", ""),
    }


# -- Remediate mode (STEP 25) ------------------------------------------------
def _handle_remediate(event, remediation_log_table_name):
    """Delete an EXPLICIT, human-approved resource list — no re-detection.

    The resources were captured at detect time and approved by an operator via
    the Step Functions `.waitForTaskToken` callback. Re-detecting here would
    reopen a TOCTOU gap (a resource appearing/disappearing between detection
    and approval). The two STEP 12 gates STILL apply: unless AUTO_REMEDIATE is
    "true" AND the event flag is set, this is a dry-run.
    """
    resources = event.get("resources", []) if isinstance(event, dict) else []
    armed = _auto_remediate_enabled(event)
    remediation_counts = _remediate(resources, remediation_log_table_name, dry_run=not armed)

    summary = {
        "mode": "remediate",
        "resources_requested": len(resources),
        "auto_remediate_armed": armed,
        "remediations": remediation_counts,
    }
    logger.info("Remediate summary: %s", json.dumps(summary))
    return summary


# -- Entrypoint --------------------------------------------------------------
def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    mode = event.get("mode", "scan")

    findings_table_name = os.environ["FINDINGS_TABLE"]
    remediation_log_table_name = os.environ["REMEDIATION_LOG_TABLE"]
    snapshot_age_days = int(os.environ.get("SNAPSHOT_AGE_DAYS", "180"))

    # STEP 25: act on a pre-approved list. Detection already happened upstream.
    if mode == "remediate":
        return _handle_remediate(event, remediation_log_table_name)

    all_findings, upsert_counts, counts = _detect(findings_table_name, snapshot_age_days)
    estimated_savings = sum(
        f.get("metadata", {}).get("monthly_cost_usd", 0) for f in all_findings
    )

    # STEP 25: detection-only — return the list for the human-approval flow.
    # Deliberately no _remediate call: not even a dry-run row, because the
    # delete intent hasn't been formed yet (the human hasn't decided).
    if mode == "detect":
        summary = {
            "mode": "detect",
            "volumes_found": counts["volumes"],
            "eips_found": counts["eips"],
            "snapshots_found": counts["snapshots"],
            "resource_count": len(all_findings),
            "findings_written": upsert_counts["total"],
            "new_findings": upsert_counts["inserted"],
            "updated_findings": upsert_counts["updated"],
            "estimated_monthly_savings_usd": round(float(estimated_savings), 2),
            "resources": [_to_resource_summary(f) for f in all_findings],
        }
        logger.info("Detect summary: %s", json.dumps(summary))
        return summary

    # mode == "scan" (default) — pre-STEP-25 behaviour, unchanged. dry_run is
    # True unless BOTH gates passed.
    armed = _auto_remediate_enabled(event)
    remediation_counts = _remediate(all_findings, remediation_log_table_name, dry_run=not armed)

    summary = {
        "volumes_found": counts["volumes"],
        "eips_found": counts["eips"],
        "snapshots_found": counts["snapshots"],
        "findings_written": upsert_counts["total"],
        "new_findings": upsert_counts["inserted"],
        "updated_findings": upsert_counts["updated"],
        "estimated_monthly_savings_usd": round(float(estimated_savings), 2),
        "auto_remediate_armed": armed,
        "remediations": remediation_counts,
    }
    logger.info("Summary: %s", json.dumps(summary))
    return summary