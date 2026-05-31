"""Unit tests for src/shared/ — the helpers wired into the Lambdas in STEP 15a.

Three modules under test:
  - shared.aws_helpers     paginate, get_account_id, get_all_regions
  - shared.dynamo_client   batch_put_findings, put_finding, queries, _coerce_decimals
  - shared.notification    send_sns_alert, send_slack_webhook

Every public function takes a boto3 client/resource as an optional parameter
(`sts_client=None`, `dynamodb_resource=None`, `sns_client=None`). Tests pass
`unittest.mock.Mock()` and assert on call_args — no AWS, no moto, no network.
"""

from __future__ import annotations

import json
import urllib.error
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from shared import aws_helpers
from shared import dynamo_client
from shared import notification


# ---------------------------------------------------------------------------
# shared.aws_helpers
# ---------------------------------------------------------------------------


class TestPaginate:
    def test_yields_items_across_pages(self):
        client = MagicMock()
        client.can_paginate.return_value = True
        paginator = MagicMock()
        paginator.paginate.return_value = iter([
            {"Volumes": [{"VolumeId": "vol-1"}, {"VolumeId": "vol-2"}]},
            {"Volumes": [{"VolumeId": "vol-3"}]},
        ])
        client.get_paginator.return_value = paginator

        items = list(aws_helpers.paginate(client, "describe_volumes", "Volumes"))

        assert [i["VolumeId"] for i in items] == ["vol-1", "vol-2", "vol-3"]
        client.get_paginator.assert_called_once_with("describe_volumes")

    def test_forwards_kwargs_to_paginator(self):
        client = MagicMock()
        client.can_paginate.return_value = True
        paginator = MagicMock()
        paginator.paginate.return_value = iter([{"Volumes": []}])
        client.get_paginator.return_value = paginator

        list(aws_helpers.paginate(
            client, "describe_volumes", "Volumes",
            Filters=[{"Name": "status", "Values": ["available"]}],
        ))

        paginator.paginate.assert_called_once_with(
            Filters=[{"Name": "status", "Values": ["available"]}]
        )

    def test_raises_when_api_not_paginatable(self):
        client = MagicMock()
        client.can_paginate.return_value = False
        client.meta.service_model.service_name = "ce"

        with pytest.raises(ValueError, match="does not support get_paginator"):
            list(aws_helpers.paginate(client, "get_cost_and_usage", "ResultsByTime"))


class TestGetAccountId:
    def test_returns_account_id_from_sts(self):
        sts = MagicMock()
        sts.get_caller_identity.return_value = {"Account": "123456789012"}

        result = aws_helpers.get_account_id(sts_client=sts)

        assert result == "123456789012"
        sts.get_caller_identity.assert_called_once()

    def test_caches_result_across_calls(self):
        sts = MagicMock()
        sts.get_caller_identity.return_value = {"Account": "999"}

        first = aws_helpers.get_account_id(sts_client=sts)
        # Second call passes a fresh mock that would error if invoked.
        second_sts = MagicMock()
        second_sts.get_caller_identity.side_effect = AssertionError("should not be called")
        second = aws_helpers.get_account_id(sts_client=second_sts)

        assert first == second == "999"
        sts.get_caller_identity.assert_called_once()


class TestGetAllRegions:
    def test_returns_region_names(self):
        ec2 = MagicMock()
        ec2.describe_regions.return_value = {
            "Regions": [
                {"RegionName": "ap-south-1"},
                {"RegionName": "us-east-1"},
            ]
        }

        regions = aws_helpers.get_all_regions(ec2_client=ec2)

        assert regions == ["ap-south-1", "us-east-1"]
        ec2.describe_regions.assert_called_once_with(AllRegions=False)


# ---------------------------------------------------------------------------
# shared.dynamo_client
# ---------------------------------------------------------------------------


