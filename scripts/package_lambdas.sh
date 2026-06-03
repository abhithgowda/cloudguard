#!/bin/bash
# =============================================================================
# package_lambdas.sh — STEP 19
#
# Populates src/<lambda>/build/ for each Lambda with its own .py files plus a
# copy of src/shared/. Terraform's archive_file (in modules/lambda/main.tf)
# then zips build/ on the next plan and uploads via the AWS Lambda API.
#
# Why this script exists at all:
#   After STEP 15a, every Lambda imports from src/shared/. But archive_file
#   zips a single directory (source_dir), and src/shared/ is OUTSIDE
#   src/<lambda>/. Without this pre-copy step, the deployed Lambdas would
#   ImportError: No module named 'shared' on first invocation.
#
# Why no pip install:
#   Each Lambda's requirements.txt is `boto3` only, and boto3 ships in the
#   Python 3.12 Lambda runtime. Vendoring it would add ~15 MB to every zip
#   for zero functional gain — slower cold starts and we hit the 50 MB
#   zip / 250 MB unzipped Lambda quota faster. If a real third-party dep
#   ever gets added, insert `pip install --target build/ <pkg>` here.
#
# Run from anywhere (script resolves the repo root from its own location):
#   bash scripts/package_lambdas.sh
#
# CI uses this script (STEP 21 GitHub Actions on ubuntu-latest). The
# PowerShell sibling (package_lambdas.ps1) is for the local Windows loop.
# =============================================================================

set -euo pipefail

FUNCTIONS=("cost_scanner" "security_scanner" "resource_cleanup" "report_generator" "remediation_approval")

# Resolve repo root from this script's location so cwd doesn't matter.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SRC_ROOT="${REPO_ROOT}/src"
SHARED_DIR="${SRC_ROOT}/shared"

if [[ ! -d "${SHARED_DIR}" ]]; then
    echo "ERROR: ${SHARED_DIR} not found — STEP 14 must be complete." >&2
    exit 1
fi

for func in "${FUNCTIONS[@]}"; do
    SRC_DIR="${SRC_ROOT}/${func}"
    BUILD_DIR="${SRC_DIR}/build"

    if [[ ! -d "${SRC_DIR}" ]]; then
        echo "ERROR: ${SRC_DIR} not found." >&2
        exit 1
    fi

    echo "Packaging ${func}..."

    # Clean and recreate the build dir so stale files from a previous run
    # never sneak into the zip.
    rm -rf "${BUILD_DIR}"
    mkdir -p "${BUILD_DIR}"

    # Copy the Lambda's own .py files (handler + helpers). requirements.txt
    # is intentionally excluded — Lambda ignores it and we don't pip install.
    cp "${SRC_DIR}"/*.py "${BUILD_DIR}/"

    # Vendor the shared/ package. At runtime `shared/` sits next to handler.py
    # so `from shared.dynamo_client import ...` resolves.
    cp -r "${SHARED_DIR}" "${BUILD_DIR}/shared"

    # Strip __pycache__ directories. They're compiled by whichever local Python
    # version ran (3.13 in dev) and tagged with that version in the filename,
    # so the Lambda 3.12 runtime would ignore them anyway — dead weight.
    find "${BUILD_DIR}" -type d -name "__pycache__" -exec rm -rf {} +

    echo "  -> ${BUILD_DIR}/ populated ($(find "${BUILD_DIR}" -type f | wc -l) files)"
done

echo ""
echo "All Lambdas packaged. Next: terraform plan in terraform/environments/dev/"
echo "(archive_file re-hashes build/ — Terraform shows source_code_hash changes)."
