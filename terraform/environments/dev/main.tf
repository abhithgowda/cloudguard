# =============================================================================
# main.tf — Dev environment entry point
#
# Module calls are added progressively. Wired so far: iam (STEP 4).
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
# DynamoDB module — findings, cost-data, remediation-log tables (STEP 5)
# -----------------------------------------------------------------------------
module "dynamodb" {
  source      = "../../modules/dynamodb"
  environment = var.environment
  project     = var.project
}