class TestCoerceDecimals:
    def test_float_to_decimal_via_str(self):
        result = dynamo_client._coerce_decimals(1.5)
        assert result == Decimal("1.5")
        # str() conversion — should NOT have the binary-float artefacts.
        assert str(result) == "1.5"

    def test_nested_dict_walked_recursively(self):
        result = dynamo_client._coerce_decimals({
            "metadata": {"monthly_cost_usd": 85.2, "size_gb": 600},
            "ratio": 2.5,
        })
        assert result["metadata"]["monthly_cost_usd"] == Decimal("85.2")
        assert result["ratio"] == Decimal("2.5")
        # Ints stay ints — DynamoDB accepts them.
        assert result["metadata"]["size_gb"] == 600
        assert isinstance(result["metadata"]["size_gb"], int)

    def test_nested_list_walked_recursively(self):
        result = dynamo_client._coerce_decimals([1.5, {"x": 2.5}, [3.5]])
        assert result == [Decimal("1.5"), {"x": Decimal("2.5")}, [Decimal("3.5")]]

    def test_strings_untouched(self):
        assert dynamo_client._coerce_decimals("hello") == "hello"

    def test_decimal_passthrough(self):
        d = Decimal("1.5")
        assert dynamo_client._coerce_decimals(d) is d


class TestPutFinding:
    def test_put_item_with_coerced_values(self):
        table = MagicMock()
        resource = MagicMock()
        resource.Table.return_value = table

        dynamo_client.put_finding(
            "cloudguard-dev-findings",
            {"finding_id": "abc", "ratio": 1.5},
            dynamodb_resource=resource,
        )

        resource.Table.assert_called_once_with("cloudguard-dev-findings")
        args, kwargs = table.put_item.call_args
        assert kwargs["Item"]["finding_id"] == "abc"
        assert kwargs["Item"]["ratio"] == Decimal("1.5")


class TestBatchPutFindings:
    def test_empty_list_noops_no_client_call(self):
        resource = MagicMock()
        result = dynamo_client.batch_put_findings(
            "t", [], dynamodb_resource=resource
        )
        assert result == 0
        resource.Table.assert_not_called()

    def test_items_written_via_batch_writer(self):
        table = MagicMock()
        batch_writer = MagicMock()
        # batch_writer() is a context manager
        table.batch_writer.return_value.__enter__.return_value = batch_writer
        resource = MagicMock()
        resource.Table.return_value = table

        items = [
            {"finding_id": "1", "ratio": 1.5},
            {"finding_id": "2", "metadata": {"monthly_cost_usd": 85.2}},
        ]
        written = dynamo_client.batch_put_findings(
            "cloudguard-dev-findings", items, dynamodb_resource=resource
        )

        assert written == 2
        assert batch_writer.put_item.call_count == 2

        # First call: ratio float coerced to Decimal.
        first_item = batch_writer.put_item.call_args_list[0].kwargs["Item"]
        assert first_item["ratio"] == Decimal("1.5")

        # Second call: nested float coerced too — this is the latent bug
        # STEP 15a fixed in resource_cleanup/handler.py.
        second_item = batch_writer.put_item.call_args_list[1].kwargs["Item"]
        assert second_item["metadata"]["monthly_cost_usd"] == Decimal("85.2")


class TestComputeFindingId:
    def test_deterministic_across_calls(self):
        a = dynamo_client.compute_finding_id("security", "sg-1", "sg_open_22")
        b = dynamo_client.compute_finding_id("security", "sg-1", "sg_open_22")
        assert a == b

    def test_different_inputs_different_ids(self):
        a = dynamo_client.compute_finding_id("security", "sg-1", "sg_open_22")
        b = dynamo_client.compute_finding_id("security", "sg-2", "sg_open_22")
        c = dynamo_client.compute_finding_id("security", "sg-1", "sg_open_3389")
        d = dynamo_client.compute_finding_id("cost", "sg-1", "sg_open_22")
        assert len({a, b, c, d}) == 4

    def test_32_char_hex(self):
        fid = dynamo_client.compute_finding_id("security", "sg-1", "x")
        assert len(fid) == 32
        assert all(ch in "0123456789abcdef" for ch in fid)

    def test_delimiter_avoids_concat_ambiguity(self):
        # Without the delimiter, ("foo", "bar", "baz") would collide with
        # ("foo", "barbaz", ""). The pipe character breaks that.
        a = dynamo_client.compute_finding_id("foo", "bar", "baz")
        b = dynamo_client.compute_finding_id("foo", "barbaz", "")
        assert a != b


