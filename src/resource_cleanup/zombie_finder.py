"""Zombie resource finders for the CloudGuard cleanup Lambda.

Three pure helpers — each takes a boto3 ec2 client as a parameter and returns
a list of dicts describing the zombie resources it found. Pricing is
hardcoded for ap-south-1 from the public AWS pricing page (effective
2026-05); revisit the constants when the Pricing API integration lands.

Why hardcoded prices and not the AWS Pricing API:
  - Pricing API is us-east-1-only, needs an extra IAM grant + ~500ms per call
  - These prices change a few times per year at most
  - Documented constants keep the math auditable in CloudWatch logs

The handler (handler.py) is responsible for stamping finding_id / timestamp /
expires_at and for the auto-remediate path. These helpers do detection only.
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# -- ap-south-1 EBS pricing (USD per GB-month), effective 2026-05 -------------
EBS_PRICE_PER_GB_MONTH = {
    "gp3": 0.0912,
    "gp2": 0.114,
    "io1": 0.142,
    "io2": 0.142,
    "st1": 0.0535,
    "sc1": 0.0331,
    "standard": 0.08,
}
EBS_DEFAULT_PRICE = 0.10  # conservative fallback for unknown volume types

# -- ap-south-1 unused-EIP price: $0.005/hr * 24 * ~30.42 days = ~$3.65/mo ----
EIP_MONTHLY_COST_USD = 3.65

# -- ap-south-1 snapshot pricing (Standard tier; Archive tier excluded) ------
SNAPSHOT_PRICE_PER_GB_MONTH = 0.05

# Severity ladder by estimated monthly cost (USD).
# Tunable — the goal is to surface the expensive zombies first.
SEVERITY_HIGH_THRESHOLD_USD = 50.0
SEVERITY_MEDIUM_THRESHOLD_USD = 10.0


def _severity_for_cost(monthly_cost_usd):
    """Map a monthly cost to a CloudGuard severity level."""
    if monthly_cost_usd >= SEVERITY_HIGH_THRESHOLD_USD:
        return "HIGH"
    if monthly_cost_usd >= SEVERITY_MEDIUM_THRESHOLD_USD:
        return "MEDIUM"
    return "LOW"


def _ebs_monthly_cost(size_gb, volume_type):
    """Estimate monthly EBS storage cost. iops/throughput surcharges ignored."""
    rate = EBS_PRICE_PER_GB_MONTH.get(volume_type, EBS_DEFAULT_PRICE)
    return round(size_gb * rate, 2)


def find_zombie_ebs_volumes(ec2_client):
    """Return findings for EBS volumes in `available` state (unattached).

    Available = not attached to any instance = billed but unused.
    """
    findings = []
    paginator = ec2_client.get_paginator("describe_volumes")
    pages = paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}])

    for page in pages:
        for vol in page.get("Volumes", []):
            volume_id = vol["VolumeId"]
            try:
                size_gb = int(vol.get("Size", 0))
                volume_type = vol.get("VolumeType", "unknown")
                monthly_cost = _ebs_monthly_cost(size_gb, volume_type)
                create_time = vol.get("CreateTime")
                create_iso = (
                    create_time.isoformat() if isinstance(create_time, datetime) else None
                )

                findings.append({
                    "resource_id": volume_id,
                    "resource_type": "aws_ebs_volume",
                    "check_name": "zombie_ebs_volume",
                    "severity": _severity_for_cost(monthly_cost),
                    "category": "cleanup",
                    "description": (
                        f"EBS volume {volume_id} ({size_gb} GiB, {volume_type}) "
                        f"is `available` (unattached) — estimated waste "
                        f"${monthly_cost:.2f}/month."
                    ),
                    "recommendation": (
                        "Confirm the volume is not part of a paused workload, then "
                        "delete it. Cleanup Lambda will remove it automatically "
                        "once AUTO_REMEDIATE is enabled."
                    ),
                    "metadata": {
                        "size_gb": size_gb,
                        "volume_type": volume_type,
                        "monthly_cost_usd": monthly_cost,
                        "create_date": create_iso,
                        "availability_zone": vol.get("AvailabilityZone"),
                    },
                })
            except Exception as e:  # noqa: BLE001
                logger.exception("Failed to evaluate volume %s: %s", volume_id, e)

    logger.info("Zombie EBS scan: %d findings", len(findings))
    return findings


def find_unused_elastic_ips(ec2_client):
    """Return findings for Elastic IPs with no AssociationId (not attached)."""
    findings = []

    try:
        response = ec2_client.describe_addresses()
    except Exception as e:  # noqa: BLE001
        logger.exception("describe_addresses failed: %s", e)
        return findings

    for addr in response.get("Addresses", []):
        if addr.get("AssociationId"):
            continue  # in use — skip

        allocation_id = addr.get("AllocationId", "unknown")
        public_ip = addr.get("PublicIp", "unknown")

        findings.append({
            "resource_id": allocation_id,
            "resource_type": "aws_eip",
            "check_name": "unused_elastic_ip",
            "severity": _severity_for_cost(EIP_MONTHLY_COST_USD),
            "category": "cleanup",
            "description": (
                f"Elastic IP {public_ip} (allocation {allocation_id}) is not "
                f"associated with any resource — billed at ~"
                f"${EIP_MONTHLY_COST_USD:.2f}/month for idle."
            ),
            "recommendation": (
                "Confirm the IP isn't reserved for a planned re-attach, then "
                "release it. AWS only charges for unattached EIPs."
            ),
            "metadata": {
                "public_ip": public_ip,
                "domain": addr.get("Domain"),
                "monthly_cost_usd": EIP_MONTHLY_COST_USD,
            },
        })

    logger.info("Unused EIP scan: %d findings", len(findings))
    return findings


def find_old_snapshots(ec2_client, age_days=180):
    """Return findings for self-owned snapshots older than `age_days`.

    Archive-tier snapshots are skipped — their pricing model differs and the
    `describe_snapshots` payload exposes the tier only when explicitly asked.
    """
    findings = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=age_days)

    paginator = ec2_client.get_paginator("describe_snapshots")
    pages = paginator.paginate(OwnerIds=["self"])

    for page in pages:
        for snap in page.get("Snapshots", []):
            snapshot_id = snap.get("SnapshotId", "unknown")
            try:
                start_time = snap.get("StartTime")
                if not isinstance(start_time, datetime):
                    continue
                if start_time > cutoff:
                    continue  # not old enough

                # StorageTier may be absent on older snapshots; default to standard.
                if snap.get("StorageTier", "standard").lower() == "archive":
                    continue

                volume_size = int(snap.get("VolumeSize", 0))
                monthly_cost = round(volume_size * SNAPSHOT_PRICE_PER_GB_MONTH, 2)
                age = (datetime.now(timezone.utc) - start_time).days

                findings.append({
                    "resource_id": snapshot_id,
                    "resource_type": "aws_ebs_snapshot",
                    "check_name": "old_snapshot",
                    "severity": _severity_for_cost(monthly_cost),
                    "category": "cleanup",
                    "description": (
                        f"Snapshot {snapshot_id} ({volume_size} GiB) is "
                        f"{age} days old — estimated cost "
                        f"${monthly_cost:.2f}/month."
                    ),
                    "recommendation": (
                        "If retained for compliance or DR, move to the Archive "
                        "tier (cheaper for cold storage). Otherwise delete."
                    ),
                    "metadata": {
                        "volume_size_gb": volume_size,
                        "monthly_cost_usd": monthly_cost,
                        "start_time": start_time.isoformat(),
                        "age_days": age,
                        "description": snap.get("Description"),
                    },
                })
            except Exception as e:  # noqa: BLE001
                logger.exception("Failed to evaluate snapshot %s: %s", snapshot_id, e)

    logger.info("Old-snapshot scan (>%dd): %d findings", age_days, len(findings))
    return findings
