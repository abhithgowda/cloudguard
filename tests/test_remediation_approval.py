"""Unit tests for src/remediation_approval/ (STEP 25).

Covers the two dispatched paths:
  - NOTIFY:   persists the task token, signs links, emails the operator.
  - CALLBACK: verifies the HMAC signature / expiry / single-use, then calls
              states:SendTaskSuccess (approve) or SendTaskFailure (reject).

The HMAC secret is injected directly (module._hmac_secret) so tests never hit
SSM. boto3 clients on the module are replaced with Mocks.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from botocore.exceptions import ClientError


@pytest.fixture
def approval_env(monkeypatch):
    monkeypatch.setenv("APPROVALS_TABLE", "cloudguard-dev-approvals")
    monkeypatch.setenv("HMAC_PARAM_NAME", "/cloudguard/dev/remediation/hmac-secret")
    monkeypatch.setenv("SES_SENDER_EMAIL", "ops@example.com")
    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    monkeypatch.setenv("APPROVAL_TTL_SECONDS", "3600")
    monkeypatch.setenv("ENVIRONMENT", "dev")


@pytest.fixture
def mod(approval_env, handler_loader):
    """Load the approval handler with mocked clients and a known HMAC secret."""
    m = handler_loader("remediation_approval")
    m._hmac_secret = "test-signing-secret"
    m._sfn = MagicMock()
    m._ses = MagicMock()
    m._ssm = MagicMock()
    m._dynamodb = MagicMock()
    # table = m._dynamodb.Table(<name>) — the same MagicMock for assertions.
    m._table = m._dynamodb.Table.return_value
    return m


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------
class TestSigning:
    def test_signature_is_action_bound(self, mod):
        exp = int(time.time()) + 3600
        approve_sig = mod._sign("abc", "approve", exp)
        reject_sig = mod._sign("abc", "reject", exp)
        # Same id + expiry but different action ⇒ different signature, so an
        # approve link can't be replayed against the reject route.
        assert approve_sig != reject_sig

    def test_build_link_shape(self, mod):
        exp = int(time.time()) + 3600
        url = mod._build_link("https://api.example.com", "abc", "approve", exp)
        assert url.startswith("https://api.example.com/approve?")
        assert "id=abc" in url and "sig=" in url and f"exp={exp}" in url


# ---------------------------------------------------------------------------
# NOTIFY
# ---------------------------------------------------------------------------
class TestNotify:
    def _event(self):
        return {
            "taskToken": "task-token-xyz",
            "resources": [
                {"resource_id": "vol-1", "resource_type": "aws_ebs_volume",
                 "severity": "HIGH", "monthly_cost_usd": 85.2},
            ],
            "apiBaseUrl": "https://api.example.com",
            "executionName": "exec-1",
        }

    def test_persists_token_then_emails(self, mod):
        result = mod.lambda_handler(self._event(), None)

        # Token row written with PENDING status + TTL.
        item = mod._table.put_item.call_args.kwargs["Item"]
        assert item["task_token"] == "task-token-xyz"
        assert item["status"] == "PENDING"
        assert item["approval_id"] == result["approval_id"]
        assert item["expires_at"] == result["expires_at"]

        # Email sent once, containing both signed links with this approval_id.
        mod._ses.send_email.assert_called_once()
        html = mod._ses.send_email.call_args.kwargs["Message"]["Body"]["Html"]["Data"]
        assert f"id={result['approval_id']}" in html
        assert "/approve?" in html and "/reject?" in html

    def test_ses_failure_raises(self, mod):
        mod._ses.send_email.side_effect = ClientError(
            {"Error": {"Code": "MessageRejected", "Message": "unverified"}},
            "SendEmail",
        )
        # A send failure surfaces immediately (the workflow would otherwise
        # wait out the full timeout). No deletion can happen either way.
        with pytest.raises(ClientError):
            mod.lambda_handler(self._event(), None)


# ---------------------------------------------------------------------------
# CALLBACK
# ---------------------------------------------------------------------------
class TestCallback:
    def _signed_event(self, mod, action, *, ttl=3600, approval_id="abc"):
        exp = int(time.time()) + ttl
        sig = mod._sign(approval_id, action, exp)
        return {
            "rawPath": f"/{action}",
            "queryStringParameters": {"id": approval_id, "exp": str(exp), "sig": sig},
        }

    def _pending_item(self, approval_id="abc", token="task-token-xyz"):
        return {"Item": {"approval_id": approval_id, "task_token": token, "status": "PENDING"}}

    def test_approve_sends_task_success(self, mod):
        mod._table.get_item.return_value = self._pending_item()
        resp = mod.lambda_handler(self._signed_event(mod, "approve"), None)

        assert resp["statusCode"] == 200
        assert "Approved" in resp["body"]
        mod._sfn.send_task_success.assert_called_once()
        assert mod._sfn.send_task_success.call_args.kwargs["taskToken"] == "task-token-xyz"
        # Single-use: row flipped to APPROVED.
        assert mod._table.update_item.call_args.kwargs["ExpressionAttributeValues"][":s"] == "APPROVED"

    def test_reject_sends_task_failure(self, mod):
        mod._table.get_item.return_value = self._pending_item()
        resp = mod.lambda_handler(self._signed_event(mod, "reject"), None)

        assert resp["statusCode"] == 200
        assert "Rejected" in resp["body"]
        mod._sfn.send_task_failure.assert_called_once()
        assert mod._sfn.send_task_failure.call_args.kwargs["error"] == "RemediationRejected"
        mod._sfn.send_task_success.assert_not_called()

    def test_bad_signature_is_403_and_no_callback(self, mod):
        exp = int(time.time()) + 3600
        event = {
            "rawPath": "/approve",
            "queryStringParameters": {"id": "abc", "exp": str(exp), "sig": "deadbeef"},
        }
        resp = mod.lambda_handler(event, None)
        assert resp["statusCode"] == 403
        mod._sfn.send_task_success.assert_not_called()
        mod._table.get_item.assert_not_called()  # rejected before any DB I/O

    def test_expired_link_is_410(self, mod):
        resp = mod.lambda_handler(self._signed_event(mod, "approve", ttl=-10), None)
        assert resp["statusCode"] == 410
        mod._sfn.send_task_success.assert_not_called()

    def test_missing_params_is_400(self, mod):
        resp = mod.lambda_handler({"rawPath": "/approve", "queryStringParameters": {}}, None)
        assert resp["statusCode"] == 400

    def test_unknown_action_is_404(self, mod):
        resp = mod.lambda_handler(
            {"rawPath": "/bogus", "queryStringParameters": {"id": "a", "exp": "1", "sig": "x"}},
            None,
        )
        assert resp["statusCode"] == 404

    def test_already_decided_is_409(self, mod):
        mod._table.get_item.return_value = {
            "Item": {"approval_id": "abc", "task_token": "t", "status": "APPROVED"}
        }
        resp = mod.lambda_handler(self._signed_event(mod, "approve"), None)
        assert resp["statusCode"] == 409
        mod._sfn.send_task_success.assert_not_called()

    def test_unknown_approval_id_is_404(self, mod):
        mod._table.get_item.return_value = {}  # no Item
        resp = mod.lambda_handler(self._signed_event(mod, "approve"), None)
        assert resp["statusCode"] == 404

    def test_task_already_timed_out_is_410(self, mod):
        mod._table.get_item.return_value = self._pending_item()
        mod._sfn.send_task_success.side_effect = ClientError(
            {"Error": {"Code": "TaskTimedOut", "Message": "token expired"}},
            "SendTaskSuccess",
        )
        resp = mod.lambda_handler(self._signed_event(mod, "approve"), None)
        assert resp["statusCode"] == 410


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
class TestDispatch:
    def test_unrecognised_event_raises(self, mod):
        with pytest.raises(ValueError):
            mod.lambda_handler({"foo": "bar"}, None)
