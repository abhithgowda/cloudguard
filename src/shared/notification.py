"""Alerting helpers — SNS publish and Slack webhook delivery.

Both functions take all required inputs as parameters. No Secrets Manager
calls live here: the caller fetches the Slack webhook URL from Secrets
Manager and passes it in, keeping this module pure and unit-testable
without mocking the Secrets Manager client.

Slack delivery uses ``urllib.request`` from the stdlib rather than the
``requests`` library to avoid adding ~100 KB to every Lambda zip — every
function this module ships with would otherwise need ``requests`` in its
``requirements.txt``.

Each Lambda's deployment zip bundles its own copy of this module (see
``scripts/package_lambdas.sh`` in STEP 19).
"""

import json
import logging
import urllib.error
import urllib.request

import boto3

logger = logging.getLogger(__name__)

_SNS_CLIENT = None


def _get_sns_client():
    """Module-scope cached SNS client — reused across warm invocations."""
    global _SNS_CLIENT
    if _SNS_CLIENT is None:
        _SNS_CLIENT = boto3.client("sns")
    return _SNS_CLIENT


def send_sns_alert(topic_arn, subject, message, sns_client=None):
    """Publish a message to an SNS topic.

    AWS truncates ``Subject`` above 100 characters; this function caps it
    explicitly so the truncation is visible in the caller's logs rather
    than silently performed by SNS. ``message`` may be a string or a
    JSON-serialisable dict/list (encoded with ``default=str`` so values
    like ``Decimal`` and ``datetime`` survive).

    Returns the ``MessageId`` on success. Raises
    ``botocore.exceptions.ClientError`` on failure — the caller decides
    whether to swallow it (the report_generator does; the cost_scanner
    does not publish at all).
    """
    client = sns_client or _get_sns_client()

    if isinstance(message, (dict, list)):
        message_body = json.dumps(message, default=str)
    else:
        message_body = str(message)

    response = client.publish(
        TopicArn=topic_arn,
        Subject=subject[:100],
        Message=message_body,
    )
    message_id = response.get("MessageId")
    logger.info("send_sns_alert: published MessageId=%s to %s", message_id, topic_arn)
    return message_id


def send_slack_webhook(webhook_url, message_payload, timeout_seconds=5):
    """POST a JSON payload to a Slack incoming webhook URL.

    Args:
        webhook_url: full ``https://hooks.slack.com/services/...`` URL.
            The caller is expected to fetch this from Secrets Manager and
            pass it in — keeps this function free of Secrets Manager mocks.
        message_payload: dict matching Slack's webhook payload schema,
            e.g. ``{"text": "...", "blocks": [...]}``.
        timeout_seconds: socket timeout. Slack's incoming-webhook SLA is
            typically sub-second; 5 s is a generous ceiling.

    Returns ``True`` on HTTP 2xx, ``False`` otherwise. Does NOT raise on
    network failure — a Slack outage should not break a Lambda whose
    primary job is writing findings to DynamoDB; the failure is logged
    and the caller continues.
    """
    data = json.dumps(message_payload, default=str).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = response.status
            if 200 <= status < 300:
                logger.info("send_slack_webhook: delivered (HTTP %d)", status)
                return True
            logger.warning("send_slack_webhook: non-2xx response (HTTP %d)", status)
            return False
    except urllib.error.URLError as exc:
        logger.warning("send_slack_webhook: delivery failed (%s)", exc)
        return False
    except Exception as exc:  # noqa: BLE001 — Slack must not break the caller
        logger.warning("send_slack_webhook: unexpected error (%s)", exc)
        return False
