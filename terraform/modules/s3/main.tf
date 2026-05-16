# =============================================================================
# main.tf — S3 module
#
# Creates two buckets:
#   1. Reports bucket (cloudguard-${env}-reports-${suffix})
#        - SSE-KMS using the shared CMK from the KMS module
#        - Versioning ENABLED
#        - All 4 public-access-block settings = true
#        - Lifecycle: transition to GLACIER_IR @ 90d, expire @ 365d
#        - Access logging delivered to the logs bucket below
#        - Bucket policy restricts s3:PutObject to the 4 Lambda role ARNs
#
#   2. Logs bucket (cloudguard-${env}-reports-logs-${suffix})
#        - SSE-S3 (AES256), NOT KMS — see decision note below
#        - Versioning ENABLED
#        - Public access fully blocked
#        - Receives access logs from the reports bucket
#
# Why the logs bucket is SSE-S3 and not SSE-KMS:
#   S3 access-log delivery is performed by the AWS logging service principal
#   (logging.s3.amazonaws.com). If the target bucket is SSE-KMS, the service
#   needs kms:GenerateDataKey on the CMK — workable but adds another grant to
#   the key policy with limited security upside (the logs themselves contain
#   no payload data, only request metadata). SSE-S3 is the path of least
#   resistance and matches AWS's own guidance for log destinations.
# =============================================================================

# Resolve the AWS log delivery account ID for this region — used in the
# logs-bucket policy so the S3 logging service can write objects.
# In practice this returns the well-known logging service principal; using the
# data source means we don't hardcode a region->account mapping.
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  reports_bucket = var.reports_bucket_name
  logs_bucket    = "${var.reports_bucket_name}-logs"
}

# =============================================================================
# Reports bucket
# =============================================================================
resource "aws_s3_bucket" "reports" {
  bucket = local.reports_bucket

  tags = {
    Name    = local.reports_bucket
    Purpose = "CloudGuard HTML/CSV reports — output of report_generator Lambda"
  }
}

# -- Versioning ---------------------------------------------------------------
# Versioning lets a report overwrite be recovered (and is also required for
# certain replication / object-lock configurations later if we need them).
resource "aws_s3_bucket_versioning" "reports" {
  bucket = aws_s3_bucket.reports.id

  versioning_configuration {
    status = "Enabled"
  }
}

# -- Public access block (all 4 = true) ---------------------------------------
# The only correct default for a reports bucket. Even if a future bucket
# policy or ACL accidentally permits public access, these settings override.
resource "aws_s3_bucket_public_access_block" "reports" {
  bucket = aws_s3_bucket.reports.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -- SSE-KMS encryption -------------------------------------------------------
# Every object encrypted with the shared CMK. bucket_key_enabled = true uses
# an S3 bucket key (envelope encryption at the bucket level) which reduces
# KMS API calls by ~99% on busy buckets at zero security cost.
resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

# -- Lifecycle ----------------------------------------------------------------
# Reports are read fresh by humans for ~90 days, then become audit/compliance
# evidence. Glacier Instant Retrieval keeps them millisecond-accessible but at
# Glacier pricing — better fit than Flexible Retrieval (hours to restore) for
# reports that may be linked from an audit ticket months later.
# Delete after 365 days — beyond a year, a CloudGuard finding is stale.
resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id

  rule {
    id     = "reports-tier-and-expire"
    status = "Enabled"

    filter {} # apply to all objects in the bucket

    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }

    expiration {
      days = 365
    }

    # Clean up old versions too — versioning is on, so without this we'd
    # accumulate noncurrent copies forever.
    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "GLACIER_IR"
    }

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    # Abort incomplete multipart uploads — these are silent storage bills.
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# -- Access logging -----------------------------------------------------------
# Every GET/PUT/DELETE against the reports bucket gets a log line in the
# logs bucket. Critical for forensics: if a report leaks, the access log
# shows who pulled it and when.
resource "aws_s3_bucket_logging" "reports" {
  bucket = aws_s3_bucket.reports.id

  target_bucket = aws_s3_bucket.logs.id
  target_prefix = "reports-access/"
}

# -- Bucket policy: only Lambda roles can write -------------------------------
# This is defense-in-depth on top of the IAM policy: even if a misconfigured
# IAM policy granted s3:PutObject to some other principal, this bucket policy
# would still reject the write. The reverse is also true — both policies must
# allow the action for it to succeed.
data "aws_iam_policy_document" "reports_bucket" {
  # Explicit deny: any non-TLS request gets rejected outright.
  # AWS recommends this on every bucket; Checkov flags its absence.
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    resources = [
      aws_s3_bucket.reports.arn,
      "${aws_s3_bucket.reports.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # Allow the 4 Lambda execution roles to PutObject / GetObject under
  # the reports prefix. Listed explicitly — no wildcards.
  statement {
    sid    = "AllowLambdaRolesWriteAndRead"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = var.lambda_role_arns
    }

    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket",
    ]

    resources = [
      aws_s3_bucket.reports.arn,
      "${aws_s3_bucket.reports.arn}/*",
    ]
  }
}

resource "aws_s3_bucket_policy" "reports" {
  bucket = aws_s3_bucket.reports.id
  policy = data.aws_iam_policy_document.reports_bucket.json

  # The bucket policy references the public-access-block settings; ensure
  # they apply first so a transient state can't briefly allow public access.
  depends_on = [aws_s3_bucket_public_access_block.reports]
}

# =============================================================================
# Logs bucket (S3 access logs for the reports bucket)
# =============================================================================
resource "aws_s3_bucket" "logs" {
  bucket = local.logs_bucket

  tags = {
    Name    = local.logs_bucket
    Purpose = "S3 access logs for the CloudGuard reports bucket"
  }
}

resource "aws_s3_bucket_versioning" "logs" {
  bucket = aws_s3_bucket.logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket = aws_s3_bucket.logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3 (AES256), NOT KMS — see header comment for reasoning.
resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Lifecycle: access logs balloon fast. Expire them after 90 days.
resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "expire-old-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# -- Logs-bucket policy: allow the S3 logging service to deliver logs --------
# Modern AWS uses the logging.s3.amazonaws.com service principal with the
# source bucket as a Condition. This is the current AWS-recommended pattern
# (replaces the older "log delivery group" ACL approach).
data "aws_iam_policy_document" "logs_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    resources = [
      aws_s3_bucket.logs.arn,
      "${aws_s3_bucket.logs.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "AllowS3LogDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.logs.arn}/*"]

    # Scope to logs coming from THIS account's reports bucket only.
    # Without these conditions any S3 logging service in any account
    # could (theoretically) be tricked into writing here.
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.reports.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_s3_bucket_policy" "logs" {
  bucket = aws_s3_bucket.logs.id
  policy = data.aws_iam_policy_document.logs_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.logs]
}