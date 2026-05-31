"""Security Group checker.

Flags inbound rules open to the world (0.0.0.0/0 or ::/0). Severity ladder:
  - SSH (22) or RDP (3389) open to 0.0.0.0/0       -> CRITICAL
  - "all traffic" (-1 / IpProtocol = "-1") to 0/0  -> CRITICAL
  - Any other non-80/443 port open to 0/0          -> HIGH

Returns a list of finding dicts shaped like the rest of the security scanner.
The caller (handler.py) augments each finding with finding_id + timestamp +
expires_at before writing to DynamoDB.
"""

import logging

logger = logging.getLogger(__name__)

ALLOWED_PUBLIC_PORTS = {80, 443}
CRITICAL_PORTS = {22, 3389}
OPEN_CIDRS_V4 = {"0.0.0.0/0"}
OPEN_CIDRS_V6 = {"::/0"}


def _expand_port_range(rule):
    """Yield each port in this rule's range.

    AWS uses FromPort=-1, ToPort=-1 (or absent) to indicate "all ports" for
    IpProtocol="-1" (all traffic) or for ICMP. Yields a single sentinel None
    for those cases so the caller can treat them as "all ports".
    """
    proto = rule.get("IpProtocol", "")
    from_port = rule.get("FromPort")
    to_port = rule.get("ToPort")

    if proto == "-1" or from_port is None or to_port is None:
        yield None
        return

    if from_port == to_port:
        yield from_port
        return

    yield from range(from_port, to_port + 1)


def _is_open_to_world(rule):
    """Returns (is_open, source_cidr_or_label) for the first open source on this rule."""
    for ip_range in rule.get("IpRanges", []):
        cidr = ip_range.get("CidrIp")
        if cidr in OPEN_CIDRS_V4:
            return True, cidr
    for ipv6_range in rule.get("Ipv6Ranges", []):
        cidr = ipv6_range.get("CidrIpv6")
        if cidr in OPEN_CIDRS_V6:
            return True, cidr
    return False, None


def _evaluate_rule(sg, rule):
    """Build a finding for an open rule, or None if the rule is safe."""
    is_open, source_cidr = _is_open_to_world(rule)
    if not is_open:
        return None

    proto = rule.get("IpProtocol", "")
    ports = list(_expand_port_range(rule))
    all_ports = ports == [None]

    severity = "HIGH"
    reason = ""

    if all_ports or proto == "-1":
        severity = "CRITICAL"
        reason = f"All traffic ({proto or '-1'}) open to {source_cidr}"
    elif any(p in CRITICAL_PORTS for p in ports if p is not None):
        severity = "CRITICAL"
        bad_ports = sorted({p for p in ports if p in CRITICAL_PORTS})
        reason = f"Port {bad_ports} ({proto}) open to {source_cidr}"
    elif any(p not in ALLOWED_PUBLIC_PORTS for p in ports if p is not None):
        severity = "HIGH"
        bad_ports = sorted({p for p in ports if p not in ALLOWED_PUBLIC_PORTS})
        reason = f"Port {bad_ports} ({proto}) open to {source_cidr}"
    else:
        return None

    port_label = "all" if all_ports else f"{rule.get('FromPort')}-{rule.get('ToPort')}"

    # Discriminator on check_name (STEP 21.5) — one SG with TWO open rules
    # (e.g. port 22 + port 8080) must produce TWO distinct finding_ids.
    # Without the proto+port suffix, compute_finding_id collapses both into
    # one row and the second rule's severity / description silently overwrite
    # the first via the upsert path.
    return {
        "resource_id": sg["GroupId"],
        "resource_type": "aws_security_group",
        "check_name": f"sg_open_to_world:{proto or '-1'}:{port_label}",
        "severity": severity,
        "category": "security",
        "description": (
            f"Security group {sg['GroupId']} ({sg.get('GroupName', 'unknown')}) "
            f"in VPC {sg.get('VpcId', 'unknown')}: {reason}."
        ),
        "recommendation": (
            "Restrict the inbound rule to a known CIDR (office IP, VPN range, "
            "or another security group). 0.0.0.0/0 on admin ports is the most "
            "common ingress vector for compromised AWS accounts."
        ),
        "metadata": {
            "vpc_id": sg.get("VpcId"),
            "protocol": proto,
            "port_range": port_label,
            "source": source_cidr,
        },
    }


def check_security_groups(ec2_client):
    """Scan every security group in the region; return list of findings."""
    findings = []
    paginator = ec2_client.get_paginator("describe_security_groups")

    for page in paginator.paginate():
        for sg in page.get("SecurityGroups", []):
            for rule in sg.get("IpPermissions", []):
                finding = _evaluate_rule(sg, rule)
                if finding:
                    findings.append(finding)

    logger.info("SG check: %d findings across scanned groups", len(findings))
    return findings