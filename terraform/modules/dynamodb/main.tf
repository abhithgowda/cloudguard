# =============================================================================
# main.tf — DynamoDB module
#
# Creates 3 tables for CloudGuard:
#   1. {project}-{env}-findings         — scan findings from all 3 scanners
#   2. {project}-{env}-cost-data        — daily cost per service (30-day history)
#   3. {project}-{env}-remediation-log  — actions taken by the cleanup Lambda
#
# All tables: PAY_PER_REQUEST, PITR, KMS (customer-managed CMK from kms module).
#
# Naming MUST match the pre-built ARNs in the IAM module locals (STEP 4).
# If you change the name_prefix here, update the IAM module too.
# =============================================================================

locals {
  name_prefix = "${var.project}-${var.environment}"
}

# =============================================================================
# Table 1: findings
# One record per finding raised by any of the 3 scanner Lambdas.
#
# GSI: severity-index — lets the report generator pull all CRITICAL findings
#      without a full table scan; hash key is severity, sort key is timestamp.
# GSI: category-index — lets callers filter by cost / security / cleanup.
# TTL: expires_at — Lambda sets this to now + 90 days so DynamoDB auto-expires
#      old findings without needing a periodic cleanup job.
# =============================================================================
resource "aws_dynamodb_table" "findings" {
  name         = "${local.name_prefix}-findings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "finding_id"
  range_key    = "timestamp"

  attribute {
    name = "finding_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  attribute {
    name = "severity"
    type = "S"
  }

  attribute {
    name = "category"
    type = "S"
  }

  global_secondary_index {
    name            = "severity-index"
    hash_key        = "severity"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "category-index"
    hash_key        = "category"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    # Customer-managed CMK from the kms module (STEP 6). Lets us audit Decrypt
    # calls in CloudTrail, set a key policy, and rotate on our own schedule.
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }
}

# =============================================================================
# Table 2: cost-data
# Daily cost per service, written by the cost scanner Lambda.
# PK: date (YYYY-MM-DD), SK: service_name.
# No GSIs — every query specifies both dimensions, a full-key lookup suffices.
# =============================================================================
resource "aws_dynamodb_table" "cost_data" {
  name         = "${local.name_prefix}-cost-data"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "date"
  range_key    = "service_name"

  attribute {
    name = "date"
    type = "S"
  }

  attribute {
    name = "service_name"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }
}

# =============================================================================
# Table 3: remediation-log
# One record per cleanup action (delete volume, release EIP, etc.).
#
# GSI: status-index — lets operators query all FAILED remediations that need
#      manual follow-up without scanning the whole table.
# =============================================================================
resource "aws_dynamodb_table" "remediation_log" {
  name         = "${local.name_prefix}-remediation-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "remediation_id"
  range_key    = "timestamp"

  attribute {
    name = "remediation_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  global_secondary_index {
    name            = "status-index"
    hash_key        = "status"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }
}
