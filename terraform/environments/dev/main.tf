# =============================================================================
# main.tf — Dev environment entry point
#
# Module calls are added progressively. Wired so far: iam, kms, dynamodb, s3, sns.
# =============================================================================

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# -----------------------------------------------------------------------------
# Cross-module name conventions
#
# The S3 bucket name is the single source of truth that BOTH the IAM module
# (which builds the bucket ARN for s3:PutObject) and the S3 module (which
# actually creates the bucket) must agree on. Constructing it once in a local
# here — instead of letting each module reconstruct it — eliminates the
# possibility of drift.
#
# Suffix is required because S3 bucket names are globally unique across every
# AWS account in existence; the suffix lives in the gitignored tfvars.
# -----------------------------------------------------------------------------
locals {
  reports_bucket_name = "${var.project}-${var.environment}-reports-${var.bucket_suffix}"
  reports_bucket_arn  = "arn:aws:s3:::${local.reports_bucket_name}"

  # SES sender defaults to the alert recipient — one verified identity covers
  # both ends in sandbox SES. Override via tfvars only if the From: address
  # needs to differ from the To: address.
  ses_sender_email = var.ses_sender_email != "" ? var.ses_sender_email : var.alert_email
}

# -----------------------------------------------------------------------------
# IAM module — one role per Lambda, least-privilege inline policies (STEP 4,
# retrofitted in STEP 7 to consume the reports bucket ARN instead of building
# it from a hardcoded naming convention).
# -----------------------------------------------------------------------------
module "iam" {
  source             = "../../modules/iam"
  environment        = var.environment
  project            = var.project
  reports_bucket_arn = local.reports_bucket_arn
}

# -----------------------------------------------------------------------------
# KMS module — single shared CMK for DynamoDB, S3, SNS envelope encryption.
# Created in STEP 6 (inserted after IAM so we can pass the 4 role ARNs into
# the key policy and lock each grant down with kms:ViaService).
# -----------------------------------------------------------------------------
module "kms" {
  source      = "../../modules/kms"
  environment = var.environment
  project     = var.project
  lambda_role_arns = [
    module.iam.cost_scanner_role_arn,
    module.iam.security_scanner_role_arn,
    module.iam.resource_cleanup_role_arn,
    module.iam.report_generator_role_arn,
  ]
  # STEP 21 hotfix: github_plan + github_deploy need Lambda-scoped CMK access
  # to refresh-decrypt and apply-encrypt env vars. Without this, CI plan shows
  # phantom env-var drift and deploy apply fails AccessDenied on Encrypt.
  github_actions_role_arns = [
    module.github_oidc.plan_role_arn,
    module.github_oidc.deploy_role_arn,
  ]
}

# -----------------------------------------------------------------------------
# DynamoDB module — findings, cost-data, remediation-log tables (STEP 5,
# retrofitted in STEP 6 to consume module.kms.key_arn instead of the
# AWS-managed aws/dynamodb key).
# -----------------------------------------------------------------------------
module "dynamodb" {
  source      = "../../modules/dynamodb"
  environment = var.environment
  project     = var.project
  kms_key_arn = module.kms.key_arn
}

# -----------------------------------------------------------------------------
# S3 module — reports bucket + access-logs bucket (STEP 7).
#
# The reports bucket is encrypted with the shared CMK (module.kms.key_arn),
# its bucket policy grants write access to the 4 Lambda execution roles, and
# all public access is blocked. See the module's main.tf for details.
# -----------------------------------------------------------------------------
module "s3" {
  source              = "../../modules/s3"
  environment         = var.environment
  project             = var.project
  reports_bucket_name = local.reports_bucket_name
  kms_key_arn         = module.kms.key_arn
  lambda_role_arns = [
    module.iam.cost_scanner_role_arn,
    module.iam.security_scanner_role_arn,
    module.iam.resource_cleanup_role_arn,
    module.iam.report_generator_role_arn,
  ]
}

# -----------------------------------------------------------------------------
# SNS module — single fan-out alerts topic, KMS-encrypted with the shared CMK
# (STEP 8). The IAM module already grants the 4 Lambda roles sns:Publish on
# `${project}-${env}-alerts` — this module's topic name matches that ARN.
#
# alert_email is declared in variables.tf (since STEP 3) and set in the
# gitignored terraform.tfvars. AWS sends a confirmation email on apply; the
# subscription stays pending until the recipient clicks the link.
# -----------------------------------------------------------------------------
module "sns" {
  source      = "../../modules/sns"
  environment = var.environment
  project     = var.project
  kms_key_arn = module.kms.key_arn
  alert_email = var.alert_email
  lambda_role_arns = [
    module.iam.cost_scanner_role_arn,
    module.iam.security_scanner_role_arn,
    module.iam.resource_cleanup_role_arn,
    module.iam.report_generator_role_arn,
  ]
}

