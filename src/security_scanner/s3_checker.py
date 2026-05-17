"""S3 bucket checker.

For every bucket in the account, performs 4 sub-checks:
  1. Public Access Block      -> any setting False     -> HIGH
  2. Default encryption       -> missing               -> HIGH
  3. Bucket policy            -> Principal = "*"       -> CRITICAL
  4. Versioning               -> not Enabled           -> LOW (warning)

Each per-bucket API call is wrapped in try/except — a single misconfigured
bucket (or one we don't have permission to introspect) should not abort
the scan. Findings carry the bucket name as resource_id.
"""

import json
import logging

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def _finding(bucket, check_name, severity, description, recommendation, **meta):
    return {
        "resource_id": bucket,
        "resource_type": "aws_s3_bucket",
        "check_name": check_name,
        "severity": severity,
        "category": "security",
        "description": description,
        "recommendation": recommendation,
        "metadata": meta or None,
    }


def _check_public_access_block(s3_client, bucket):
    try:
        resp = s3_client.get_public_access_block(Bucket=bucket)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchPublicAccessBlockConfiguration":
            return _finding(
                bucket,
                "s3_no_public_access_block",
                "HIGH",
                f"Bucket {bucket} has no public access block configuration.",
                "Enable all 4 block-public-access settings at the bucket level.",
            )
        logger.warning("PAB check failed for %s: %s", bucket, e)
        return None

    cfg = resp.get("PublicAccessBlockConfiguration", {})
    disabled = [k for k, v in cfg.items() if v is False]
    if disabled:
        return _finding(
            bucket,
            "s3_public_access_block_disabled",
            "HIGH",
            f"Bucket {bucket} has public-access-block disabled for: {', '.join(disabled)}.",
            "Set all 4 BPA settings (BlockPublicAcls, IgnorePublicAcls, "
            "BlockPublicPolicy, RestrictPublicBuckets) to True.",
            disabled_settings=disabled,
        )
    return None


def _check_encryption(s3_client, bucket):
    try:
        s3_client.get_bucket_encryption(Bucket=bucket)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ServerSideEncryptionConfigurationNotFoundError":
            return _finding(
                bucket,
                "s3_no_default_encryption",
                "HIGH",
                f"Bucket {bucket} has no default server-side encryption.",
                "Enable SSE-S3 (AES256) or SSE-KMS as the bucket default. "
                "AWS now enables SSE-S3 by default for new buckets, but legacy "
                "buckets may have been created before that change.",
            )
        logger.warning("Encryption check failed for %s: %s", bucket, e)
        return None
    return None


def _check_bucket_policy(s3_client, bucket):
    try:
        resp = s3_client.get_bucket_policy(Bucket=bucket)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchBucketPolicy":
            return None
        logger.warning("Policy check failed for %s: %s", bucket, e)
        return None

    try:
        policy = json.loads(resp["Policy"])
    except (ValueError, KeyError):
        logger.warning("Could not parse bucket policy for %s", bucket)
        return None

    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]

    for stmt in statements:
        if stmt.get("Effect") != "Allow":
            continue
        principal = stmt.get("Principal")
        if principal == "*" or (isinstance(principal, dict) and principal.get("AWS") == "*"):
            return _finding(
                bucket,
                "s3_bucket_policy_public",
                "CRITICAL",
                f"Bucket {bucket} policy contains an Allow statement with Principal = '*'.",
                "Remove the wildcard principal or scope it with a Condition "
                "(e.g. aws:SourceVpce). A public Allow can expose every object "
                "in the bucket regardless of object-level ACLs.",
                statement_sid=stmt.get("Sid"),
            )
    return None


def _check_versioning(s3_client, bucket):
    try:
        resp = s3_client.get_bucket_versioning(Bucket=bucket)
    except ClientError as e:
        logger.warning("Versioning check failed for %s: %s", bucket, e)
        return None

    status = resp.get("Status")
    if status != "Enabled":
        return _finding(
            bucket,
            "s3_versioning_disabled",
            "LOW",
            f"Bucket {bucket} versioning is not enabled (status={status or 'never enabled'}).",
            "Enable versioning to protect against accidental deletes and "
            "ransomware-style overwrites. Pair with MFA Delete for production buckets.",
        )
    return None


def check_s3_buckets(s3_client):
    """Scan every bucket in the account; return list of findings."""
    findings = []
    try:
        buckets = s3_client.list_buckets().get("Buckets", [])
    except ClientError as e:
        logger.error("list_buckets failed: %s", e)
        return findings

    for b in buckets:
        name = b["Name"]
        for check in (
            _check_public_access_block,
            _check_encryption,
            _check_bucket_policy,
            _check_versioning,
        ):
            try:
                f = check(s3_client, name)
                if f:
                    findings.append(f)
            except Exception as e:  # noqa: BLE001
                logger.exception("Check %s raised on %s: %s", check.__name__, name, e)

    logger.info("S3 check: %d findings across %d buckets", len(findings), len(buckets))
    return findings