# =============================================================================
# package_lambdas.ps1 — STEP 19 (PowerShell sibling of package_lambdas.sh)
#
# Native-Windows equivalent of the bash script. Same contract:
#   * Populates src/<lambda>/build/ with the Lambda's .py files + src/shared/
#   * Terraform's archive_file zips build/ on the next plan
#   * AWS Lambda API uploads happen at terraform apply (UpdateFunctionCode)
#
# No pip install — boto3 ships in the Lambda Python 3.12 runtime. See the
# header comment in package_lambdas.sh for the full reasoning.
#
# Run from anywhere (script resolves the repo root from its own location):
#   .\scripts\package_lambdas.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

$Functions = @("cost_scanner", "security_scanner", "resource_cleanup", "report_generator")

# Resolve repo root from this script's location so cwd doesn't matter.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir "..")
$SrcRoot   = Join-Path $RepoRoot "src"
$SharedDir = Join-Path $SrcRoot "shared"

if (-not (Test-Path $SharedDir)) {
    Write-Error "ERROR: $SharedDir not found - STEP 14 must be complete."
    exit 1
}

foreach ($func in $Functions) {
    $SrcDir   = Join-Path $SrcRoot $func
    $BuildDir = Join-Path $SrcDir "build"

    if (-not (Test-Path $SrcDir)) {
        Write-Error "ERROR: $SrcDir not found."
        exit 1
    }

    Write-Host "Packaging $func..."

    # Clean and recreate build/ so stale files from a previous run never
    # sneak into the zip.
    if (Test-Path $BuildDir) {
        Remove-Item -Recurse -Force $BuildDir
    }
    New-Item -ItemType Directory -Path $BuildDir | Out-Null

    # Copy the Lambda's own .py files (handler + helpers). requirements.txt
    # is intentionally excluded — Lambda ignores it and we don't pip install.
    Get-ChildItem -Path $SrcDir -Filter "*.py" -File | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination $BuildDir
    }

    # Vendor the shared/ package. At runtime `shared/` sits next to
    # handler.py so `from shared.dynamo_client import ...` resolves.
    Copy-Item -Recurse -Path $SharedDir -Destination (Join-Path $BuildDir "shared")

    # Strip __pycache__ directories. They're compiled by the local Python
    # (3.13 here) and tagged with that version in the filename, so the Lambda
    # 3.12 runtime would ignore them anyway — dead weight in the zip.
    Get-ChildItem -Path $BuildDir -Recurse -Force -Directory -Filter "__pycache__" |
        Remove-Item -Recurse -Force

    $FileCount = (Get-ChildItem -Path $BuildDir -Recurse -File).Count
    Write-Host "  -> $BuildDir populated ($FileCount files)"
}

Write-Host ""
Write-Host "All Lambdas packaged. Next: terraform plan in terraform/environments/dev/"
Write-Host "(archive_file re-hashes build/ - Terraform shows source_code_hash changes)."