class TestUpsertFinding:
    def _setup(self, query_items=None):
        table = MagicMock()
        table.query.return_value = {"Items": query_items or []}
        resource = MagicMock()
        resource.Table.return_value = table
        return resource, table

    def _finding(self, **overrides):
        base = {
            "finding_id": "abc123",
            "timestamp": "2026-05-31T00:00:00+00:00",
            "category": "security",
            "severity": "HIGH",
            "resource_id": "sg-1",
            "check_name": "sg_open_22",
            "description": "open SSH",
            "expires_at": 1700000000,
        }
        base.update(overrides)
        return base

    def test_first_sight_does_put_item(self):
        resource, table = self._setup(query_items=[])
        result = dynamo_client.upsert_finding(
            "t", self._finding(), dynamodb_resource=resource
        )
        assert result == "inserted"
        table.put_item.assert_called_once()
        table.update_item.assert_not_called()
        item = table.put_item.call_args.kwargs["Item"]
        assert item["first_seen"] == "2026-05-31T00:00:00+00:00"
        assert item["last_seen"] == "2026-05-31T00:00:00+00:00"
        assert item["occurrence_count"] == 1

    def test_re_sight_does_update_item_preserving_sk(self):
        existing = {
            "finding_id": "abc123",
            "timestamp": "2026-05-29T10:00:00+00:00",  # first_seen SK
            "occurrence_count": 3,
        }
        resource, table = self._setup(query_items=[existing])
        result = dynamo_client.upsert_finding(
            "t",
            self._finding(timestamp="2026-05-31T00:00:00+00:00"),
            dynamodb_resource=resource,
        )
        assert result == "updated"
        table.put_item.assert_not_called()
        table.update_item.assert_called_once()
        kwargs = table.update_item.call_args.kwargs
        # SK on the Update is the EXISTING first_seen, not the new scan time.
        assert kwargs["Key"]["timestamp"] == "2026-05-29T10:00:00+00:00"
        # occurrence_count was incremented from 3 to 4.
        assert kwargs["ExpressionAttributeValues"][":oc"] == 4
        # last_seen is the new scan time.
        assert kwargs["ExpressionAttributeValues"][":ls"] == "2026-05-31T00:00:00+00:00"

    def test_re_sight_with_no_prior_count_defaults_to_2(self):
        # An old uuid-keyed row pre STEP 21.5 has no occurrence_count field
        # — defaults to 1, increments to 2 on re-sight.
        existing = {
            "finding_id": "abc123",
            "timestamp": "2026-05-29T10:00:00+00:00",
        }
        resource, table = self._setup(query_items=[existing])
        dynamo_client.upsert_finding(
            "t", self._finding(), dynamodb_resource=resource
        )
        assert table.update_item.call_args.kwargs["ExpressionAttributeValues"][":oc"] == 2


class TestBatchUpsertFindings:
    def test_empty_returns_zero_counts_no_calls(self):
        resource = MagicMock()
        result = dynamo_client.batch_upsert_findings(
            "t", [], dynamodb_resource=resource
        )
        assert result == {"inserted": 0, "updated": 0, "total": 0}
        resource.Table.assert_not_called()

    def test_mixed_insert_and_update_counts(self):
        table = MagicMock()
        # First finding: query returns empty → insert path.
        # Second finding: query returns existing → update path.
        table.query.side_effect = [
            {"Items": []},
            {"Items": [{"finding_id": "f2", "timestamp": "earlier"}]},
        ]
        resource = MagicMock()
        resource.Table.return_value = table

        result = dynamo_client.batch_upsert_findings(
            "t",
            [
                {"finding_id": "f1", "timestamp": "t1", "severity": "HIGH",
                 "expires_at": 1, "description": "d1"},
                {"finding_id": "f2", "timestamp": "t2", "severity": "LOW",
                 "expires_at": 2, "description": "d2"},
            ],
            dynamodb_resource=resource,
        )
        assert result == {"inserted": 1, "updated": 1, "total": 2}