# -----------------------------------------------------------------------------
# Lambda modules (STEP 9)
#
# Four invocations of the reusable lambda module — one per scanner. Each gets:
#   - its own IAM role (least-privilege from iam module)
#   - env vars wired to the DynamoDB tables and SNS topic it actually uses
#   - CMK-encrypted env vars + CMK-encrypted log group (STEP 9 KMS retrofit)
#   - reserved_concurrent_executions = 5 (default) to cap runaway-bill risk
#   - X-Ray active tracing (default) for per-Lambda timeline in Step Functions
#
# source_dir paths point at src/<lambda>/build/ — populated by
# scripts/package_lambdas.sh (or .ps1) per STEP 19. The build/ directory
# contains the Lambda's own .py files PLUS a copy of src/shared/, so the
# runtime import `from shared.dynamo_client import ...` resolves.
# archive_file re-hashes build/ on every plan, so a code change auto-flows
# through to a new source_code_hash AFTER the packaging script has run.
# -----------------------------------------------------------------------------
module "cost_scanner" {
  source        = "../../modules/lambda"
  project       = var.project
  environment   = var.environment
  function_name = "${var.project}-${var.environment}-cost-scanner"
  role_arn      = module.iam.cost_scanner_role_arn
  source_dir    = "${path.root}/../../../src/cost_scanner/build"
  kms_key_arn   = module.kms.key_arn

  environment_variables = {
    FINDINGS_TABLE  = module.dynamodb.findings_table_name
    COST_DATA_TABLE = module.dynamodb.cost_data_table_name
    SNS_TOPIC_ARN   = module.sns.topic_arn
    ENVIRONMENT     = var.environment
    LOG_LEVEL       = "INFO"
    # Absolute-dollar floor on the latest day's cost. Without it, microscopic
    # spend (e.g. $0.00001 → $0.0009 = 90x ratio) gets flagged HIGH — the
    # false-positive that surfaced on the first live run (STEP 20 Bug #2).
    MIN_ANOMALY_DOLLARS = "1.0"
  }
}

module "security_scanner" {
  source        = "../../modules/lambda"
  project       = var.project
  environment   = var.environment
  function_name = "${var.project}-${var.environment}-security-scanner"
  role_arn      = module.iam.security_scanner_role_arn
  source_dir    = "${path.root}/../../../src/security_scanner/build"
  kms_key_arn   = module.kms.key_arn

  environment_variables = {
    FINDINGS_TABLE = module.dynamodb.findings_table_name
    SNS_TOPIC_ARN  = module.sns.topic_arn
    ENVIRONMENT    = var.environment
    LOG_LEVEL      = "INFO"
  }
}

module "resource_cleanup" {
  source        = "../../modules/lambda"
  project       = var.project
  environment   = var.environment
  function_name = "${var.project}-${var.environment}-resource-cleanup"
  role_arn      = module.iam.resource_cleanup_role_arn
  source_dir    = "${path.root}/../../../src/resource_cleanup/build"
  kms_key_arn   = module.kms.key_arn

  environment_variables = {
    FINDINGS_TABLE        = module.dynamodb.findings_table_name
    REMEDIATION_LOG_TABLE = module.dynamodb.remediation_log_table_name
    SNS_TOPIC_ARN         = module.sns.topic_arn
    ENVIRONMENT           = var.environment
    LOG_LEVEL             = "INFO"
    # Dry-run by default — actual deletes only happen when the Step Functions
    # input or EventBridge target overrides this. Safety rail for the
    # destructive permissions in the resource_cleanup role.
    AUTO_REMEDIATE = "false"
  }
}

module "report_generator" {
  source        = "../../modules/lambda"
  project       = var.project
  environment   = var.environment
  function_name = "${var.project}-${var.environment}-report-generator"
  role_arn      = module.iam.report_generator_role_arn
  source_dir    = "${path.root}/../../../src/report_generator/build"
  kms_key_arn   = module.kms.key_arn

  # Report generator runs once at the end of the workflow — give it more
  # memory (CPU is proportional) and time so HTML generation + S3 upload
  # complete inside a single invocation.
  memory_size = 512
  timeout     = 600

