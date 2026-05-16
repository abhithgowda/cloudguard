# =============================================================================
# main.tf — Dev environment entry point
#
# Module calls are added progressively. Wired so far: iam, dynamodb, kms.
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
