"""Generic boto3 helpers shared across all CloudGuard Lambdas.

- ``paginate`` standardises pagination across boto3 APIs that support
  ``get_paginator()``.
- ``get_account_id`` caches a one-time STS ``GetCallerIdentity`` lookup at
  module scope so warm Lambda invocations skip the API call.
- ``get_all_regions`` enumerates the account's opted-in regions for the
  future multi-region scanning use case.

Each Lambda's deployment zip bundles its own copy of this module (see
``scripts/package_lambdas.sh`` in STEP 19). There is no shared runtime
across Lambdas — module-level caches are per-execution-environment.
"""

import logging

import boto3

logger = logging.getLogger(__name__)

_ACCOUNT_ID_CACHE = None


def paginate(client, method_name, result_key, **kwargs):
    """Yield items from a paginated boto3 API call, one at a time.

    Args:
        client: boto3 client (e.g. ``boto3.client('ec2')``).
        method_name: method to paginate, e.g. ``'describe_volumes'``.
        result_key: response key holding the list, e.g. ``'Volumes'``.
        **kwargs: forwarded to ``paginator.paginate()`` (Filters, MaxResults, ...).

    Raises:
        ValueError: if the API does not support ``get_paginator()`` —
            e.g. Cost Explorer's ``NextPageToken`` API, which must be
            hand-rolled (see ``src/cost_scanner/cost_analyzer.py``).
    """
    if not client.can_paginate(method_name):
        raise ValueError(
            f"{client.meta.service_model.service_name}.{method_name} "
            "does not support get_paginator(); page manually with NextToken."
        )

    paginator = client.get_paginator(method_name)
    for page in paginator.paginate(**kwargs):
        for item in page.get(result_key, []):
            yield item


def get_account_id(sts_client=None):
    """Return the current AWS account ID via STS ``GetCallerIdentity``.

    Cached at module scope — account ID is invariant for the lifetime of a
    Lambda execution environment. Pass a custom ``sts_client`` to inject a
    mock in tests.
    """
    global _ACCOUNT_ID_CACHE
    if _ACCOUNT_ID_CACHE is not None:
        return _ACCOUNT_ID_CACHE

    client = sts_client or boto3.client("sts")
    _ACCOUNT_ID_CACHE = client.get_caller_identity()["Account"]
    return _ACCOUNT_ID_CACHE


def get_all_regions(ec2_client=None):
    """Return the list of opted-in EC2 region names for this account.

    ``AllRegions=False`` returns only regions the account has opted into —
    standard regions are opted-in by default; opt-in regions (e.g.
    ``me-central-1``, ``ap-south-2``) require explicit enablement.
    """
    client = ec2_client or boto3.client("ec2")
    response = client.describe_regions(AllRegions=False)
    return [r["RegionName"] for r in response.get("Regions", [])]
