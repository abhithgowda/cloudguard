"""Pure helpers for the cost scanner.

Split from handler.py so STEP 15 unit tests can mock the boto3 clients
and call these directly without invoking the Lambda runtime.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from shared.dynamo_client import batch_put_findings

logger = logging.getLogger(__name__)

FINDING_TTL_DAYS = 90
SEVERITY_CRITICAL_RATIO = 2.0
SEVERITY_HIGH_RATIO = 1.5
MIN_ANOMALY_DOLLARS_DEFAULT = 1.0


def get_cost_data(ce_client, start_date, end_date):
    """Page through Cost Explorer GetCostAndUsage, return nested dict.

    Returns: { service_name: { "YYYY-MM-DD": float_cost, ... }, ... }
    """
    results = {}
    next_token = None

    while True:
        kwargs = {
            "TimePeriod": {
                "Start": start_date.isoformat(),
                "End": end_date.isoformat(),
            },
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
        }
        if next_token:
            kwargs["NextPageToken"] = next_token

        response = ce_client.get_cost_and_usage(**kwargs)

        for day in response.get("ResultsByTime", []):
            day_start = day["TimePeriod"]["Start"]
            for group in day.get("Groups", []):
                service = group["Keys"][0]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                results.setdefault(service, {})[day_start] = amount

        next_token = response.get("NextPageToken")
        if not next_token:
            break

    return results


def detect_anomalies(
    cost_data,
    threshold=SEVERITY_HIGH_RATIO,
    min_dollars=MIN_ANOMALY_DOLLARS_DEFAULT,
):
    """Compare each service's most recent day vs the average of prior days.

    Skip services with zero historical cost (avoids div-by-zero and the
    false-positive of a service that legitimately just turned on).

    ``min_dollars`` is an absolute-dollar floor on the latest day's cost. A
    90x ratio on $0.0009 is mathematically a spike but operationally noise —
    surfaced in STEP 20's first live run on a personal account with
    microscopic S3 spend. Set to 0 to disable.
    """
    anomalies = []

    for service, day_costs in cost_data.items():
        if len(day_costs) < 2:
            continue

        sorted_days = sorted(day_costs.keys())
        latest_day = sorted_days[-1]
        prior_days = sorted_days[:-1]

        latest_cost = day_costs[latest_day]
        prior_costs = [day_costs[d] for d in prior_days]
        avg_cost = sum(prior_costs) / len(prior_costs)

        if avg_cost <= 0:
            continue

        if latest_cost < min_dollars:
            continue

        ratio = latest_cost / avg_cost
        if ratio < threshold:
            continue

        anomalies.append(
            {
                "service": service,
                "date": latest_day,
                "expected_cost": round(avg_cost, 4),
                "actual_cost": round(latest_cost, 4),
                "ratio": round(ratio, 3),
                "percentage_increase": round((ratio - 1.0) * 100, 1),
            }
        )

    return anomalies


def _severity_for(ratio):
    if ratio >= SEVERITY_CRITICAL_RATIO:
        return "CRITICAL"
    if ratio >= SEVERITY_HIGH_RATIO:
        return "HIGH"
    return "MEDIUM"


def store_cost_data(table_name, cost_data):
    """Batch-write the raw cost grid to cloudguard-<env>-cost-data.

    PK = date, SK = service_name. Re-running the same day overwrites
    (latest data wins) — correct for end-of-day cost re-evaluation.

    Float→Decimal coercion is handled recursively by ``batch_put_findings``
    via ``shared.dynamo_client._coerce_decimals``.
    """
    rows = [
        {"date": day_str, "service_name": service, "unblended_cost": amount}
        for service, day_costs in cost_data.items()
        for day_str, amount in day_costs.items()
    ]
    return batch_put_findings(table_name, rows)


def store_findings(table_name, anomalies):
    """Batch-write anomalies to cloudguard-<env>-findings with 90-day TTL.

    Stamps finding_id / timestamp / expires_at here (same shared timestamp
    for the whole batch is intentional — a single scanner run is one logical
    write event). Float coercion is delegated to ``batch_put_findings``.
    """
    now = datetime.now(timezone.utc)
    expires_at = int((now + timedelta(days=FINDING_TTL_DAYS)).timestamp())
    timestamp_iso = now.isoformat()

    items = []
    for anomaly in anomalies:
        severity = _severity_for(anomaly["ratio"])
        description = (
            f"{anomaly['service']} cost on {anomaly['date']} was "
            f"${anomaly['actual_cost']}, {anomaly['percentage_increase']}% "
            f"above the prior-period average of ${anomaly['expected_cost']}."
        )
        items.append({
            "finding_id": str(uuid.uuid4()),
            "timestamp": timestamp_iso,
            "category": "cost",
            "severity": severity,
            "resource_id": anomaly["service"],
            "resource_type": "aws_service",
            "check_name": "cost_anomaly_30d_baseline",
            "description": description,
            "expected_cost": anomaly["expected_cost"],
            "actual_cost": anomaly["actual_cost"],
            "ratio": anomaly["ratio"],
            "expires_at": expires_at,
        })

    return batch_put_findings(table_name, items)