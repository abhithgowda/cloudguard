"""Pytest configuration — wires sys.path the way the Lambda runtime would.

In production the STEP 19 packaging script copies `src/<lambda>/*.py` and
`src/shared/` side-by-side into the Lambda zip root. Imports inside handlers
look like `from cost_analyzer import ...` (sibling) and `from shared.X import Y`
(sub-package). To mirror that here:

    sys.path[0] = src/                       → makes `from shared.X import Y` work
    sys.path[1..] = src/<each lambda>/        → makes sibling imports work

Each Lambda has its own `handler.py`, so importing them as plain `handler`
would collide across test files. `load_handler(name)` loads each `handler.py`
under a unique module name (`cost_scanner_handler`, etc.) and clears the
shared/* module caches between loads so module-scope boto3 client caches in
`shared.aws_helpers`, `shared.dynamo_client`, and `shared.notification`
don't leak state between tests.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

LAMBDA_DIRS = (
    "cost_scanner",
    "security_scanner",
    "resource_cleanup",
    "report_generator",
)

# Dummy AWS config so module-level boto3.client(...) calls in handlers don't
# raise NoRegionError when imported under a clean environment.
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
for d in LAMBDA_DIRS:
    p = str(SRC / d)
    if p not in sys.path:
        sys.path.append(p)


def load_handler(lambda_name: str):
    """Load `src/<lambda_name>/handler.py` as a uniquely-named module.

    Using `importlib.util.spec_from_file_location` with a custom module name
    avoids the 4 `handler.py` files clobbering each other in `sys.modules`.
    """
    module_name = f"{lambda_name}_handler"
    if module_name in sys.modules:
        del sys.modules[module_name]

    handler_path = SRC / lambda_name / "handler.py"
    spec = importlib.util.spec_from_file_location(module_name, handler_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _reset_shared_caches():
    """Clear module-scope client caches in shared/ before each test.

    Production callers benefit from these caches (one STS / DynamoDB / SNS
    client per execution environment). In tests we inject `Mock()`s instead;
    a previous test's cache would otherwise leak into the next one.
    """
    for mod_name in (
        "shared.aws_helpers",
        "shared.dynamo_client",
        "shared.notification",
    ):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        if hasattr(mod, "_ACCOUNT_ID_CACHE"):
            mod._ACCOUNT_ID_CACHE = None
        if hasattr(mod, "_DDB_RESOURCE"):
            mod._DDB_RESOURCE = None
        if hasattr(mod, "_SNS_CLIENT"):
            mod._SNS_CLIENT = None
    yield


@pytest.fixture
def handler_loader():
    """Expose `load_handler` to tests that need a specific Lambda's handler module."""
    return load_handler
