"""CloudGuard Cost Scanner — Lambda entrypoint.

Reads 30 days of daily cost data per AWS service from Cost Explorer,
detects anomalies (today > 1.5x the prior 29-day average), writes raw
cost data to `cloudguard-<env>-cost-data` and anomalies as findings to
`cloudguard-<env>-findings`.

Wiring: env vars FINDINGS_TABLE, COST_DATA_TABLE, ENVIRONMENT are
injected by the lambda Terraform module (terraform/environments/dev/main.tf).
"""

import json
import logging
import os
from datetime import date, timedelta

import boto3

from cost_analyzer import (
    detect_anomalies,
    get_cost_data,
    store_cost_data,
    store_findings,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ce = boto3.client("ce")


def lambda_handler(event, context):
    findings_table_name = os.environ["FINDINGS_TABLE"]
    cost_data_table_name = os.environ["COST_DATA_TABLE"]
    min_anomaly_dollars = float(os.environ.get("MIN_ANOMALY_DOLLARS", "1.0"))

    end_date = date.today()
    start_date = end_date - timedelta(days=30)

    logger.info("Fetching cost data %s to %s", start_date, end_date)
    cost_data = get_cost_data(ce, start_date, end_date)

    store_cost_data(cost_data_table_name, cost_data)

    anomalies = detect_anomalies(
        cost_data, threshold=1.5, min_dollars=min_anomaly_dollars
    )
    logger.info(
        "Detected %d anomalies (min_dollars=%s)",
        len(anomalies),
        min_anomaly_dollars,
    )

    if anomalies:
        store_findings(findings_table_name, anomalies)

    total_daily_cost = sum(
        day_costs.get(end_date.isoformat(), 0.0)
        for day_costs in cost_data.values()
    )

    summary = {
        "anomalies_found": len(anomalies),
        "total_daily_cost": round(total_daily_cost, 4),
        "services_scanned": len(cost_data),
    }
    logger.info("Summary: %s", json.dumps(summary))
    return summary