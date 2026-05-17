"""EBS volume encryption checker.

Flags any EBS volume in the account that is not encrypted at rest. AWS now
defaults new volumes to encrypted in most regions when the account-level
"EBS encryption by default" setting is on, but legacy volumes created
before that setting was enabled remain unencrypted forever — and a single
unencrypted volume can fail a SOC2/PCI control.

Severity:
  - Unencrypted volume in `in-use` state  -> HIGH (active data exposure)
  - Unencrypted volume in `available` state -> MEDIUM (still a data risk)
"""

import logging

logger = logging.getLogger(__name__)


def check_ebs_encryption(ec2_client):
    """Scan every EBS volume in the region; return list of findings."""
    findings = []
    paginator = ec2_client.get_paginator("describe_volumes")

    volume_count = 0
    for page in paginator.paginate():
        for vol in page.get("Volumes", []):
            volume_count += 1
            if vol.get("Encrypted"):
                continue

            volume_id = vol["VolumeId"]
            state = vol.get("State", "unknown")
            severity = "HIGH" if state == "in-use" else "MEDIUM"

            findings.append(
                {
                    "resource_id": volume_id,
                    "resource_type": "aws_ebs_volume",
                    "check_name": "ebs_volume_unencrypted",
                    "severity": severity,
                    "category": "security",
                    "description": (
                        f"EBS volume {volume_id} ({vol.get('Size')} GiB, "
                        f"type={vol.get('VolumeType')}, state={state}) is not encrypted."
                    ),
                    "recommendation": (
                        "Snapshot the volume, create an encrypted copy of the snapshot, "
                        "create a new volume from the encrypted snapshot, and swap it in. "
                        "Then enable account-level 'EBS encryption by default' to prevent "
                        "any future unencrypted volume."
                    ),
                    "metadata": {
                        "size_gib": vol.get("Size"),
                        "volume_type": vol.get("VolumeType"),
                        "state": state,
                        "availability_zone": vol.get("AvailabilityZone"),
                    },
                }
            )

    logger.info("EBS check: %d findings across %d volumes", len(findings), volume_count)
    return findings