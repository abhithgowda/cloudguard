"""DynamoDB helpers for finding writes and queries.

All writes coerce floats to ``Decimal`` at the boundary because DynamoDB
rejects native Python floats. Coercion uses ``Decimal(str(value))`` to
preserve the textual precision the caller intended; ``Decimal(0.1)`` would
produce ``Decimal('0.10000000000000000555...')``. This matches the
convention already used in ``src/cost_scanner/cost_analyzer.py``.

Two write paths:

* ``batch_put_findings`` — append-only, uses ``table.batch_writer()`` for
  25-item ``BatchWriteItem`` requests. Use for tables where each write is a
  discrete event (e.g. ``cloudguard-<env>-remediation-log``, ``cost-data``).

* ``upsert_finding`` / ``batch_upsert_findings`` — idempotent. The finding
  table's PK is ``finding_id``; using a deterministic ``compute_finding_id``
  hash means re-scanning the same real-world issue updates the same row
  (``last_seen``, ``occurrence_count``) instead of inserting duplicates.
  Modelled on AWS Security Hub's ``FirstObservedAt`` / ``LastObservedAt``.
  Trade-off: one ``Query`` + one ``Put``/``Update`` per finding instead of
  batched ``BatchWriteItem``. At dev volume (~50 findings / scan) this is a
  rounding error.

Each Lambda's deployment zip bundles its own copy of this module (see
``scripts/package_lambdas.sh`` in STEP 19).
"""

import hashlib
import logging
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

_DDB_RESOURCE = None


def _get_resource():
    """Module-scope cached DynamoDB resource — reused across warm invocations."""
    global _DDB_RESOURCE
    if _DDB_RESOURCE is None:
        _DDB_RESOURCE = boto3.resource("dynamodb")
    return _DDB_RESOURCE


def _coerce_decimals(item):
    """Recursively convert ``float`` to ``Decimal`` via ``str()``.

    DynamoDB rejects floats. ``str()`` preserves the textual precision the
    caller intended — ``Decimal(0.1)`` produces ugly binary-float artefacts.
    """
    if isinstance(item, float):
        return Decimal(str(item))
    if isinstance(item, dict):
        return {k: _coerce_decimals(v) for k, v in item.items()}
    if isinstance(item, list):
        return [_coerce_decimals(v) for v in item]
    return item


def compute_finding_id(category, resource_id, check_name):
    """Deterministic finding ID — same real-world issue maps to the same PK.

    SHA-256 of ``<category>|<resource_id>|<check_name>`` truncated to 32 hex
    chars (128 bits — collision-resistant for the small finding population
    CloudGuard generates, and short enough to read in DynamoDB console).

    The delimiter avoids ``foo|bar|baz`` vs ``foobar|baz`` ambiguity from
    naive concatenation. All three inputs are converted to ``str`` so a
    caller passing an int (e.g. a port number) doesn't break the hash.
    """
    key = f"{category}|{resource_id}|{check_name}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def upsert_finding(table_name, finding, dynamodb_resource=None):
    """Idempotent finding write — same ``finding_id`` updates the same row.

    Caller stamps ``finding_id`` (use ``compute_finding_id``), ``timestamp``
    (the current scan time, used as SK on first-sight only), and
    ``expires_at``. On re-sight the existing SK is preserved (it is the
    immutable ``first_seen`` value) and ``last_seen`` / ``occurrence_count``
    / ``expires_at`` are bumped.

    Implementation: ``Query`` by PK → if existing item found, ``UpdateItem``
    on the existing (PK, SK); otherwise ``PutItem`` with current timestamp
    as SK and ``first_seen = last_seen = now``, ``occurrence_count = 1``.

    Returns ``"inserted"`` or ``"updated"``.
    """
    resource = dynamodb_resource or _get_resource()
    table = resource.Table(table_name)

    finding_id = finding["finding_id"]
    now_iso = finding["timestamp"]
    expires_at = finding["expires_at"]

    existing = table.query(
        KeyConditionExpression=Key("finding_id").eq(finding_id),
        Limit=1,
    ).get("Items", [])

    if existing:
        existing_sk = existing[0]["timestamp"]
        prior_count = int(existing[0].get("occurrence_count", 1))
        table.update_item(
            Key={"finding_id": finding_id, "timestamp": existing_sk},
            UpdateExpression=(
                "SET last_seen = :ls, "
                "occurrence_count = :oc, "
                "expires_at = :ea, "
                "severity = :sv, "
                "description = :desc"
            ),
            ExpressionAttributeValues=_coerce_decimals({
                ":ls": now_iso,
                ":oc": prior_count + 1,
                ":ea": expires_at,
                ":sv": finding["severity"],
                ":desc": finding.get("description", ""),
            }),
        )
        return "updated"

    item = dict(finding)
    item.setdefault("first_seen", now_iso)
    item.setdefault("last_seen", now_iso)
    item.setdefault("occurrence_count", 1)
    table.put_item(Item=_coerce_decimals(item))
    return "inserted"


