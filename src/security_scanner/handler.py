"""CloudGuard Security Scanner — Lambda entrypoint.

Orchestrates the per-resource-type security checkers and writes every
finding to `cloudguard-<env>-findings` with category="security".

Wiring: env var FINDINGS_TABLE (and ENVIRONMENT) injected by the lambda
Terraform module (terraform/environments/dev/main.tf).

Each check returns a list of finding dicts shaped by the helpers. The
handler stamps on finding_id, timestamp (ISO-8601 UTC) and expires_at
(epoch seconds, +90 days for the table's TTL) before batch-writing.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

from config_checker import check_config_compliance
from ebs_checker import check_ebs_encryption
from iam_checker import check_iam_users
from s3_checker import check_s3_buckets
from sg_checker import check_security_groups

from shared.dynamo_client import batch_upsert_findings, compute_finding_id

logger = logging.getLogger()
logger.setLevel(logging.INFO)

FINDING_TTL_DAYS = 90

ec2 = boto3.client("ec2")
s3 = boto3.client("s3")
iam = boto3.client("iam")
config = boto3.client("config")


def _run_check(name, fn, *args):
    """Invoke a checker, log + swallow exceptions so one failure doesn't kill the run."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001
        logger.exception("Checker %s raised: %s", name, e)
        return []


def _stamp_findings(raw_findings):
    """Add deterministic finding_id / timestamp / expires_at to each finding.

    STEP 21.5: ``finding_id`` is a stable hash of (category, resource_id,
    check_name), so re-scanning the same SG-port-22-open finding produces
    the same ID — the upsert path then updates last_seen instead of
    inserting a duplicate.
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
        # DynamoDB rejects empty maps in some SDK paths — drop empty metadata.
        if f.get("metadata") in (None, {}):
            f.pop("metadata", None)
    return raw_findings


def lambda_handler(event, context):
    findings_table_name = os.environ["FINDINGS_TABLE"]

    sg_findings = _run_check("security_groups", check_security_groups, ec2)
    s3_findings = _run_check("s3_buckets", check_s3_buckets, s3)
    iam_findings = _run_check("iam_users", check_iam_users, iam)
    ebs_findings = _run_check("ebs_encryption", check_ebs_encryption, ec2)
    config_findings = _run_check("config_compliance", check_config_compliance, config)

    all_findings = (
        sg_findings + s3_findings + iam_findings + ebs_findings + config_findings
    )
    _stamp_findings(all_findings)

    by_severity = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in all_findings:
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1

    upsert_counts = batch_upsert_findings(findings_table_name, all_findings)

    summary = {
        "total_findings": upsert_counts["total"],
        "new_findings": upsert_counts["inserted"],
        "updated_findings": upsert_counts["updated"],
        "by_severity": by_severity,
        "by_check": {
            "security_groups": len(sg_findings),
            "s3_buckets": len(s3_findings),
            "iam_users": len(iam_findings),
            "ebs_encryption": len(ebs_findings),
            "config_compliance": len(config_findings),
        },
    }
    logger.info("Summary: %s", json.dumps(summary))
    return summary