"""AWS Config compliance checker.

For every active Config rule in the region, fetches the rule's overall
compliance status and — for non-compliant rules — the specific resources
that failed evaluation. Emits one finding per non-compliant resource.

Severity ladder is intentionally MEDIUM by default: Config rule criticality
varies enormously (root-mfa-enabled is CRITICAL; s3-bucket-logging-enabled
is more of a hygiene warning), but the per-rule criticality isn't carried
by the Config API. Bump specific rules to HIGH/CRITICAL via the
CRITICAL_RULES / HIGH_RULES sets below as you tune in production.

Graceful no-op: if AWS Config is not enabled in the account (no
configuration recorder), the API raises NoSuchConfigurationRecorder...
which we catch and return an empty list — the scan continues over the
other security categories.
"""

import logging

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Rules whose failure is critical even without per-account context.
# Add to these sets as you onboard managed rules in production.
CRITICAL_RULES = {
    "root-account-mfa-enabled",
    "iam-root-access-key-check",
    "s3-bucket-public-read-prohibited",
    "s3-bucket-public-write-prohibited",
}
HIGH_RULES = {
    "encrypted-volumes",
    "rds-storage-encrypted",
    "s3-bucket-server-side-encryption-enabled",
    "iam-password-policy",
    "vpc-flow-logs-enabled",
}


def _severity_for_rule(rule_name):
    if rule_name in CRITICAL_RULES:
        return "CRITICAL"
    if rule_name in HIGH_RULES:
        return "HIGH"
    return "MEDIUM"


def _finding(rule_name, severity, resource_type, resource_id, annotation):
    return {
        "resource_id": resource_id or rule_name,
        "resource_type": resource_type or "aws_config_rule",
        "check_name": f"config_rule:{rule_name}",
        "severity": severity,
        "category": "security",
        "description": (
            f"AWS Config rule '{rule_name}' marked {resource_type or 'rule'} "
            f"'{resource_id or rule_name}' as NON_COMPLIANT"
            + (f": {annotation}" if annotation else ".")
        ),
        "recommendation": (
            f"Review the AWS Config rule '{rule_name}' in the console — it "
            "documents the specific compliance condition that failed and "
            "the remediation steps. Many managed rules ship with an "
            "auto-remediation SSM document."
        ),
        "metadata": {
            "config_rule": rule_name,
            "annotation": annotation,
        },
    }


def _list_noncompliant_rules(config_client):
    """Page through DescribeComplianceByConfigRule, yield NON_COMPLIANT rule names."""
    next_token = None
    while True:
        kwargs = {"ComplianceTypes": ["NON_COMPLIANT"]}
        if next_token:
            kwargs["NextToken"] = next_token
        resp = config_client.describe_compliance_by_config_rule(**kwargs)

        for rule in resp.get("ComplianceByConfigRules", []):
            compliance = rule.get("Compliance", {}).get("ComplianceType")
            if compliance == "NON_COMPLIANT":
                yield rule["ConfigRuleName"]

        next_token = resp.get("NextToken")
        if not next_token:
            return


def _list_noncompliant_resources(config_client, rule_name):
    """Page through GetComplianceDetailsByConfigRule for this rule."""
    next_token = None
    while True:
        kwargs = {
            "ConfigRuleName": rule_name,
            "ComplianceTypes": ["NON_COMPLIANT"],
            "Limit": 100,
        }
        if next_token:
            kwargs["NextToken"] = next_token
        resp = config_client.get_compliance_details_by_config_rule(**kwargs)

        for result in resp.get("EvaluationResults", []):
            qualifier = result.get("EvaluationResultIdentifier", {}).get(
                "EvaluationResultQualifier", {}
            )
            yield {
                "resource_type": qualifier.get("ResourceType"),
                "resource_id": qualifier.get("ResourceId"),
                "annotation": result.get("Annotation"),
            }

        next_token = resp.get("NextToken")
        if not next_token:
            return


def check_config_compliance(config_client):
    """Scan AWS Config for NON_COMPLIANT rule evaluations; return findings."""
    findings = []
    try:
        rules = list(_list_noncompliant_rules(config_client))
    except ClientError as e:
        code = e.response["Error"]["Code"]
        # Config not enabled in this account/region — graceful no-op.
        if code in {
            "NoSuchConfigurationRecorderException",
            "InvalidConfigurationRecorderName",
            "AccessDeniedException",
        }:
            logger.warning("AWS Config unavailable (%s); skipping config check", code)
            return findings
        raise

    for rule_name in rules:
        severity = _severity_for_rule(rule_name)
        try:
            for resource in _list_noncompliant_resources(config_client, rule_name):
                findings.append(
                    _finding(
                        rule_name=rule_name,
                        severity=severity,
                        resource_type=resource["resource_type"],
                        resource_id=resource["resource_id"],
                        annotation=resource["annotation"],
                    )
                )
        except ClientError as e:
            logger.warning("Get details failed for rule %s: %s", rule_name, e)
            continue

    logger.info(
        "Config check: %d findings across %d non-compliant rules",
        len(findings),
        len(rules),
    )
    return findings