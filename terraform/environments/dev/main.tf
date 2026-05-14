# =============================================================================
# main.tf — Dev environment entry point
#
# Module calls are added progressively from STEP 4 onwards.
# For now this just configures the AWS provider.
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
