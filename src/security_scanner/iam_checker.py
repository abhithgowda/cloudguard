"""IAM user audit checker.

For every IAM user in the account, performs 4 sub-checks:
  1. Access keys older than 90 days                 -> MEDIUM
  2. Access keys unused for 90+ days                -> MEDIUM
  3. No MFA device attached                         -> HIGH
  4. AdministratorAccess directly attached to user  -> HIGH

Per-user calls are wrapped — a single user that errors should not abort
the scan.
"""

import logging
from datetime import datetime, timezone

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

ACCESS_KEY_MAX_AGE_DAYS = 90
ACCESS_KEY_UNUSED_DAYS = 90
ADMIN_POLICY_ARN = "arn:aws:iam::aws:policy/AdministratorAccess"


def _finding(user, check_name, severity, description, recommendation, **meta):
    return {
        "resource_id": user,
        "resource_type": "aws_iam_user",
        "check_name": check_name,
        "severity": severity,
        "category": "security",
        "description": description,
        "recommendation": recommendation,
        "metadata": meta or None,
    }


def _days_since(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days


def _check_access_keys(iam_client, user):
    findings = []
    try:
        keys = iam_client.list_access_keys(UserName=user).get("AccessKeyMetadata", [])
    except ClientError as e:
        logger.warning("list_access_keys failed for %s: %s", user, e)
        return findings

    for key in keys:
        key_id = key["AccessKeyId"]
        if key.get("Status") != "Active":
            continue

        age = _days_since(key.get("CreateDate"))
        if age is not None and age > ACCESS_KEY_MAX_AGE_DAYS:
            findings.append(
                _finding(
                    user,
                    # Discriminator (STEP 21.5) — same user can have multiple
                    # access keys; without the key_id suffix both findings
                    # would collide on (resource_id, check_name) and the
                    # upsert path would silently overwrite one with the other.
                    f"iam_access_key_old:{key_id}",
                    "MEDIUM",
                    f"User {user} has an active access key {key_id} {age} days old.",
                    "Rotate keys at least every 90 days. Prefer IAM roles + STS "
                    "over long-lived user keys wherever possible.",
                    access_key_id=key_id,
                    age_days=age,
                )
            )

        try:
            last_used = iam_client.get_access_key_last_used(AccessKeyId=key_id)
            last_used_date = last_used.get("AccessKeyLastUsed", {}).get("LastUsedDate")
        except ClientError as e:
            logger.warning("get_access_key_last_used failed for %s: %s", key_id, e)
            continue

        unused_days = _days_since(last_used_date) if last_used_date else None
        if last_used_date is None:
            if age is not None and age > ACCESS_KEY_UNUSED_DAYS:
                findings.append(
                    _finding(
                        user,
                        f"iam_access_key_unused:{key_id}",
                        "MEDIUM",
                        f"User {user} access key {key_id} has never been used "
                        f"({age} days since creation).",
                        "Delete unused access keys. Every active credential is an attack surface.",
                        access_key_id=key_id,
                    )
                )
        elif unused_days is not None and unused_days > ACCESS_KEY_UNUSED_DAYS:
            findings.append(
                _finding(
                    user,
                    f"iam_access_key_unused:{key_id}",
                    "MEDIUM",
                    f"User {user} access key {key_id} unused for {unused_days} days.",
                    "Disable or delete keys that have not been used in 90 days.",
                    access_key_id=key_id,
                    days_unused=unused_days,
                )
            )
    return findings


def _check_mfa(iam_client, user):
    try:
        mfa = iam_client.list_mfa_devices(UserName=user).get("MFADevices", [])
    except ClientError as e:
        logger.warning("list_mfa_devices failed for %s: %s", user, e)
        return None

    if not mfa:
        return _finding(
            user,
            "iam_user_no_mfa",
            "HIGH",
            f"User {user} has no MFA device attached.",
            "Require MFA on every IAM user, especially those with console access. "
            "Pair with an SCP enforcing MFA-required Conditions on sensitive actions.",
        )
    return None


def _check_admin_attached(iam_client, user):
    try:
        attached = iam_client.list_attached_user_policies(UserName=user).get(
            "AttachedPolicies", []
        )
    except ClientError as e:
        logger.warning("list_attached_user_policies failed for %s: %s", user, e)
        return None

    for policy in attached:
        if policy.get("PolicyArn") == ADMIN_POLICY_ARN:
            return _finding(
                user,
                "iam_user_admin_attached",
                "HIGH",
                f"User {user} has AdministratorAccess attached directly.",
                "Use group-based assignment or short-lived role assumption "
                "instead of attaching AdministratorAccess to a user. Direct "
                "attachment makes blast-radius audit impossible.",
            )
    return None


def check_iam_users(iam_client):
    """Scan every IAM user in the account; return list of findings."""
    findings = []
    paginator = iam_client.get_paginator("list_users")

    user_count = 0
    for page in paginator.paginate():
        for u in page.get("Users", []):
            name = u["UserName"]
            user_count += 1

            findings.extend(_check_access_keys(iam_client, name))

            mfa_finding = _check_mfa(iam_client, name)
            if mfa_finding:
                findings.append(mfa_finding)

            admin_finding = _check_admin_attached(iam_client, name)
            if admin_finding:
                findings.append(admin_finding)

    logger.info("IAM check: %d findings across %d users", len(findings), user_count)
    return findings