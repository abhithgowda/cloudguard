"""One-shot purge of the cloudguard-<env>-findings table.

Why this exists
---------------
STEP 21.5 changed the finding write path from append (uuid finding_id +
scan-time timestamp SK) to idempotent upsert (deterministic finding_id hash
of category/resource_id/check_name, with first_seen as the immutable SK).

After deploy, EXISTING uuid-keyed rows can't be reached by the new code
path — the deterministic hashes won't match any of them. They'd live in
the table until the 90-day TTL expires them, and during that window the
report's backward-compat OR filter would surface them as duplicates next
to the new deterministic rows.

This script deletes every row in the findings table. The next scan
re-populates with one row per unique real-world issue. Cost data and
remediation log are NOT touched — they have different schemas and are
already correctly idempotent / append-only.

Usage
-----
Dry-run (default, prints what WOULD be deleted, no API calls):
    python scripts/cleanup_old_findings.py --table cloudguard-dev-findings

Actually delete (requires explicit flag):
    python scripts/cleanup_old_findings.py \\
        --table cloudguard-dev-findings --confirm

The script uses DynamoDB Scan + BatchWriteItem (DeleteRequest). At a few
hundred rows this is one Scan page and one batch. The IAM permission
required is dynamodb:Scan + dynamodb:BatchWriteItem (the local AWS profile
must already have these — admin in personal account, or the deploy role
ARN if run via CI).
"""
from __future__ import annotations

import argparse
import sys

import boto3


def scan_all_keys(table) -> list[dict]:
    """Return the full list of (finding_id, timestamp) key dicts."""
    keys: list[dict] = []
    kwargs: dict = {"ProjectionExpression": "finding_id, #ts",
                    "ExpressionAttributeNames": {"#ts": "timestamp"}}
    while True:
        resp = table.scan(**kwargs)
        for item in resp.get("Items", []):
            keys.append({"finding_id": item["finding_id"],
                         "timestamp": item["timestamp"]})
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return keys


def batch_delete(table, keys: list[dict]) -> int:
    """Delete N items via batch_writer (auto-batches 25/req, handles retries)."""
    if not keys:
        return 0
    with table.batch_writer() as batch:
        for k in keys:
            batch.delete_item(Key=k)
    return len(keys)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--table", required=True,
                   help="DynamoDB table name (e.g. cloudguard-dev-findings)")
    p.add_argument("--region", default="ap-south-1")
    p.add_argument("--confirm", action="store_true",
                   help="Actually delete (without this flag, dry-run only)")
    args = p.parse_args()

    ddb = boto3.resource("dynamodb", region_name=args.region)
    table = ddb.Table(args.table)

    print(f"Scanning {args.table} in {args.region}...")
    keys = scan_all_keys(table)
    print(f"Found {len(keys)} rows.")

    if not keys:
        print("Nothing to delete.")
        return 0

    sample = keys[:5]
    print("Sample keys to be deleted:")
    for k in sample:
        print(f"  finding_id={k['finding_id']!s:40s} timestamp={k['timestamp']}")
    if len(keys) > 5:
        print(f"  ... and {len(keys) - 5} more.")

    if not args.confirm:
        print("\nDRY-RUN — no items deleted. Re-run with --confirm to actually delete.")
        return 0

    print(f"\nDeleting {len(keys)} rows...")
    deleted = batch_delete(table, keys)
    print(f"Deleted {deleted} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
