# =============================================================================
# backend.tf — Terraform Remote State Configuration (dev environment)
#
# State is stored in S3. Locking uses S3 native locking (Terraform >= 1.10).
# DynamoDB is NOT used — native S3 locking via use_lockfile = true is
# sufficient and removes a dependency.
#
# The S3 bucket must exist BEFORE running terraform init.
# Run scripts/setup_backend.sh first.
# =============================================================================

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    # STEP 25: random_password generates the remediation-approval HMAC signing
    # key (modules/remediation). archive is used implicitly by the lambda module
    # (archive_file) and was already in the lock file; declared here too so the
    # provider set is explicit for CI.
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  backend "s3" {
    bucket  = "cloudguard-tf-state-abhithcogni"
    key     = "dev/terraform.tfstate"
    region  = "ap-south-1"
    encrypt = true

    # Native S3 state locking (Terraform >= 1.10)
    # Creates a .tflock file in the bucket using S3 conditional writes.
    # Prevents concurrent terraform apply runs from corrupting state.
    use_lockfile = true
  }
}
