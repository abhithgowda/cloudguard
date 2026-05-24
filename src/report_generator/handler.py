"""CloudGuard Report Generator — Lambda entrypoint.

Reads findings + cost data + remediation log from DynamoDB over a configurable
window (default 24h), builds a full HTML report, uploads it to the reports
S3 bucket, generates a pre-signed URL (7-day max per SigV4), emails a short
summary via SES, and publishes an SNS notification.

Event input (optional):
    {"report_window_hours": 24 | 168}   # daily vs weekly digest

Wiring (env vars set by the Lambda Terraform module — see dev/main.tf):
    FINDINGS_TABLE, COST_DATA_TABLE, REMEDIATION_LOG_TABLE
    REPORTS_BUCKET
    SNS_TOPIC_ARN
    ALERT_EMAIL              recipient
    SES_SENDER_EMAIL         verified SES identity (often == ALERT_EMAIL)
    REPORT_WINDOW_HOURS      default window if event input is absent
    ENVIRONMENT, LOG_LEVEL

Query strategy (STEP 13 decision, documented in PROGRESS.md):
    findings + remediation_log → Scan + FilterExpression on timestamp
    cost_data                  → Scan, capped to N days from latest
This is honest about scale: at >~10k items per table, swap in a 4th GSI on
(environment, timestamp) and use Query. Acceptable for the dev workload here.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from html_builder import build_email_summary, build_report

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_dynamodb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")
_ses = boto3.client("ses")
_sns = boto3.client("sns")

PRESIGNED_URL_TTL_SECONDS = 7 * 24 * 3600  # SigV4 hard cap = 7 days.


def lambda_handler(event: dict[str, Any] | None, context):
    event = event or {}
    environment = os.environ.get("ENVIRONMENT", "dev")
    window_hours = int(
        event.get("report_window_hours")
        or os.environ.get("REPORT_WINDOW_HOURS", "24")
    )

    findings_table = _dynamodb.Table(os.environ["FINDINGS_TABLE"])
    cost_data_table = _dynamodb.Table(os.environ["COST_DATA_TABLE"])
    remediation_table = _dynamodb.Table(os.environ["REMEDIATION_LOG_TABLE"])

    bucket = os.environ["REPORTS_BUCKET"]
    sender = os.environ["SES_SENDER_EMAIL"]
    recipient = os.environ["ALERT_EMAIL"]
    topic_arn = os.environ["SNS_TOPIC_ARN"]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    cutoff_iso = cutoff.isoformat()

    logger.info(
        "Building %dh report for %s — cutoff %s", window_hours, environment, cutoff_iso
    )

    findings = _scan_with_filter(findings_table, Attr("timestamp").gte(cutoff_iso))
    remediations = _scan_with_filter(
        remediation_table, Attr("timestamp").gte(cutoff_iso)
    )
    # Cost data window: at minimum 30 days so the trend table is meaningful
    # even for a 24h report. Anything older than 30d is noise.
    cost_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    cost_data = _scan_with_filter(cost_data_table, Attr("date").gte(cost_cutoff))

    logger.info(
        "Loaded %d findings, %d cost rows, %d remediations",
        len(findings),
        len(cost_data),
        len(remediations),
    )

    generated_at = datetime.now(timezone.utc)
    full_html = build_report(
        findings=findings,
        cost_data=cost_data,
        remediations=remediations,
        window_hours=window_hours,
        environment=environment,
        generated_at=generated_at,
    )

    s3_key = _build_s3_key(environment, window_hours, generated_at)
    _s3.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=full_html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        # Belt-and-braces — the bucket policy already denies plaintext and
        # the bucket default is SSE-KMS. ServerSideEncryption arg here is
        # informational; the bucket-level default still applies.
        ServerSideEncryption="aws:kms",
    )
    logger.info("Uploaded report to s3://%s/%s", bucket, s3_key)

    report_url = _s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )

    email_html = build_email_summary(
        findings=findings,
        cost_data=cost_data,
        remediations=remediations,
        window_hours=window_hours,
        environment=environment,
        report_url=report_url,
    )

    email_sent = _send_email(
        sender=sender,
        recipient=recipient,
        environment=environment,
        window_hours=window_hours,
        critical_count=sum(1 for f in findings if f.get("severity") == "CRITICAL"),
        body_html=email_html,
        report_url=report_url,
    )

    _publish_sns(
        topic_arn=topic_arn,
        environment=environment,
        window_hours=window_hours,
        findings_count=len(findings),
        report_url=report_url,
    )

    summary = {
        "findings_count": len(findings),
        "cost_rows_count": len(cost_data),
        "remediation_count": len(remediations),
        "report_s3_key": s3_key,
        "report_url_ttl_days": PRESIGNED_URL_TTL_SECONDS // 86400,
        "email_sent": email_sent,
        "window_hours": window_hours,
    }
    logger.info("Summary: %s", json.dumps(summary))
    return summary


# ---------------------------------------------------------------------------
# Helpers (kept here, not in html_builder, because they touch boto3).
# ---------------------------------------------------------------------------


def _scan_with_filter(table, filter_expression) -> list[dict]:
    """Page through a Scan, returning all items matching the filter.

    DynamoDB Scan is paginated by `LastEvaluatedKey`; the standard pattern is
    a while-loop. boto3's `client.get_paginator('scan')` works on the *client*,
    not the resource. Hand-rolled here since we use the resource API.
    """
    items: list[dict] = []
    kwargs: dict[str, Any] = {"FilterExpression": filter_expression}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


def _build_s3_key(environment: str, window_hours: int, when: datetime) -> str:
    return (
        f"reports/{environment}/{when:%Y/%m/%d}/"
        f"report-{window_hours}h-{when:%Y%m%dT%H%M%SZ}.html"
    )


def _send_email(
    *,
    sender: str,
    recipient: str,
    environment: str,
    window_hours: int,
    critical_count: int,
    body_html: str,
    report_url: str,
) -> bool:
    """Send via SES. Returns True on success, False if SES rejects.

    SES errors are caught and logged rather than re-raised — a delivery failure
    shouldn't fail the whole Lambda when the report is already in S3 and SNS
    can also alert. The S3 object + SNS publish are the durable signals; SES
    is the convenience channel.
    """
    subject = (
        f"[CloudGuard {environment}] {window_hours}h report"
        + (f" — {critical_count} CRITICAL" if critical_count else "")
    )
    text_body = (
        f"CloudGuard {environment} report — last {window_hours}h.\n"
        f"Critical findings: {critical_count}\n"
        f"Full report (link valid 7 days): {report_url}\n"
    )
    try:
        _ses.send_email(
            Source=sender,
            Destination={"ToAddresses": [recipient]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            },
        )
        return True
    except ClientError as e:
        # MessageRejected is the most likely error in sandbox SES — both the
        # sender and the recipient must be verified identities. Log loudly so
        # the operator sees it in CloudWatch.
        logger.exception(
            "SES send_email failed (sender=%s recipient=%s): %s",
            sender,
            recipient,
            e,
        )
        return False


def _publish_sns(
    *,
    topic_arn: str,
    environment: str,
    window_hours: int,
    findings_count: int,
    report_url: str,
) -> None:
    message = (
        f"CloudGuard {environment}: {findings_count} findings in last "
        f"{window_hours}h. Report: {report_url}"
    )
    try:
        _sns.publish(
            TopicArn=topic_arn,
            Subject=f"CloudGuard {environment} report ({window_hours}h)",
            Message=message,
        )
    except ClientError as e:  # noqa: BLE001
        # Same reasoning as SES — SNS failure shouldn't break the lambda.
        logger.exception("SNS publish failed: %s", e)