def batch_upsert_findings(table_name, findings, dynamodb_resource=None):
    """Upsert a batch of findings sequentially.

    Returns ``{"inserted": int, "updated": int, "total": int}``. Sequential
    rather than ``BatchWriteItem`` because the AWS batch API does not support
    conditional / read-then-write semantics — the per-item Query is required.
    No-op for an empty input list.
    """
    counts = {"inserted": 0, "updated": 0, "total": 0}
    if not findings:
        return counts

    for finding in findings:
        action = upsert_finding(table_name, finding, dynamodb_resource)
        counts[action] += 1
        counts["total"] += 1

    logger.info(
        "batch_upsert_findings: %d inserted, %d updated on %s",
        counts["inserted"],
        counts["updated"],
        table_name,
    )
    return counts


def put_finding(table_name, finding, dynamodb_resource=None):
    """Write a single finding to the findings table.

    The caller is responsible for stamping ``finding_id``, ``timestamp``,
    ``category``, ``severity``, and ``expires_at`` — see ``handler.py`` in
    any scanner for the canonical schema.
    """
    resource = dynamodb_resource or _get_resource()
    table = resource.Table(table_name)
    table.put_item(Item=_coerce_decimals(finding))


def batch_put_findings(table_name, findings, dynamodb_resource=None):
    """Batch-write findings using ``table.batch_writer()``.

    boto3's batch_writer handles:
      * splitting into 25-item ``BatchWriteItem`` requests (the AWS limit),
      * retrying ``UnprocessedItems`` with exponential backoff,
      * flushing on context exit.

    Returns the number of items written. No-op for an empty input list.
    """
    if not findings:
        return 0

    resource = dynamodb_resource or _get_resource()
    table = resource.Table(table_name)

    with table.batch_writer() as batch:
        for finding in findings:
            batch.put_item(Item=_coerce_decimals(finding))

    logger.info("batch_put_findings: wrote %d items to %s", len(findings), table_name)
    return len(findings)


def query_findings_by_date(table_name, start_date, end_date, dynamodb_resource=None):
    """Return findings whose ``timestamp`` falls within ``[start_date, end_date]``.

    LIMITATION (documented carry-over from STEP 13): the findings table's
    partition key is ``finding_id`` (uuid) and no GSI uses ``timestamp`` as a
    partition key, so this is a ``Scan`` with a ``FilterExpression`` — cost is
    O(table size). Acceptable at current dev volumes (tens to low hundreds of
    findings/day). Add a ``(environment, timestamp)`` GSI when volume justifies
    it; this function's signature stays the same and the implementation flips
    to ``Query``.

    Args:
        start_date / end_date: ISO-8601 strings, e.g.
            ``'2026-05-24T00:00:00+00:00'``. ISO-8601 sorts lexically, so
            string ``BETWEEN`` works correctly.

    Returns: list of items (paginated internally).
    """
    resource = dynamodb_resource or _get_resource()
    table = resource.Table(table_name)

    items = []
    scan_kwargs = {
        "FilterExpression": "#ts BETWEEN :start AND :end",
        "ExpressionAttributeNames": {"#ts": "timestamp"},
        "ExpressionAttributeValues": {":start": start_date, ":end": end_date},
    }

    while True:
        response = table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    logger.info(
        "query_findings_by_date: %d items in [%s, %s] (Scan+Filter on %s)",
        len(items),
        start_date,
        end_date,
        table_name,
    )
    return items


def query_findings_by_severity(table_name, severity, dynamodb_resource=None):
    """Query the ``severity-index`` GSI for all findings of a given severity.

    Real ``Query`` (not ``Scan``) — the GSI partition key is ``severity`` and
    sort key is ``timestamp`` (provisioned in STEP 5), so results return in
    chronological order by default. Paginated internally until exhausted.

    Args:
        severity: one of ``CRITICAL`` / ``HIGH`` / ``MEDIUM`` / ``LOW``.
    """
    resource = dynamodb_resource or _get_resource()
    table = resource.Table(table_name)

    items = []
    query_kwargs = {
        "IndexName": "severity-index",
        "KeyConditionExpression": Key("severity").eq(severity),
    }

    while True:
        response = table.query(**query_kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        query_kwargs["ExclusiveStartKey"] = last_key

    logger.info(
        "query_findings_by_severity: %d items at severity=%s on %s",
        len(items),
        severity,
        table_name,
    )
    return items
