"""Unit tests for src/cost_scanner/cost_analyzer.py.

The handler.py is thin orchestration (env-var reads + 4 helper calls) and
makes a module-level `boto3.client("ce")` call at import time. Tests focus
on the pure helpers, which is where the anomaly detection logic lives.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

import cost_analyzer


# ---------------------------------------------------------------------------
# detect_anomalies — the core anomaly logic
# ---------------------------------------------------------------------------


class TestDetectAnomalies:
    def test_3x_spike_is_critical(self):
        # 29 days at $1, day 30 at $3 → ratio 3.0 → CRITICAL
        cost_data = {
            "Amazon EC2": {
                f"2026-05-{day:02d}": 1.0 for day in range(1, 30)
            },
        }
        cost_data["Amazon EC2"]["2026-05-30"] = 3.0

        anomalies = cost_analyzer.detect_anomalies(cost_data)

        assert len(anomalies) == 1
        a = anomalies[0]
        assert a["service"] == "Amazon EC2"
        assert a["date"] == "2026-05-30"
        assert a["actual_cost"] == 3.0
        assert a["ratio"] == 3.0
        # The severity classification lives in _severity_for; tested separately.

    def test_1_8x_spike_is_high(self):
        cost_data = {
            "Amazon RDS": {f"2026-05-{day:02d}": 1.0 for day in range(1, 30)},
        }
        cost_data["Amazon RDS"]["2026-05-30"] = 1.8

        anomalies = cost_analyzer.detect_anomalies(cost_data)

        assert len(anomalies) == 1
        assert anomalies[0]["ratio"] == 1.8

    def test_below_threshold_is_not_an_anomaly(self):
        # 1.4x is below the 1.5 default threshold.
        cost_data = {
            "Amazon EC2": {f"2026-05-{day:02d}": 1.0 for day in range(1, 30)},
        }
        cost_data["Amazon EC2"]["2026-05-30"] = 1.4

        anomalies = cost_analyzer.detect_anomalies(cost_data)

        assert anomalies == []

    def test_skips_service_with_fewer_than_two_days(self):
        # A brand-new service has no baseline — flagging would false-positive
        # on every first scan after the service is enabled.
        cost_data = {"AWS Glue": {"2026-05-30": 100.0}}

        anomalies = cost_analyzer.detect_anomalies(cost_data)

        assert anomalies == []

    def test_skips_service_with_zero_baseline(self):
        # avg_cost == 0 → div-by-zero AND "$0 → $5" is a turn-on event,
        # not an anomaly.
        cost_data = {
            "AWS WAF": {f"2026-05-{day:02d}": 0.0 for day in range(1, 30)},
        }
        cost_data["AWS WAF"]["2026-05-30"] = 5.0

        anomalies = cost_analyzer.detect_anomalies(cost_data)

        assert anomalies == []

    def test_baseline_excludes_latest_day(self):
        # The latest day's value MUST NOT pollute its own baseline.
        # 29 days at $0, day 30 at $10. If latest were included, baseline
        # = 10/30 = 0.33, ratio = 30; excluded → baseline = 0, ratio undefined
        # (skip). Either way, the spike-day must not be its own baseline.
        cost_data = {
            "AWS Lambda": {f"2026-05-{day:02d}": 0.0 for day in range(1, 30)},
        }
        cost_data["AWS Lambda"]["2026-05-30"] = 10.0

        anomalies = cost_analyzer.detect_anomalies(cost_data)

        # Baseline is 0 (29 prior days), so the service is skipped by the
        # avg_cost <= 0 guard — confirming the exclusion path.
        assert anomalies == []

    def test_detect_anomalies_skips_microscopic_costs(self):
        # STEP 20 Bug #2: a personal account with $0.00001 baseline S3 spend
        # and a $0.0009 spike-day was flagged HIGH at ratio=90x. The absolute
        # dollar value is operationally noise. Floor at $1 (default) suppresses.
        cost_data = {
            "Amazon S3": {
                f"2026-05-{day:02d}": 0.00001 for day in range(1, 30)
            },
        }
        cost_data["Amazon S3"]["2026-05-30"] = 0.0009

        anomalies = cost_analyzer.detect_anomalies(cost_data)

        assert anomalies == []

    def test_custom_floor_allows_small_but_real_anomaly_through(self):
        # The floor is a knob, not a hard veto. Lowering it via the parameter
        # (env var MIN_ANOMALY_DOLLARS in production) lets small-but-real
        # anomalies surface — useful in lower-spend dev accounts.
        cost_data = {
            "Amazon S3": {f"2026-05-{d:02d}": 0.05 for d in range(1, 30)},
        }
        cost_data["Amazon S3"]["2026-05-30"] = 0.50  # 10x at $0.50

        # Default floor ($1.00) suppresses it.
        assert cost_analyzer.detect_anomalies(cost_data) == []

        # Custom $0.10 floor lets it through.
        anomalies = cost_analyzer.detect_anomalies(cost_data, min_dollars=0.10)
        assert len(anomalies) == 1
        assert anomalies[0]["service"] == "Amazon S3"

    def test_floor_zero_disables_the_filter(self):
        # min_dollars=0 must restore pre-fix behaviour for callers that
        # explicitly opt out (e.g. tests, or an env where every cent matters).
        cost_data = {
            "Amazon S3": {
                f"2026-05-{day:02d}": 0.00001 for day in range(1, 30)
            },
        }
        cost_data["Amazon S3"]["2026-05-30"] = 0.0009

        anomalies = cost_analyzer.detect_anomalies(cost_data, min_dollars=0)

        assert len(anomalies) == 1

    def test_multiple_services_independent(self):
        cost_data = {
            "Service-A": {f"2026-05-{d:02d}": 1.0 for d in range(1, 30)},
            "Service-B": {f"2026-05-{d:02d}": 1.0 for d in range(1, 30)},
        }
        cost_data["Service-A"]["2026-05-30"] = 5.0   # anomaly
        cost_data["Service-B"]["2026-05-30"] = 1.0   # baseline

        anomalies = cost_analyzer.detect_anomalies(cost_data)

        assert len(anomalies) == 1
        assert anomalies[0]["service"] == "Service-A"


class TestSeverityFor:
    @pytest.mark.parametrize(
        "ratio,expected",
        [
            (2.5, "CRITICAL"),
            (2.0, "CRITICAL"),
            (1.99, "HIGH"),
            (1.5, "HIGH"),
            (1.49, "MEDIUM"),
            (1.0, "MEDIUM"),
        ],
    )
    def test_severity_thresholds(self, ratio, expected):
        assert cost_analyzer._severity_for(ratio) == expected


# ---------------------------------------------------------------------------
# get_cost_data — Cost Explorer pagination
# ---------------------------------------------------------------------------


class TestGetCostData:
    def _ce_page(self, day_str, service_costs):
        """Build one ResultsByTime entry with Groups for given services."""
        return {
            "TimePeriod": {"Start": day_str, "End": day_str},
            "Groups": [
                {
                    "Keys": [service],
                    "Metrics": {"UnblendedCost": {"Amount": str(amount)}},
                }
                for service, amount in service_costs.items()
            ],
        }

    def test_parses_single_page_response(self):
        ce = MagicMock()
        ce.get_cost_and_usage.return_value = {
            "ResultsByTime": [
                self._ce_page("2026-05-29", {"Amazon EC2": 1.0, "Amazon S3": 0.5}),
                self._ce_page("2026-05-30", {"Amazon EC2": 1.5}),
            ],
        }

        data = cost_analyzer.get_cost_data(
            ce, date(2026, 4, 30), date(2026, 5, 30)
        )

        assert data["Amazon EC2"]["2026-05-29"] == 1.0
        assert data["Amazon EC2"]["2026-05-30"] == 1.5
        assert data["Amazon S3"]["2026-05-29"] == 0.5

    def test_paginates_via_next_page_token(self):
        # Cost Explorer uses `NextPageToken` (not `NextToken`) — that's why
        # shared.aws_helpers.paginate refuses this API and it's hand-rolled.
        ce = MagicMock()
        ce.get_cost_and_usage.side_effect = [
            {
                "ResultsByTime": [self._ce_page("2026-05-29", {"Amazon EC2": 1.0})],
                "NextPageToken": "page2",
            },
            {
                "ResultsByTime": [self._ce_page("2026-05-30", {"Amazon EC2": 2.0})],
            },
        ]

        data = cost_analyzer.get_cost_data(
            ce, date(2026, 4, 30), date(2026, 5, 30)
        )

        assert ce.get_cost_and_usage.call_count == 2
        # Second call carries the token.
        second_kwargs = ce.get_cost_and_usage.call_args_list[1].kwargs
        assert second_kwargs["NextPageToken"] == "page2"
        # Both pages merged.
        assert data["Amazon EC2"]["2026-05-29"] == 1.0
        assert data["Amazon EC2"]["2026-05-30"] == 2.0


# ---------------------------------------------------------------------------
# store_cost_data / store_findings — DynamoDB writes
# ---------------------------------------------------------------------------


class TestStoreCostData:
    def test_pivots_to_one_row_per_day_per_service(self):
        # cost_data table stays append-only (PK=date, SK=service is naturally
        # idempotent — same date+service overwrites the same row).
        with patch.object(cost_analyzer, "batch_put_findings") as mock_batch:
            mock_batch.return_value = 3
            result = cost_analyzer.store_cost_data(
                "cloudguard-dev-cost-data",
                {
                    "Amazon EC2": {"2026-05-29": 1.0, "2026-05-30": 1.5},
                    "Amazon S3": {"2026-05-30": 0.5},
                },
            )

        assert result == 3
        table_name, items = mock_batch.call_args.args
        assert table_name == "cloudguard-dev-cost-data"
        assert len(items) == 3
        # Each row has PK=date, SK=service_name, plus unblended_cost.
        sample = items[0]
        assert {"date", "service_name", "unblended_cost"} <= set(sample.keys())


class TestStoreFindings:
    def test_writes_finding_with_critical_severity_for_ratio_2(self):
        anomalies = [
            {
                "service": "Amazon EC2",
                "date": "2026-05-30",
                "expected_cost": 1.0,
                "actual_cost": 3.0,
                "ratio": 3.0,
                "percentage_increase": 200.0,
            }
        ]

        with patch.object(cost_analyzer, "batch_upsert_findings") as mock_batch:
            mock_batch.return_value = 1
            cost_analyzer.store_findings("cloudguard-dev-findings", anomalies)

        items = mock_batch.call_args.args[1]
        assert len(items) == 1
        f = items[0]
        assert f["severity"] == "CRITICAL"
        assert f["category"] == "cost"
        assert f["resource_id"] == "Amazon EC2"
        assert f["check_name"] == "cost_anomaly_30d_baseline"
        # STEP 21.5: finding_id is now a deterministic 32-char hex hash of
        # (category, resource_id, check_name) — same anomaly → same ID
        # → upsert path bumps last_seen instead of inserting a duplicate.
        assert isinstance(f["finding_id"], str) and len(f["finding_id"]) == 32
        assert all(c in "0123456789abcdef" for c in f["finding_id"])
        # expires_at is a +90d epoch second integer.
        assert isinstance(f["expires_at"], int)

    def test_finding_id_is_deterministic_across_runs(self):
        anomaly = {
            "service": "Amazon EC2", "date": "2026-05-30",
            "expected_cost": 1.0, "actual_cost": 3.0,
            "ratio": 3.0, "percentage_increase": 200.0,
        }
        with patch.object(cost_analyzer, "batch_upsert_findings") as mock_batch:
            mock_batch.return_value = {"inserted": 1, "updated": 0, "total": 1}
            cost_analyzer.store_findings("t", [anomaly])
            fid_1 = mock_batch.call_args.args[1][0]["finding_id"]
            cost_analyzer.store_findings("t", [anomaly])
            fid_2 = mock_batch.call_args.args[1][0]["finding_id"]
        assert fid_1 == fid_2

    def test_high_severity_for_ratio_1_5(self):
        anomalies = [{
            "service": "Amazon S3", "date": "2026-05-30",
            "expected_cost": 1.0, "actual_cost": 1.5,
            "ratio": 1.5, "percentage_increase": 50.0,
        }]
        with patch.object(cost_analyzer, "batch_upsert_findings") as mock_batch:
            mock_batch.return_value = {"inserted": 1, "updated": 0, "total": 1}
            cost_analyzer.store_findings("t", anomalies)

        items = mock_batch.call_args.args[1]
        assert items[0]["severity"] == "HIGH"

    def test_empty_anomalies_still_called_with_empty_list(self):
        with patch.object(cost_analyzer, "batch_upsert_findings") as mock_batch:
            mock_batch.return_value = {"inserted": 0, "updated": 0, "total": 0}
            cost_analyzer.store_findings("t", [])
        # batch_upsert_findings handles the empty-list no-op internally.
        assert mock_batch.call_args.args[1] == []