  environment_variables = {
    FINDINGS_TABLE        = module.dynamodb.findings_table_name
    COST_DATA_TABLE       = module.dynamodb.cost_data_table_name
    REMEDIATION_LOG_TABLE = module.dynamodb.remediation_log_table_name
    REPORTS_BUCKET        = module.s3.reports_bucket_name
    SNS_TOPIC_ARN         = module.sns.topic_arn
    # SES sender + recipient. In dev these are typically the same address
    # (one verification covers both ends); override `ses_sender_email` in
    # tfvars only if they need to differ.
    SES_SENDER_EMAIL    = local.ses_sender_email
    ALERT_EMAIL         = var.alert_email
    REPORT_WINDOW_HOURS = tostring(var.report_window_hours)
    ENVIRONMENT         = var.environment
    LOG_LEVEL           = "INFO"
  }
}

# -----------------------------------------------------------------------------
# Step Functions module (STEP 16, revised in STEP 17.5)
#
# Orchestrates the 3 scanner Lambdas: cost/security/cleanup run in parallel.
# Each scanner branch has Retry (MaxAttempts=2, BackoffRate=2.0) + Catch → Pass
# so a single scanner failure does NOT abort the workflow.
#
# STEP 17.5 revision: GenerateReport state was removed from the SFN. The
# 6-hourly scan_schedule was producing content-identical 24h-window reports
# to the daily EventBridge report rule (both use the same window). Reports
# now arrive only on the daily + weekly EventBridge schedules — the SFN
# writes findings to DynamoDB silently. See PROGRESS.md STEP 17.5.
#
# The KMS retrofit in STEP 16 widened the AllowCloudWatchLogsEncrypt Sid
# to cover the SFN log group ARN pattern (/aws/vendedlogs/states/...).
# -----------------------------------------------------------------------------
module "step_functions" {
  source      = "../../modules/step-functions"
  project     = var.project
  environment = var.environment
  kms_key_arn = module.kms.key_arn

  cost_scanner_arn     = module.cost_scanner.function_arn
  security_scanner_arn = module.security_scanner.function_arn
  resource_cleanup_arn = module.resource_cleanup.function_arn
}

# -----------------------------------------------------------------------------
# EventBridge module (STEP 17)
#
# Three scheduled rules drive the workflow:
#   - scan_schedule  → state machine, every 6 h, Input = {auto_remediate: false}
#   - daily_report   → report_generator Lambda, 08:00 IST daily,  window 24 h
#   - weekly_report  → report_generator Lambda, 08:00 IST Mondays, window 168 h
#
# auto_remediate stays false here: this is gate #2 from STEP 12's two-gate
# design. The Lambda's AUTO_REMEDIATE env var is also false (above), so even
# if this were flipped, the cleanup Lambda would still refuse. Real
# remediation requires BOTH gates set, and an operator manually starting
# the workflow from the console with auto_remediate=true. True async approval
# (per-resource Approve/Reject links via .waitForTaskToken) is STEP 25.
# -----------------------------------------------------------------------------
module "eventbridge" {
  source      = "../../modules/eventbridge"
  project     = var.project
  environment = var.environment

  state_machine_arn  = module.step_functions.state_machine_arn
  report_lambda_arn  = module.report_generator.function_arn
  report_lambda_name = module.report_generator.function_name

  # Scheduled scans are dry-run by default. See module docs for details.
  auto_remediate = false
}

# -----------------------------------------------------------------------------
# GitHub Actions OIDC module (STEP 21)
#
# Replaces long-lived AWS_ACCESS_KEY_ID/SECRET_ACCESS_KEY in GitHub repo
# secrets with branch-scoped, short-lived (~1h) credentials minted via OIDC
# federation. CI assumes the plan role; deploy.yml assumes the deploy role,
# which is locked to the `main` branch via the trust policy's `sub` condition.
#
# Account-global gotcha: aws_iam_openid_connect_provider is unique per AWS
# account. If a future prod environment lives in the SAME account, this
# resource must move to a shared bootstrap state (or be looked up via `data`)
# to avoid a "provider already exists" error on prod apply. Separate accounts
# per environment (the recommended pattern) sidesteps the issue.
# -----------------------------------------------------------------------------
module "github_oidc" {
  source             = "../../modules/github_oidc"
  project            = var.project
  environment        = var.environment
  github_org         = var.github_org
  github_repo        = var.github_repo
  state_bucket_name  = var.state_bucket_name
  deploy_environment = "dev"  # MUST match deploy.yml's `environment:` value
  deploy_branch      = "main" # Belt-and-braces: ref claim must also be main
}
