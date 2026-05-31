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


# -- Entrypoint --------------------------------------------------------------
def lambda_handler(event, context):
    findings_table_name = os.environ["FINDINGS_TABLE"]
    remediation_log_table_name = os.environ["REMEDIATION_LOG_TABLE"]
    snapshot_age_days = int(os.environ.get("SNAPSHOT_AGE_DAYS", "180"))

    volumes = find_zombie_ebs_volumes(ec2)
    eips = find_unused_elastic_ips(ec2)
    snapshots = find_old_snapshots(ec2, age_days=snapshot_age_days)
    all_findings = volumes + eips + snapshots

    _stamp_findings(all_findings)
    # STEP 21.5: idempotent upsert (deterministic finding_id). Same zombie
    # volume re-detected next scan updates last_seen instead of inserting
    # a duplicate. Float→Decimal coercion is still recursive via the helper.
    upsert_counts = batch_upsert_findings(findings_table_name, all_findings)
    findings_written = upsert_counts["total"]

    estimated_savings = sum(
        f.get("metadata", {}).get("monthly_cost_usd", 0) for f in all_findings
    )

    armed = _auto_remediate_enabled(event)
    # dry_run is True unless BOTH gates passed.
    remediation_counts = _remediate(all_findings, remediation_log_table_name, dry_run=not armed)

    summary = {
        "volumes_found": len(volumes),
        "eips_found": len(eips),
        "snapshots_found": len(snapshots),
        "findings_written": findings_written,
        "new_findings": upsert_counts["inserted"],
        "updated_findings": upsert_counts["updated"],
        "estimated_monthly_savings_usd": round(float(estimated_savings), 2),
        "auto_remediate_armed": armed,
        "remediations": remediation_counts,
    }
    logger.info("Summary: %s", json.dumps(summary))
    return summary