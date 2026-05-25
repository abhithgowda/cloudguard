"""Unit tests for src/security_scanner/ checkers.

Each checker is a pure function taking its boto3 client as a parameter
(STEP 11 decision — same dependency-injection seam as cost_analyzer).
Tests pass `MagicMock()` clients shaped like the AWS responses and assert
on the returned finding list.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

import sg_checker
import s3_checker
import iam_checker
import ebs_checker
import config_checker


# ---------------------------------------------------------------------------
# sg_checker — the textbook lateral-movement entry point
# ---------------------------------------------------------------------------


def _ec2_paginator(pages):
    """Build a boto3-style paginator mock for ec2.describe_*."""
    paginator = MagicMock()
    paginator.paginate.return_value = iter(pages)
    return paginator


class TestSgChecker:
    def _ec2_with_sgs(self, sgs):
        client = MagicMock()
        client.get_paginator.return_value = _ec2_paginator([
            {"SecurityGroups": sgs}
        ])
        return client

    def test_ssh_open_to_world_is_critical(self):
        ec2 = self._ec2_with_sgs([{
            "GroupId": "sg-1", "GroupName": "ssh-open", "VpcId": "vpc-1",
            "IpPermissions": [{
                "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }],
        }])
        findings = sg_checker.check_security_groups(ec2)
        assert len(findings) == 1
        assert findings[0]["severity"] == "CRITICAL"
        assert findings[0]["resource_id"] == "sg-1"
        assert findings[0]["resource_type"] == "aws_security_group"

    def test_rdp_open_to_world_is_critical(self):
        ec2 = self._ec2_with_sgs([{
            "GroupId": "sg-2", "GroupName": "rdp", "VpcId": "vpc-1",
            "IpPermissions": [{
                "IpProtocol": "tcp", "FromPort": 3389, "ToPort": 3389,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }],
        }])
        findings = sg_checker.check_security_groups(ec2)
        assert findings[0]["severity"] == "CRITICAL"

    def test_all_traffic_open_is_critical(self):
        # IpProtocol = "-1" is AWS's "all protocols, all ports" sentinel.
        ec2 = self._ec2_with_sgs([{
            "GroupId": "sg-3", "GroupName": "all-open", "VpcId": "vpc-1",
            "IpPermissions": [{
                "IpProtocol": "-1",
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }],
        }])
        findings = sg_checker.check_security_groups(ec2)
        assert findings[0]["severity"] == "CRITICAL"

    def test_non_admin_port_open_is_high(self):
        # Postgres 5432 to the world — not as bad as SSH but still wrong.
        ec2 = self._ec2_with_sgs([{
            "GroupId": "sg-4", "GroupName": "pg", "VpcId": "vpc-1",
            "IpPermissions": [{
                "IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }],
        }])
        findings = sg_checker.check_security_groups(ec2)
        assert findings[0]["severity"] == "HIGH"

    def test_port_80_open_is_not_flagged(self):
        # Public web traffic to 80/443 is legitimate.
        ec2 = self._ec2_with_sgs([{
            "GroupId": "sg-5", "GroupName": "web", "VpcId": "vpc-1",
            "IpPermissions": [{
                "IpProtocol": "tcp", "FromPort": 80, "ToPort": 80,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }],
        }])
        assert sg_checker.check_security_groups(ec2) == []

    def test_internal_cidr_is_not_flagged(self):
        ec2 = self._ec2_with_sgs([{
            "GroupId": "sg-6", "GroupName": "internal", "VpcId": "vpc-1",
            "IpPermissions": [{
                "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                "IpRanges": [{"CidrIp": "10.0.0.0/8"}],
            }],
        }])
        assert sg_checker.check_security_groups(ec2) == []

    def test_ipv6_ssh_open_is_critical(self):
        ec2 = self._ec2_with_sgs([{
            "GroupId": "sg-7", "GroupName": "v6", "VpcId": "vpc-1",
            "IpPermissions": [{
                "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                "Ipv6Ranges": [{"CidrIpv6": "::/0"}],
            }],
        }])
        findings = sg_checker.check_security_groups(ec2)
        assert findings[0]["severity"] == "CRITICAL"


# ---------------------------------------------------------------------------
# s3_checker — the 4-checks-per-bucket fan-out
# ---------------------------------------------------------------------------


class TestS3Checker:
    def _client_error(self, code):
        return ClientError({"Error": {"Code": code, "Message": "x"}}, "op")

    def _s3_with_buckets(self, names):
        client = MagicMock()
        client.list_buckets.return_value = {
            "Buckets": [{"Name": n} for n in names]
        }
        return client

    def test_no_public_access_block_is_high(self):
        s3 = self._s3_with_buckets(["bucket-1"])
        s3.get_public_access_block.side_effect = self._client_error(
            "NoSuchPublicAccessBlockConfiguration"
        )
        # Other 3 checks return clean shapes.
        s3.get_bucket_encryption.return_value = {}
        s3.get_bucket_policy.side_effect = self._client_error("NoSuchBucketPolicy")
        s3.get_bucket_versioning.return_value = {"Status": "Enabled"}

        findings = s3_checker.check_s3_buckets(s3)

        pab_findings = [f for f in findings if "public_access_block" in f["check_name"]]
        assert len(pab_findings) == 1
        assert pab_findings[0]["severity"] == "HIGH"

    def test_pab_with_some_settings_false_is_high(self):
        s3 = self._s3_with_buckets(["bucket-2"])
        s3.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": False,   # disabled — flagged
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        }
        s3.get_bucket_encryption.return_value = {}
        s3.get_bucket_policy.side_effect = self._client_error("NoSuchBucketPolicy")
        s3.get_bucket_versioning.return_value = {"Status": "Enabled"}

        findings = s3_checker.check_s3_buckets(s3)
        pab = [f for f in findings if "public_access_block_disabled" in f["check_name"]]
        assert pab[0]["severity"] == "HIGH"
        assert pab[0]["metadata"]["disabled_settings"] == ["IgnorePublicAcls"]

    def test_no_default_encryption_is_high(self):
        s3 = self._s3_with_buckets(["bucket-3"])
        s3.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            }
        }
        s3.get_bucket_encryption.side_effect = self._client_error(
            "ServerSideEncryptionConfigurationNotFoundError"
        )
        s3.get_bucket_policy.side_effect = self._client_error("NoSuchBucketPolicy")
        s3.get_bucket_versioning.return_value = {"Status": "Enabled"}

        findings = s3_checker.check_s3_buckets(s3)
        enc = [f for f in findings if "no_default_encryption" in f["check_name"]]
        assert enc[0]["severity"] == "HIGH"

    def test_bucket_policy_with_wildcard_principal_is_critical(self):
        s3 = self._s3_with_buckets(["public-bucket"])
        s3.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            }
        }
        s3.get_bucket_encryption.return_value = {}
        s3.get_bucket_policy.return_value = {
            "Policy": (
                '{"Statement": [{"Effect": "Allow", "Principal": "*", '
                '"Action": "s3:GetObject", "Resource": "*"}]}'
            )
        }
        s3.get_bucket_versioning.return_value = {"Status": "Enabled"}

        findings = s3_checker.check_s3_buckets(s3)
        public = [f for f in findings if "bucket_policy_public" in f["check_name"]]
        assert public[0]["severity"] == "CRITICAL"

    def test_versioning_disabled_is_low(self):
        s3 = self._s3_with_buckets(["b"])
        s3.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            }
        }
        s3.get_bucket_encryption.return_value = {}
        s3.get_bucket_policy.side_effect = self._client_error("NoSuchBucketPolicy")
        s3.get_bucket_versioning.return_value = {}

        findings = s3_checker.check_s3_buckets(s3)
        ver = [f for f in findings if "versioning_disabled" in f["check_name"]]
        assert ver[0]["severity"] == "LOW"

    def test_clean_bucket_no_findings(self):
        s3 = self._s3_with_buckets(["clean-bucket"])
        s3.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            }
        }
        s3.get_bucket_encryption.return_value = {}
        s3.get_bucket_policy.side_effect = self._client_error("NoSuchBucketPolicy")
        s3.get_bucket_versioning.return_value = {"Status": "Enabled"}

        assert s3_checker.check_s3_buckets(s3) == []

    def test_one_bad_bucket_doesnt_kill_the_scan(self):
        # bucket-A explodes on PAB lookup, bucket-B is clean.
        # Scan should still return for bucket-B's checks (clean → no findings).
        s3 = MagicMock()
        s3.list_buckets.return_value = {
            "Buckets": [{"Name": "bucket-A"}, {"Name": "bucket-B"}]
        }
        def pab_side_effect(Bucket):
            if Bucket == "bucket-A":
                raise RuntimeError("permission denied")
            return {"PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            }}
        s3.get_public_access_block.side_effect = pab_side_effect
        s3.get_bucket_encryption.return_value = {}
        s3.get_bucket_policy.side_effect = self._client_error("NoSuchBucketPolicy")
        s3.get_bucket_versioning.return_value = {"Status": "Enabled"}

        # Should not raise; bucket-A errors are caught and logged.
        findings = s3_checker.check_s3_buckets(s3)
        assert isinstance(findings, list)


# ---------------------------------------------------------------------------
# iam_checker — user audit
# ---------------------------------------------------------------------------


class TestIamChecker:
    def _iam_with_users(self, users):
        client = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = iter([{"Users": users}])
        client.get_paginator.return_value = paginator
        return client

    def test_old_access_key_is_medium(self):
        iam = self._iam_with_users([{"UserName": "alice"}])
        # Key created 100 days ago — exceeds 90-day threshold.
        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        iam.list_access_keys.return_value = {
            "AccessKeyMetadata": [{
                "AccessKeyId": "AKIA1", "Status": "Active",
                "CreateDate": old_date,
            }]
        }
        iam.get_access_key_last_used.return_value = {
            "AccessKeyLastUsed": {"LastUsedDate": datetime.now(timezone.utc)}
        }
        iam.list_mfa_devices.return_value = {"MFADevices": [{"SerialNumber": "x"}]}
        iam.list_attached_user_policies.return_value = {"AttachedPolicies": []}

        findings = iam_checker.check_iam_users(iam)
        old = [f for f in findings if "access_key_old" in f["check_name"]]
        assert old[0]["severity"] == "MEDIUM"
        assert old[0]["resource_id"] == "alice"

    def test_unused_access_key_is_medium(self):
        iam = self._iam_with_users([{"UserName": "bob"}])
        # Recently created but unused for >90 days.
        iam.list_access_keys.return_value = {
            "AccessKeyMetadata": [{
                "AccessKeyId": "AKIA2", "Status": "Active",
                "CreateDate": datetime.now(timezone.utc) - timedelta(days=10),
            }]
        }
        iam.get_access_key_last_used.return_value = {
            "AccessKeyLastUsed": {
                "LastUsedDate": datetime.now(timezone.utc) - timedelta(days=120)
            }
        }
        iam.list_mfa_devices.return_value = {"MFADevices": [{"SerialNumber": "x"}]}
        iam.list_attached_user_policies.return_value = {"AttachedPolicies": []}

        findings = iam_checker.check_iam_users(iam)
        unused = [f for f in findings if "access_key_unused" in f["check_name"]]
        assert unused[0]["severity"] == "MEDIUM"

    def test_no_mfa_is_high(self):
        iam = self._iam_with_users([{"UserName": "carol"}])
        iam.list_access_keys.return_value = {"AccessKeyMetadata": []}
        iam.list_mfa_devices.return_value = {"MFADevices": []}
        iam.list_attached_user_policies.return_value = {"AttachedPolicies": []}

        findings = iam_checker.check_iam_users(iam)
        mfa = [f for f in findings if "no_mfa" in f["check_name"]]
        assert mfa[0]["severity"] == "HIGH"

    def test_administrator_access_attached_is_high(self):
        iam = self._iam_with_users([{"UserName": "dave"}])
        iam.list_access_keys.return_value = {"AccessKeyMetadata": []}
        iam.list_mfa_devices.return_value = {"MFADevices": [{"SerialNumber": "x"}]}
        iam.list_attached_user_policies.return_value = {
            "AttachedPolicies": [
                {"PolicyName": "AdministratorAccess",
                 "PolicyArn": "arn:aws:iam::aws:policy/AdministratorAccess"}
            ]
        }

        findings = iam_checker.check_iam_users(iam)
        admin = [f for f in findings if "admin_attached" in f["check_name"]]
        assert admin[0]["severity"] == "HIGH"

    def test_clean_user_no_findings(self):
        iam = self._iam_with_users([{"UserName": "eve"}])
        iam.list_access_keys.return_value = {"AccessKeyMetadata": []}
        iam.list_mfa_devices.return_value = {"MFADevices": [{"SerialNumber": "x"}]}
        iam.list_attached_user_policies.return_value = {"AttachedPolicies": []}

        assert iam_checker.check_iam_users(iam) == []


# ---------------------------------------------------------------------------
# ebs_checker — unencrypted-volume detection
# ---------------------------------------------------------------------------


class TestEbsChecker:
    def _ec2_with_volumes(self, volumes):
        client = MagicMock()
        client.get_paginator.return_value = _ec2_paginator([
            {"Volumes": volumes}
        ])
        return client

    def test_unencrypted_in_use_is_high(self):
        ec2 = self._ec2_with_volumes([{
            "VolumeId": "vol-1", "Size": 100, "VolumeType": "gp3",
            "State": "in-use", "Encrypted": False,
            "AvailabilityZone": "ap-south-1a",
        }])
        findings = ebs_checker.check_ebs_encryption(ec2)
        assert len(findings) == 1
        assert findings[0]["severity"] == "HIGH"

    def test_unencrypted_available_is_medium(self):
        ec2 = self._ec2_with_volumes([{
            "VolumeId": "vol-2", "Size": 100, "VolumeType": "gp3",
            "State": "available", "Encrypted": False,
        }])
        findings = ebs_checker.check_ebs_encryption(ec2)
        assert findings[0]["severity"] == "MEDIUM"

    def test_encrypted_volume_no_finding(self):
        ec2 = self._ec2_with_volumes([{
            "VolumeId": "vol-3", "Size": 100, "VolumeType": "gp3",
            "State": "in-use", "Encrypted": True,
        }])
        assert ebs_checker.check_ebs_encryption(ec2) == []


# ---------------------------------------------------------------------------
# config_checker — AWS Config compliance aggregator
# ---------------------------------------------------------------------------


class TestConfigChecker:
    def test_graceful_noop_when_config_not_enabled(self):
        config = MagicMock()
        config.describe_compliance_by_config_rule.side_effect = ClientError(
            {"Error": {"Code": "NoSuchConfigurationRecorderException", "Message": "x"}},
            "DescribeComplianceByConfigRule",
        )
        findings = config_checker.check_config_compliance(config)
        assert findings == []  # quiet skip, no raise

    def test_access_denied_is_also_graceful(self):
        config = MagicMock()
        config.describe_compliance_by_config_rule.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "no"}},
            "DescribeComplianceByConfigRule",
        )
        assert config_checker.check_config_compliance(config) == []

    def test_critical_rule_promoted_to_critical_severity(self):
        config = MagicMock()
        # Page 1: one non-compliant rule.
        config.describe_compliance_by_config_rule.return_value = {
            "ComplianceByConfigRules": [{
                "ConfigRuleName": "root-account-mfa-enabled",
                "Compliance": {"ComplianceType": "NON_COMPLIANT"},
            }],
        }
        config.get_compliance_details_by_config_rule.return_value = {
            "EvaluationResults": [{
                "EvaluationResultIdentifier": {
                    "EvaluationResultQualifier": {
                        "ResourceType": "AWS::IAM::Account",
                        "ResourceId": "123456789012",
                    }
                },
                "Annotation": "Root account has no MFA",
            }],
        }

        findings = config_checker.check_config_compliance(config)
        assert len(findings) == 1
        assert findings[0]["severity"] == "CRITICAL"
        assert findings[0]["check_name"] == "config_rule:root-account-mfa-enabled"

    def test_high_rule_promoted_to_high_severity(self):
        config = MagicMock()
        config.describe_compliance_by_config_rule.return_value = {
            "ComplianceByConfigRules": [{
                "ConfigRuleName": "encrypted-volumes",
                "Compliance": {"ComplianceType": "NON_COMPLIANT"},
            }],
        }
        config.get_compliance_details_by_config_rule.return_value = {
            "EvaluationResults": [{
                "EvaluationResultIdentifier": {
                    "EvaluationResultQualifier": {
                        "ResourceType": "AWS::EC2::Volume",
                        "ResourceId": "vol-abc",
                    }
                },
            }],
        }
        findings = config_checker.check_config_compliance(config)
        assert findings[0]["severity"] == "HIGH"

    def test_unknown_rule_defaults_to_medium(self):
        config = MagicMock()
        config.describe_compliance_by_config_rule.return_value = {
            "ComplianceByConfigRules": [{
                "ConfigRuleName": "some-obscure-managed-rule",
                "Compliance": {"ComplianceType": "NON_COMPLIANT"},
            }],
        }
        config.get_compliance_details_by_config_rule.return_value = {
            "EvaluationResults": [{
                "EvaluationResultIdentifier": {
                    "EvaluationResultQualifier": {
                        "ResourceType": "AWS::S3::Bucket",
                        "ResourceId": "some-bucket",
                    }
                },
            }],
        }
        findings = config_checker.check_config_compliance(config)
        assert findings[0]["severity"] == "MEDIUM"