class TestQueryFindingsByDate:
    def test_scan_with_filter_expression(self):
        table = MagicMock()
        table.scan.return_value = {
            "Items": [{"finding_id": "1"}, {"finding_id": "2"}],
        }
        resource = MagicMock()
        resource.Table.return_value = table

        items = dynamo_client.query_findings_by_date(
            "cloudguard-dev-findings",
            "2026-05-24T00:00:00+00:00",
            "2026-05-25T00:00:00+00:00",
            dynamodb_resource=resource,
        )

        assert len(items) == 2
        kwargs = table.scan.call_args.kwargs
        assert kwargs["FilterExpression"] == "#ts BETWEEN :start AND :end"
        # Reserved-word safety — "timestamp" needs the alias.
        assert kwargs["ExpressionAttributeNames"] == {"#ts": "timestamp"}
        assert kwargs["ExpressionAttributeValues"] == {
            ":start": "2026-05-24T00:00:00+00:00",
            ":end": "2026-05-25T00:00:00+00:00",
        }

    def test_paginates_via_last_evaluated_key(self):
        table = MagicMock()
        table.scan.side_effect = [
            {"Items": [{"finding_id": "1"}], "LastEvaluatedKey": {"k": "1"}},
            {"Items": [{"finding_id": "2"}]},
        ]
        resource = MagicMock()
        resource.Table.return_value = table

        items = dynamo_client.query_findings_by_date(
            "t", "s", "e", dynamodb_resource=resource
        )

        assert [i["finding_id"] for i in items] == ["1", "2"]
        assert table.scan.call_count == 2
        # Second scan call carries the ExclusiveStartKey.
        assert table.scan.call_args_list[1].kwargs["ExclusiveStartKey"] == {"k": "1"}


class TestQueryFindingsBySeverity:
    def test_queries_severity_index_gsi(self):
        table = MagicMock()
        table.query.return_value = {
            "Items": [{"finding_id": "1", "severity": "CRITICAL"}],
        }
        resource = MagicMock()
        resource.Table.return_value = table

        items = dynamo_client.query_findings_by_severity(
            "cloudguard-dev-findings", "CRITICAL", dynamodb_resource=resource
        )

        assert len(items) == 1
        kwargs = table.query.call_args.kwargs
        assert kwargs["IndexName"] == "severity-index"
        # KeyConditionExpression is a boto3 Condition object — just check it exists.
        assert "KeyConditionExpression" in kwargs


# ---------------------------------------------------------------------------
# shared.notification
# ---------------------------------------------------------------------------


class TestSendSnsAlert:
    def test_publish_string_message(self):
        sns = MagicMock()
        sns.publish.return_value = {"MessageId": "abc-123"}

        result = notification.send_sns_alert(
            "arn:aws:sns:ap-south-1:123:cloudguard-alerts",
            "subject",
            "hello",
            sns_client=sns,
        )

        assert result == "abc-123"
        sns.publish.assert_called_once_with(
            TopicArn="arn:aws:sns:ap-south-1:123:cloudguard-alerts",
            Subject="subject",
            Message="hello",
        )

    def test_dict_message_json_encoded_with_decimal_handling(self):
        sns = MagicMock()
        sns.publish.return_value = {"MessageId": "x"}

        notification.send_sns_alert(
            "arn",
            "subject",
            {"ratio": Decimal("1.5"), "service": "EC2"},
            sns_client=sns,
        )

        body = sns.publish.call_args.kwargs["Message"]
        payload = json.loads(body)
        # default=str converts Decimal so json doesn't raise TypeError.
        assert payload["ratio"] == "1.5"
        assert payload["service"] == "EC2"

    def test_subject_truncated_to_100_chars(self):
        sns = MagicMock()
        sns.publish.return_value = {"MessageId": "x"}

        notification.send_sns_alert(
            "arn", "x" * 150, "msg", sns_client=sns,
        )

        assert len(sns.publish.call_args.kwargs["Subject"]) == 100


class TestSendSlackWebhook:
    def _mock_urlopen(self, status: int):
        """Build a context-manager-compatible mock for urllib.request.urlopen."""
        response = MagicMock()
        response.status = status
        ctx = MagicMock()
        ctx.__enter__.return_value = response
        ctx.__exit__.return_value = False
        return ctx

    def test_success_returns_true(self):
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(200)):
            result = notification.send_slack_webhook(
                "https://hooks.slack.com/services/x",
                {"text": "hello"},
            )
        assert result is True

    def test_non_2xx_returns_false(self):
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(503)):
            result = notification.send_slack_webhook(
                "https://hooks.slack.com/services/x",
                {"text": "hello"},
            )
        assert result is False

    def test_urlerror_returns_false_does_not_raise(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            result = notification.send_slack_webhook(
                "https://hooks.slack.com/services/x",
                {"text": "hello"},
            )
        assert result is False

    def test_generic_exception_returns_false_does_not_raise(self):
        # Slack must NEVER break the caller — bare Exception swallowed.
        with patch(
            "urllib.request.urlopen",
            side_effect=RuntimeError("unexpected"),
        ):
            result = notification.send_slack_webhook(
                "https://hooks.slack.com/services/x",
                {"text": "hello"},
            )
        assert result is False
