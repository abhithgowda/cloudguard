"""Unit tests for src/report_generator/.

html_builder.py — pure functions, just feed synthetic data and assert on the
                  rendered string. No I/O.
handler.py      — focus on the SES/SNS failure-tolerance contract: the S3
                  archive is the durable output; a failed SES send must NOT
                  fail the Lambda invocation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import html_builder


# ---------------------------------------------------------------------------
# html_builder.build_report — the full archived HTML
# ---------------------------------------------------------------------------


def _sample_findings():
    return [
        {
            "finding_id": "f1", "timestamp": "2026-05-25T10:00:00+00:00",
            "category": "security", "severity": "CRITICAL",
            "resource_id": "sg-0abc",
            "resource_type": "aws_security_group",
            "check_name": "sg_open_to_world",
            "description": "Security group sg-0abc has SSH open to 0.0.0.0/0",
            "recommendation": "Restrict to office CIDR.",
        },
        {
            "finding_id": "f2", "timestamp": "2026-05-25T10:00:00+00:00",
            "category": "cost", "severity": "HIGH",
            "resource_id": "AmazonEC2",
            "check_name": "cost_anomaly_30d_baseline",
            "description": "EC2 cost was $85.20, 75% above the 30d average.",
            "expected_cost": Decimal("48.69"),
            "actual_cost": Decimal("85.20"),
            "ratio": Decimal("1.75"),
        },
        {
            "finding_id": "f3", "timestamp": "2026-05-25T10:00:00+00:00",
            "category": "cleanup", "severity": "HIGH",
            "resource_id": "vol-99",
            "resource_type": "aws_ebs_volume",
            "description": "Zombie volume vol-99 (600 GiB io1) — $85.20/mo",
            "metadata": {"monthly_cost_usd": Decimal("85.20"), "size_gb": 600},
        },
    ]


def _sample_cost_rows():
    return [
        {"date": "2026-05-24", "service_name": "AmazonEC2",
         "unblended_cost": Decimal("48.50")},
        {"date": "2026-05-25", "service_name": "AmazonEC2",
         "unblended_cost": Decimal("85.20")},
        {"date": "2026-05-25", "service_name": "AmazonS3",
         "unblended_cost": Decimal("2.40")},
    ]


def _sample_remediations():
    return [
        {"remediation_id": "r1", "status": "SUCCESS",
         "resource_id": "vol-99", "action": "delete_volume"},
        {"remediation_id": "r2", "status": "FAILED",
         "resource_id": "vol-77", "action": "delete_volume",
         "error_message": "Volume is currently attached"},
        {"remediation_id": "r3", "status": "SKIPPED_DRY_RUN",
         "resource_id": "vol-55", "action": "delete_volume"},
    ]


class TestBuildReport:
    def test_renders_full_html_document(self):
        html = html_builder.build_report(
            findings=_sample_findings(),
            cost_data=_sample_cost_rows(),
            remediations=_sample_remediations(),
            window_hours=24,
            environment="dev",
            generated_at=datetime(2026, 5, 25, 10, 30, tzinfo=timezone.utc),
        )

        # Structural assertions.
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert 'lang="en"' in html
        assert "CloudGuard Report — dev" in html
        assert "last 24h" in html
        assert "2026-05-25 10:30 UTC" in html

        # Severity rendering.
        assert "CRITICAL" in html
        assert "HIGH" in html

        # Resource IDs rendered.
        assert "sg-0abc" in html
        assert "AmazonEC2" in html
        assert "vol-99" in html

        # Cost trend table present + dollar formatting.
        assert "Cost Trend" in html
        assert "$85.20" in html

        # Remediation section shows the failed-action error table.
        assert "Volume is currently attached" in html
        assert "1 succeeded" in html and "1 failed" in html
        assert "1 dry-run only" in html

    def test_empty_inputs_render_placeholders(self):
        html = html_builder.build_report(
            findings=[], cost_data=[], remediations=[],
            window_hours=24, environment="dev",
        )
        assert "No security or cost findings" in html
        assert "No cost data" in html
        assert "No cleanup activity" in html

    def test_html_escapes_dangerous_values(self):
        # A finding description containing HTML-fragments must be escaped,
        # not rendered as live markup. None of CloudGuard's writers emit
        # `<script>` today but the html.escape() call is the defence.
        findings = [{
            "category": "security", "severity": "HIGH",
            "resource_id": "<script>alert(1)</script>",
            "description": "Description with <em>html</em> & ampersand",
        }]
        html = html_builder.build_report(
            findings=findings, cost_data=[], remediations=[],
            window_hours=24, environment="dev",
        )
        # Escaped form present.
        assert "&lt;script&gt;" in html
        # Raw script tag NOT present.
        assert "<script>alert" not in html

    def test_estimated_savings_uses_cleanup_metadata(self):
        html = html_builder.build_report(
            findings=_sample_findings(),
            cost_data=[], remediations=[],
            window_hours=24, environment="dev",
        )
        # The cleanup finding has monthly_cost_usd = 85.20.
        assert "$85.20" in html


class TestBuildEmailSummary:
    def test_renders_link_and_summary(self):
        html = html_builder.build_email_summary(
            findings=_sample_findings(),
            cost_data=_sample_cost_rows(),
            remediations=[],
            window_hours=24, environment="dev",
            report_url="https://reports.example.com/x?sig=abc",
        )
        assert "View full report" in html
        assert "https://reports.example.com/x?sig=abc" in html
        assert "Last 24h" in html
        assert "Link expires in 7 days" in html

    def test_url_is_html_escaped(self):
        # Pre-signed URLs contain ampersands — must be escaped in href.
        html = html_builder.build_email_summary(
            findings=[], cost_data=[], remediations=[],
            window_hours=24, environment="dev",
            report_url="https://example.com/?a=1&b=2",
        )
        # The escaped form is present in the href attribute.
        assert "a=1&amp;b=2" in html


class TestCoerceNumber:
    def test_decimal_to_float(self):
        assert html_builder._coerce_number(Decimal("1.5")) == 1.5

    def test_none_to_zero(self):
        assert html_builder._coerce_number(None) == 0.0

    def test_string_to_float(self):
        assert html_builder._coerce_number("3.14") == 3.14

    def test_unparseable_to_zero(self):
        assert html_builder._coerce_number("not a number") == 0.0


# ---------------------------------------------------------------------------
# handler.py — _scan_with_filter, _build_s3_key, _send_email failure path
# ---------------------------------------------------------------------------


@pytest.fixture
def report_handler(monkeypatch, handler_loader):
    """Load the report_generator handler under a unique module name."""
    monkeypatch.setenv("FINDINGS_TABLE", "cloudguard-dev-findings")
    monkeypatch.setenv("COST_DATA_TABLE", "cloudguard-dev-cost-data")
    monkeypatch.setenv("REMEDIATION_LOG_TABLE", "cloudguard-dev-remediation-log")
    monkeypatch.setenv("REPORTS_BUCKET", "cloudguard-dev-reports-x")
    monkeypatch.setenv("SES_SENDER_EMAIL", "alerts@example.com")
    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:ap-south-1:0:cg")
    monkeypatch.setenv("REPORT_WINDOW_HOURS", "24")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    return handler_loader("report_generator")


class TestScanWithFilter:
    def test_paginates_via_last_evaluated_key(self, report_handler):
        table = MagicMock()
        table.scan.side_effect = [
            {"Items": [{"finding_id": "1"}], "LastEvaluatedKey": {"k": "1"}},
            {"Items": [{"finding_id": "2"}]},
        ]
        items = report_handler._scan_with_filter(table, "fake_filter")
        assert [i["finding_id"] for i in items] == ["1", "2"]
        assert table.scan.call_count == 2
        assert table.scan.call_args_list[1].kwargs["ExclusiveStartKey"] == {"k": "1"}


class TestBuildS3Key:
    def test_includes_env_date_partition_and_window(self, report_handler):
        key = report_handler._build_s3_key(
            "dev", 24, datetime(2026, 5, 25, 14, 30, 0, tzinfo=timezone.utc)
        )
        # reports/<env>/<YYYY>/<MM>/<DD>/report-<window>h-<UTC stamp>.html
        assert key == "reports/dev/2026/05/25/report-24h-20260525T143000Z.html"

    def test_weekly_window_in_filename(self, report_handler):
        key = report_handler._build_s3_key(
            "dev", 168, datetime(2026, 5, 25, 0, 0, 0, tzinfo=timezone.utc)
        )
        assert "report-168h" in key


class TestSendEmail:
    def test_ses_failure_returns_false_does_not_raise(self, report_handler):
        # The S3 archive must remain the durable signal — SES failure
        # (most common: sandbox SES rejects unverified recipient) is logged
        # and swallowed.
        report_handler._ses = MagicMock()
        report_handler._ses.send_email.side_effect = ClientError(
            {"Error": {"Code": "MessageRejected", "Message": "unverified"}},
            "SendEmail",
        )
        result = report_handler._send_email(
            sender="a@x.com", recipient="b@x.com",
            environment="dev", window_hours=24, critical_count=1,
            body_html="<html></html>", report_url="https://x",
        )
        assert result is False

    def test_ses_success_returns_true(self, report_handler):
        report_handler._ses = MagicMock()
        report_handler._ses.send_email.return_value = {"MessageId": "m1"}
        result = report_handler._send_email(
            sender="a@x.com", recipient="b@x.com",
            environment="dev", window_hours=24, critical_count=0,
            body_html="<html></html>", report_url="https://x",
        )
        assert result is True
        # Verify the subject reflects critical_count == 0 (no "— N CRITICAL").
        kwargs = report_handler._ses.send_email.call_args.kwargs
        assert "CRITICAL" not in kwargs["Message"]["Subject"]["Data"]

    def test_critical_count_in_subject_when_nonzero(self, report_handler):
        report_handler._ses = MagicMock()
        report_handler._ses.send_email.return_value = {"MessageId": "m1"}
        report_handler._send_email(
            sender="a@x.com", recipient="b@x.com",
            environment="dev", window_hours=24, critical_count=3,
            body_html="<html></html>", report_url="https://x",
        )
        subject = report_handler._ses.send_email.call_args.kwargs[
            "Message"
        ]["Subject"]["Data"]
        assert "3 CRITICAL" in subject


class TestPublishSns:
    def test_sns_failure_swallowed(self, report_handler):
        # Same contract as SES: SNS publish failure must not break the Lambda.
        report_handler._sns = MagicMock()
        report_handler._sns.publish.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "x"}},
            "Publish",
        )
        # Should not raise.
        report_handler._publish_sns(
            topic_arn="arn", environment="dev",
            window_hours=24, findings_count=5, report_url="https://x",
        )
