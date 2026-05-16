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
# IAM module — one role per Lambda, least-privilege inline policies (STEP 4)
# -----------------------------------------------------------------------------
module "iam" {
  source      = "../../modules/iam"
  environment = var.environment
  project     = var.project
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
