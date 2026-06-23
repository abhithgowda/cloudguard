"""CloudGuard Remediation Approval — Lambda entrypoint (STEP 25).

Human-in-the-loop layer for the resource_cleanup destructive path. One Lambda,
two responsibilities, dispatched on the event shape:

  1. NOTIFY  (invoked by Step Functions via
     `arn:aws:states:::lambda:invoke.waitForTaskToken`):
        event carries `taskToken`, `resources`, `apiBaseUrl`, `executionName`.
        We mint a short opaque `approval_id`, persist (approval_id → taskToken)
        in the approvals DynamoDB table with a TTL, build HMAC-signed expiring
        Approve / Reject links, and email them via SES. We RETURN immediately;
        the Step Functions execution stays PAUSED on the task token.

  2. CALLBACK (invoked by API Gateway HTTP API, payload format 2.0):
        a human clicked /approve or /reject. We verify the HMAC signature +
        expiry + single-use, look up the real task token, and call
        states:SendTaskSuccess (approve → cleanup proceeds) or
        states:SendTaskFailure (reject → cleanup skipped). The state machine
        resumes.

Why the token is NOT in the URL (STEP 25 decision 3b):
  The Step Functions task token is a bearer secret — anyone holding it can
  resume the execution. Putting it in an email link would leak it via API
  Gateway access logs, browser history, and email forwarding. Instead the URL
  carries an opaque `approval_id` + an HMAC signature + an expiry; the real
  token lives server-side in DynamoDB. Even a leaked link is single-use,
  expires, and is unforgeable without the HMAC secret.

Wiring (env vars set by the Lambda Terraform module — see dev/main.tf):
    APPROVALS_TABLE        DynamoDB table mapping approval_id → task token
    HMAC_PARAM_NAME        SSM SecureString parameter holding the signing key
    SES_SENDER_EMAIL       verified SES sender identity
    ALERT_EMAIL            approval-email recipient (the operator)
    APPROVAL_TTL_SECONDS   link + DynamoDB-item lifetime (default 86400 = 24h)
    ENVIRONMENT, LOG_LEVEL

`apiBaseUrl` is passed in the Step Functions payload (NOT an env var) so the
Lambda has no build-time dependency on the API Gateway URL — that breaks the
otherwise-circular Terraform dependency (the API integrates this Lambda, and
this Lambda needs the API URL).
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_ssm = boto3.client("ssm")
_sfn = boto3.client("stepfunctions")
_ses = boto3.client("ses")
_ec2 = boto3.client("ec2")
_dynamodb = boto3.resource("dynamodb")

# Module-scope cache for the HMAC signing key — one SSM read per execution
# environment, not per invocation. Tests set this directly to skip SSM.
_hmac_secret: str | None = None

DEFAULT_TTL_SECONDS = 24 * 3600
VALID_ACTIONS = ("approve", "reject", "ignore")

# STEP 25 follow-up: the "Ignore" button stamps this tag so the cleanup
# detector (zombie_finder._is_ignored) permanently skips the resource. Must
# match zombie_finder's IGNORE_TAG_KEY / an opt-out value.
IGNORE_TAG_KEY = "AutoCleanup"
IGNORE_TAG_VALUE = "ignore"


# ---------------------------------------------------------------------------
# Signing helpers
# ---------------------------------------------------------------------------
def _get_hmac_secret() -> str:
    """Fetch + cache the HMAC signing key from SSM Parameter Store."""
    global _hmac_secret
    if _hmac_secret is None:
        resp = _ssm.get_parameter(
            Name=os.environ["HMAC_PARAM_NAME"], WithDecryption=True
        )
        _hmac_secret = resp["Parameter"]["Value"]
    return _hmac_secret


def _sign(approval_id: str, action: str, exp: int) -> str:
    """HMAC-SHA256 over the (id, action, expiry) tuple.

    `action` is part of the signed payload so an Approve signature can't be
    replayed against the Reject route (and vice versa).
    """
    msg = f"{approval_id}:{action}:{exp}".encode()
    return hmac.new(_get_hmac_secret().encode(), msg, hashlib.sha256).hexdigest()


def _build_link(api_base_url: str, approval_id: str, action: str, exp: int) -> str:
    qs = urlencode({"id": approval_id, "exp": exp, "sig": _sign(approval_id, action, exp)})
    return f"{api_base_url.rstrip('/')}/{action}?{qs}"


# ---------------------------------------------------------------------------
# NOTIFY path — pause the workflow, email the operator
# ---------------------------------------------------------------------------
def _handle_notify(event) -> dict:
    task_token = event["taskToken"]
    resources = event.get("resources", []) or []
    api_base_url = event["apiBaseUrl"]
    execution_name = event.get("executionName", "unknown")
    environment = os.environ.get("ENVIRONMENT", "dev")

    table = _dynamodb.Table(os.environ["APPROVALS_TABLE"])
    ttl_seconds = int(os.environ.get("APPROVAL_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))

    approval_id = uuid.uuid4().hex
    now = int(time.time())
    exp = now + ttl_seconds

    # Persist the token BEFORE emailing so the link is resolvable the instant
    # it is clickable. Orphaned rows (if the email later fails) self-expire via
    # the TTL attribute.
    table.put_item(
        Item={
            "approval_id": approval_id,
            "task_token": task_token,
            "status": "PENDING",
            "expires_at": exp,  # DynamoDB TTL attribute (epoch seconds)
            "created_at": datetime.now(timezone.utc).isoformat(),
            "execution_name": execution_name,
            "resource_count": len(resources),
            # Slim resource list so the "Ignore" callback can tag exactly these
            # resources AutoCleanup=ignore without re-deriving them.
            "resources": [
                {"resource_id": r.get("resource_id"), "resource_type": r.get("resource_type")}
                for r in resources
                if r.get("resource_id")
            ],
            "environment": environment,
        }
    )

    approve_url = _build_link(api_base_url, approval_id, "approve", exp)
    reject_url = _build_link(api_base_url, approval_id, "reject", exp)
    ignore_url = _build_link(api_base_url, approval_id, "ignore", exp)

    _send_email(
        environment=environment,
        resources=resources,
        approve_url=approve_url,
        reject_url=reject_url,
        ignore_url=ignore_url,
        ttl_seconds=ttl_seconds,
    )

    logger.info(
        "Approval requested: id=%s execution=%s resources=%d",
        approval_id,
        execution_name,
        len(resources),
    )
    # Return is ignored by Step Functions (the task waits on the token), but a
    # useful record in CloudWatch / direct-invoke tests.
    return {"approval_id": approval_id, "resource_count": len(resources), "expires_at": exp}


def _send_email(*, environment, resources, approve_url, reject_url, ignore_url, ttl_seconds) -> bool:
    sender = os.environ["SES_SENDER_EMAIL"]
    recipient = os.environ["ALERT_EMAIL"]

    total_cost = sum(float(r.get("monthly_cost_usd", 0) or 0) for r in resources)
    hours = ttl_seconds // 3600
    subject = (
        f"[CloudGuard {environment}] Approval required — "
        f"{len(resources)} resource(s), ~${total_cost:.2f}/mo"
    )

    rows = "".join(
        f"<tr>"
        f"<td style='padding:4px 8px;border:1px solid #ddd;font-family:monospace'>{html.escape(str(r.get('resource_id','')))}</td>"
        f"<td style='padding:4px 8px;border:1px solid #ddd'>{html.escape(str(r.get('resource_type','')))}</td>"
        f"<td style='padding:4px 8px;border:1px solid #ddd'>{html.escape(str(r.get('severity','')))}</td>"
        f"<td style='padding:4px 8px;border:1px solid #ddd;text-align:right'>${float(r.get('monthly_cost_usd',0) or 0):.2f}</td>"
        f"</tr>"
        for r in resources
    )

    body_html = (
        f"<div style='font-family:Arial,Helvetica,sans-serif;max-width:680px'>"
        f"<h2>CloudGuard remediation approval — {html.escape(environment)}</h2>"
        f"<p>The cleanup workflow detected <strong>{len(resources)}</strong> zombie "
        f"resource(s) (~<strong>${total_cost:.2f}/month</strong>) and is "
        f"<strong>paused</strong> awaiting your decision.</p>"
        f"<table style='border-collapse:collapse;margin:12px 0'>"
        f"<tr style='background:#f4f4f4'>"
        f"<th style='padding:4px 8px;border:1px solid #ddd;text-align:left'>Resource</th>"
        f"<th style='padding:4px 8px;border:1px solid #ddd;text-align:left'>Type</th>"
        f"<th style='padding:4px 8px;border:1px solid #ddd;text-align:left'>Severity</th>"
        f"<th style='padding:4px 8px;border:1px solid #ddd;text-align:right'>$/mo</th>"
        f"</tr>{rows}</table>"
        f"<p style='margin:20px 0'>"
        f"<a href='{html.escape(approve_url)}' "
        f"style='background:#1a7f37;color:#fff;padding:10px 22px;text-decoration:none;"
        f"border-radius:4px;margin-right:10px'>✓ Approve cleanup</a>"
        f"<a href='{html.escape(reject_url)}' "
        f"style='background:#b42318;color:#fff;padding:10px 22px;text-decoration:none;"
        f"border-radius:4px;margin-right:10px'>✗ Reject</a>"
        f"<a href='{html.escape(ignore_url)}' "
        f"style='background:#6b7280;color:#fff;padding:10px 22px;text-decoration:none;"
        f"border-radius:4px'>🚫 Ignore (keep forever)</a></p>"
        f"<p style='color:#666;font-size:13px'>"
        f"<strong>Approve</strong> deletes now · <strong>Reject</strong> skips "
        f"this run (you'll be asked again next scan) · <strong>Ignore</strong> "
        f"tags the resource(s) <code>{IGNORE_TAG_KEY}={IGNORE_TAG_VALUE}</code> "
        f"so CloudGuard never flags them again.<br>"
        f"Links are single-use and expire in {hours} hour(s). Do nothing and the "
        f"workflow times out with NO deletion (fail-safe). Deletion also still "
        f"requires the AUTO_REMEDIATE env gate and the AutoCleanup=true tag.</p>"
        f"</div>"
    )
    text_body = (
        f"CloudGuard {environment}: {len(resources)} zombie resource(s) "
        f"(~${total_cost:.2f}/mo) awaiting your decision.\n"
        f"Approve (delete now): {approve_url}\n"
        f"Reject (skip this run): {reject_url}\n"
        f"Ignore (keep forever): {ignore_url}\n"
        f"Links expire in {hours}h. No action = no deletion.\n"
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
        # If the operator never gets the link, the workflow times out and
        # nothing is deleted — so a send failure is safe. Raise so the failure
        # is visible in the execution history immediately rather than after the
        # 24h timeout.
        logger.exception("SES send_email failed (sender=%s recipient=%s): %s", sender, recipient, e)
        raise


# ---------------------------------------------------------------------------
# CALLBACK path — a human clicked Approve / Reject
# ---------------------------------------------------------------------------
def _handle_callback(event) -> dict:
    path = event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path", "")
    action = path.rstrip("/").rsplit("/", 1)[-1].lower()
    if action not in VALID_ACTIONS:
        return _http(404, "Not found", "Unknown action.")

    qs = event.get("queryStringParameters") or {}
    approval_id = qs.get("id")
    sig = qs.get("sig")
    exp_raw = qs.get("exp")
    if not (approval_id and sig and exp_raw):
        return _http(400, "Bad request", "Missing approval parameters.")

    try:
        exp = int(exp_raw)
    except (TypeError, ValueError):
        return _http(400, "Bad request", "Malformed expiry.")

    # Signature first (cheap, no I/O) — reject forgeries before touching the DB.
    expected = _sign(approval_id, action, exp)
    if not hmac.compare_digest(expected, sig):
        logger.warning("Invalid signature for approval_id=%s action=%s", approval_id, action)
        return _http(403, "Forbidden", "Invalid or tampered link.")

    if int(time.time()) > exp:
        return _http(410, "Link expired", "This approval link has expired. Re-run the workflow.")

    table = _dynamodb.Table(os.environ["APPROVALS_TABLE"])
    item = table.get_item(Key={"approval_id": approval_id}).get("Item")
    if not item:
        return _http(404, "Not found", "No such approval (it may have expired and been purged).")
    if item.get("status") != "PENDING":
        return _http(
            409, "Already decided",
            f"This request was already {str(item.get('status','')).lower()}.",
        )

    task_token = item["task_token"]

    # "Ignore" suppresses the resources for good (tag AutoCleanup=ignore) BEFORE
    # resolving the token — so even if the SFN side has already timed out, the
    # operator's keep-forever decision still lands.
    if action == "ignore":
        _tag_ignore(item.get("resources", []))

    try:
        if action == "approve":
            _sfn.send_task_success(
                taskToken=task_token,
                output=json.dumps({"approved": True, "approval_id": approval_id}),
            )
        elif action == "ignore":
            _sfn.send_task_failure(
                taskToken=task_token,
                error="RemediationIgnored",
                cause=f"Operator chose keep-forever; resources tagged {IGNORE_TAG_KEY}={IGNORE_TAG_VALUE} (approval_id={approval_id}).",
            )
        else:  # reject
            _sfn.send_task_failure(
                taskToken=task_token,
                error="RemediationRejected",
                cause=f"Operator rejected remediation (approval_id={approval_id}).",
            )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        # The task already resolved (timed out, or a duplicate click won the
        # race). Treat as terminal, not a 500. For ignore, the tag already
        # landed above — still a useful outcome.
        if code in ("TaskTimedOut", "TaskDoesNotExist"):
            _mark_decided(table, approval_id, "IGNORED" if action == "ignore" else "EXPIRED")
            extra = " The resource was still tagged to be ignored." if action == "ignore" else ""
            return _http(410, "Link expired", "The workflow already moved on (timeout or prior click)." + extra)
        logger.exception("SendTask call failed (action=%s): %s", action, e)
        return _http(500, "Error", "Failed to signal the workflow. Try again shortly.")

    new_status = {"approve": "APPROVED", "reject": "REJECTED", "ignore": "IGNORED"}[action]
    _mark_decided(table, approval_id, new_status)
    logger.info("Decision %s: id=%s", new_status, approval_id)

    if action == "approve":
        return _http(200, "Approved", "Cleanup approved — the workflow will delete the listed resources.")
    if action == "ignore":
        return _http(
            200, "Ignored",
            f"Tagged {IGNORE_TAG_KEY}={IGNORE_TAG_VALUE} — CloudGuard won't flag these resources again. Nothing was deleted.",
        )
    return _http(200, "Rejected", "Remediation rejected — nothing deleted. CloudGuard may flag these again on the next scan.")


def _tag_ignore(resources) -> None:
    """Stamp AutoCleanup=ignore on the resources so the cleanup detector
    (zombie_finder) permanently skips them. Best-effort: a tagging failure is
    logged, not raised — the execution still resolves without deleting.
    """
    ids = [r.get("resource_id") for r in (resources or []) if r.get("resource_id")]
    if not ids:
        return
    try:
        _ec2.create_tags(Resources=ids, Tags=[{"Key": IGNORE_TAG_KEY, "Value": IGNORE_TAG_VALUE}])
        logger.info("Tagged %s with %s=%s (operator chose Ignore)", ids, IGNORE_TAG_KEY, IGNORE_TAG_VALUE)
    except ClientError as e:
        logger.exception("create_tags failed for %s: %s", ids, e)


def _mark_decided(table, approval_id: str, status: str) -> None:
    """Single-use guard: flip PENDING → terminal status. Best-effort."""
    try:
        table.update_item(
            Key={"approval_id": approval_id},
            UpdateExpression="SET #s = :s, decided_at = :d",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": status,
                ":d": datetime.now(timezone.utc).isoformat(),
            },
        )
    except ClientError as e:  # noqa: BLE001
        logger.exception("Failed to mark approval %s as %s: %s", approval_id, status, e)


def _http(status_code: int, title: str, message: str) -> dict:
    """Minimal HTML response for the HTTP API (payload format 2.0)."""
    color = "#1a7f37" if status_code == 200 and title == "Approved" else (
        "#b42318" if status_code >= 400 or title == "Rejected" else "#1a1a1a"
    )
    body = (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>CloudGuard — {html.escape(title)}</title></head>"
        f"<body style='font-family:Arial,Helvetica,sans-serif;text-align:center;padding:60px'>"
        f"<h1 style='color:{color}'>{html.escape(title)}</h1>"
        f"<p style='font-size:16px;color:#333'>{html.escape(message)}</p>"
        f"<p style='color:#999;font-size:13px'>You can close this tab.</p>"
        f"</body></html>"
    )
    return {
        "statusCode": status_code,
        "headers": {"content-type": "text/html; charset=utf-8"},
        "body": body,
    }


# ---------------------------------------------------------------------------
# Entrypoint — dispatch on event shape
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    event = event or {}
    # Step Functions waitForTaskToken payload carries the token.
    if isinstance(event, dict) and "taskToken" in event:
        return _handle_notify(event)
    # API Gateway HTTP API (payload v2) carries requestContext / rawPath.
    if isinstance(event, dict) and ("rawPath" in event or "requestContext" in event):
        return _handle_callback(event)
    logger.error("Unrecognised event shape: keys=%s", list(event) if isinstance(event, dict) else type(event))
    raise ValueError("remediation_approval invoked with an unrecognised event shape")
