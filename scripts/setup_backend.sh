#!/bin/bash
# =============================================================================
# setup_backend.sh
# Creates the S3 bucket used to store Terraform remote state for CloudGuard.
#
# Run ONCE before the first `terraform init`.
# Safe to re-run — AWS CLI commands are idempotent (bucket/versioning already
# existing will not cause errors with the checks below).
#
# Usage:
#   bash scripts/setup_backend.sh
#
# Requirements:
#   - AWS CLI v2 configured with credentials (aws configure)
#   - Sufficient IAM permissions: s3:CreateBucket, s3:PutBucketVersioning,
#     s3:PutBucketEncryption, s3:PutBucketPublicAccessBlock
# =============================================================================

set -e  # Exit immediately on any error

BUCKET_NAME="cloudguard-tf-state-abhithcogni"
REGION="ap-south-1"

echo "========================================"
echo "CloudGuard — Terraform Backend Setup"
echo "Bucket : $BUCKET_NAME"
echo "Region : $REGION"
echo "========================================"

# -----------------------------------------------------------------------------
# Step 1: Create the S3 bucket
# ap-south-1 requires LocationConstraint (us-east-1 does not — AWS quirk)
# -----------------------------------------------------------------------------
echo ""
echo "[1/4] Creating S3 bucket..."
aws s3api create-bucket \
  --bucket "$BUCKET_NAME" \
  --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION"
echo "      Done."

# -----------------------------------------------------------------------------
# Step 2: Enable versioning
# Why: if Terraform corrupts state, you can roll back to a previous version.
# Without versioning, a bad apply could permanently destroy your state file.
# -----------------------------------------------------------------------------
echo ""
echo "[2/4] Enabling versioning..."
aws s3api put-bucket-versioning \
  --bucket "$BUCKET_NAME" \
  --versioning-configuration Status=Enabled
echo "      Done."

# -----------------------------------------------------------------------------
# Step 3: Enable server-side encryption (SSE-S3)
# Why: state files can contain resource IDs, ARNs, and occasionally secrets.
# Encryption at rest is non-negotiable for any production state bucket.
# SSE-S3 is free and automatic. SSE-KMS adds audit trail — overkill here.
# -----------------------------------------------------------------------------
echo ""
echo "[3/4] Enabling server-side encryption (SSE-S3)..."
aws s3api put-bucket-encryption \
  --bucket "$BUCKET_NAME" \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      },
      "BucketKeyEnabled": true
    }]
  }'
echo "      Done."

# -----------------------------------------------------------------------------
# Step 4: Block all public access
# Why: a state bucket must never be public — ever. This is a hard block at
# the bucket level, overriding any accidental permissive bucket policy.
# -----------------------------------------------------------------------------
echo ""
echo "[4/4] Blocking all public access..."
aws s3api put-public-access-block \
  --bucket "$BUCKET_NAME" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
echo "      Done."

echo ""
echo "========================================"
echo "Backend setup complete."
echo ""
echo "Next steps:"
echo "  1. cd terraform/environments/dev"
echo "  2. terraform init"
echo "========================================"
