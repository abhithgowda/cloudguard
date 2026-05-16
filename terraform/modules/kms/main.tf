# =============================================================================
# main.tf — KMS module (STEP 6)
#
# Single shared customer-managed KMS key (CMK) used for envelope encryption of:
#   - DynamoDB tables (STEP 5, retrofitted here)
#   - S3 reports bucket (STEP 7)
#   - SNS alerts topic (STEP 8)
#
# Why a CMK over the AWS-managed aliases (aws/dynamodb, aws/s3, aws/sns):
#   - We can write a key policy restricting WHO may Decrypt.
#   - Every Decrypt call is logged in CloudTrail under THIS key.
#   - We control rotation cadence (here: annual auto-rotation).
#   - We can revoke access by disabling the key without touching the table/bucket.
# AWS-managed keys give none of that — they're "encrypt-at-rest checkbox" only.
#
# Why a single shared CMK, not per-service:
#   - Cost: $1/month vs $3/month for three keys.
#   - Personal dev: blast-radius isolation between cost/security/cleanup data
#     isn't worth the extra spend. In a regulated prod setup, per-service CMKs
#     with tighter policies would be the right call.
# =============================================================================

# Account ID and region pulled from the active provider — used to (a) build the
# root principal ARN in the key policy and (b) construct the region-specific
# kms:ViaService values.
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  alias_name = "alias/${var.project}-${var.environment}"

  # kms:ViaService values are region-qualified service endpoints. Each grant
  # below is locked to the consuming service in THIS region.
  via_dynamodb = "dynamodb.${data.aws_region.current.id}.amazonaws.com"
  via_s3       = "s3.${data.aws_region.current.id}.amazonaws.com"
  via_sns      = "sns.${data.aws_region.current.id}.amazonaws.com"
}

# =============================================================================
# Key policy
#
# Three Lambda-grant statements (one per consuming service) instead of one
# combined statement with a list of kms:ViaService values. Verbose, but each
# statement reads as a single purpose — easier to audit and easier to revoke
# one service later without touching the others.
# =============================================================================
data "aws_iam_policy_document" "kms_key_policy" {
  # ---------------------------------------------------------------------------
  # Root-account admin. Without this statement, a misconfigured policy can
  # lock you out of the key permanently (Terraform can't fix a key it can't
  # touch). AWS-recommended for every CMK.
  # ---------------------------------------------------------------------------
  statement {
    sid    = "EnableRootAccountAdmin"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    actions   = ["kms:*"]
    resources = ["*"]
  }

  # ---------------------------------------------------------------------------
  # Lambdas → DynamoDB via this key.
  # ---------------------------------------------------------------------------
  statement {
    sid    = "AllowLambdasViaDynamoDB"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = var.lambda_role_arns
    }

    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.via_dynamodb]
    }
  }

  # ---------------------------------------------------------------------------
  # Lambdas → S3 via this key (reports bucket reads/writes, STEP 7).
  # ---------------------------------------------------------------------------
  statement {
    sid    = "AllowLambdasViaS3"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = var.lambda_role_arns
    }

    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.via_s3]
    }
  }

  # ---------------------------------------------------------------------------
  # Lambdas → SNS via this key (alerts topic publish, STEP 8).
  # ---------------------------------------------------------------------------
  statement {
    sid    = "AllowLambdasViaSNS"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = var.lambda_role_arns
    }

    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = [local.via_sns]
    }
  }
}

# =============================================================================
# The key itself
#
# enable_key_rotation       : annual auto-rotation; SOC2/PCI alignment, zero ops.
# deletion_window_in_days   : 30 (maximum). If we ever schedule deletion by
#                             mistake, there's a month to cancel before the
#                             material is destroyed.
# key_usage                 : ENCRYPT_DECRYPT — default; SIGN_VERIFY would be
#                             for asymmetric signing, not relevant here.
# multi_region              : false. Multi-region keys are for cross-region
#                             replicas/DR; we deploy a single region.
# =============================================================================
resource "aws_kms_key" "main" {
  description             = "CloudGuard ${var.environment} shared CMK — DynamoDB, S3, SNS envelope encryption"
  key_usage               = "ENCRYPT_DECRYPT"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  multi_region            = false

  policy = data.aws_iam_policy_document.kms_key_policy.json
}

# =============================================================================
# Alias — human-friendly handle (alias/cloudguard-dev) for the key.
# Downstream resources can reference the alias OR the ARN; we expose both in
# outputs so consumers can pick.
# =============================================================================
resource "aws_kms_alias" "main" {
  name          = local.alias_name
  target_key_id = aws_kms_key.main.key_id
}
