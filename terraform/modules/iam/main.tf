# =============================================================================
# main.tf — IAM module
#
# Creates one IAM role per Lambda function in CloudGuard, each with a
# separate inline policy following least-privilege.
#
# Roles:
#   1. cost_scanner       — reads Cost Explorer, EC2/RDS describe, writes to
#                           findings + cost_data DynamoDB tables.
#   2. security_scanner   — reads Config, EC2 SGs, S3 bucket configs, IAM
#                           users/keys, writes to findings table.
#   3. resource_cleanup   — describes + deletes zombie EC2 volumes/EIPs/
#                           snapshots, writes to findings + remediation_log,
#                           publishes to SNS.
#   4. report_generator   — queries DynamoDB tables, writes HTML reports to
#                           S3, sends email via SES, publishes to SNS.
#
# All roles also receive AWSLambdaBasicExecutionRole (CloudWatch Logs perms).
# =============================================================================

# -----------------------------------------------------------------------------
# Account context — used to build resource ARNs dynamically.
# Avoids hardcoding the account ID anywhere.
# -----------------------------------------------------------------------------
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  name_prefix = "${var.project}-${var.environment}"
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.name

  # -- DynamoDB table ARNs (these tables will be created in STEP 5) ----------
  # Naming convention is enforced here AND in the DynamoDB module.
  findings_table_arn  = "arn:aws:dynamodb:${local.region}:${local.account_id}:table/${local.name_prefix}-findings"
  cost_data_arn       = "arn:aws:dynamodb:${local.region}:${local.account_id}:table/${local.name_prefix}-cost-data"
  remediation_log_arn = "arn:aws:dynamodb:${local.region}:${local.account_id}:table/${local.name_prefix}-remediation-log"

  # -- SNS alerts topic ARN (created in STEP 8) ------------------------------
  alerts_topic_arn = "arn:aws:sns:${local.region}:${local.account_id}:${local.name_prefix}-alerts"

  # -- Lambda assume-role trust policy ---------------------------------------
  # Trust policy is identical for all 4 roles — only the Lambda service can
  # assume them. Defining once and reusing avoids drift.
  lambda_assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRole"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })

  # AWS-managed policy that grants CloudWatch Logs write permissions.
  # Used by every Lambda — using the AWS-blessed managed policy instead of
  # rewriting it ourselves keeps the function-specific policies focused on
  # business logic.
  basic_execution_policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# =============================================================================
# Role 1: Cost Scanner
# Reads Cost Explorer + EC2/RDS describe; writes to findings + cost_data.
# =============================================================================
resource "aws_iam_role" "cost_scanner" {
  name               = "${local.name_prefix}-cost-scanner-role"
  description        = "Role for CloudGuard cost scanner Lambda — reads Cost Explorer, writes findings."
  assume_role_policy = local.lambda_assume_role_policy
}

resource "aws_iam_role_policy" "cost_scanner" {
  name = "${local.name_prefix}-cost-scanner-policy"
  role = aws_iam_role.cost_scanner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Cost Explorer APIs do not support resource-level permissions.
        # Resource must be "*". This is an AWS API limitation, not a design choice.
        Sid    = "CostExplorerReadOnly"
        Effect = "Allow"
        Action = [
          "ce:GetCostAndUsage",
          "ce:GetCostForecast"
        ]
        Resource = "*"
      },
      {
        # Describe APIs for cost-correlation context. Cannot be scoped to
        # specific instances/DBs — Describe* doesn't support resource ARNs.
        Sid    = "ComputeAndDatabaseDescribe"
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "rds:DescribeDBInstances"
        ]
        Resource = "*"
      },
      {
        # DynamoDB writes scoped to ONLY the two tables this function uses.
        # /index/* covers GSI queries.
        Sid    = "DynamoDBWriteFindingsAndCostData"
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:Query"
        ]
        Resource = [
          local.findings_table_arn,
          "${local.findings_table_arn}/index/*",
          local.cost_data_arn,
          "${local.cost_data_arn}/index/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "cost_scanner_basic" {
  role       = aws_iam_role.cost_scanner.name
  policy_arn = local.basic_execution_policy_arn
}

# =============================================================================
# Role 2: Security Scanner
# Reads Config, EC2 SGs, S3 configs, IAM users/keys; writes to findings.
# =============================================================================
resource "aws_iam_role" "security_scanner" {
  name               = "${local.name_prefix}-security-scanner-role"
  description        = "Role for CloudGuard security scanner Lambda — reads SG, S3, IAM, Config."
  assume_role_policy = local.lambda_assume_role_policy
}

resource "aws_iam_role_policy" "security_scanner" {
  name = "${local.name_prefix}-security-scanner-policy"
  role = aws_iam_role.security_scanner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # AWS Config compliance scan (config_checker.py, STEP 11 hotfix).
        # DescribeComplianceByConfigRule lists rules + overall compliance;
        # GetComplianceDetailsByConfigRule returns the non-compliant
        # resources for each NON_COMPLIANT rule. Neither supports
        # resource-level perms — Config rules are account-scoped concepts.
        Sid    = "ConfigCompliance"
        Effect = "Allow"
        Action = [
          "config:DescribeComplianceByConfigRule",
          "config:GetComplianceDetailsByConfigRule"
        ]
        Resource = "*"
      },
      {
        # SG check (STEP 11) + EBS encryption check (STEP 11) both live in
        # the security_scanner Lambda. Describe* doesn't support resource-
        # level perms, so they're grouped under one statement.
        Sid    = "EC2SecurityReadOnly"
        Effect = "Allow"
        Action = [
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeVolumes"
        ]
        Resource = "*"
      },
      {
        # Read all buckets' configs to check for misconfigs. Scanner must
        # see every bucket in the account, so Resource is "*" for these
        # specific read-only actions.
        Sid    = "S3BucketConfigRead"
        Effect = "Allow"
        Action = [
          "s3:ListAllMyBuckets",
          "s3:GetBucketPolicy",
          "s3:GetBucketEncryption",
          "s3:GetBucketPublicAccessBlock",
          "s3:GetBucketVersioning"
        ]
        Resource = "*"
      },
      {
        # IAM user audit: list users, list their access keys, check key
        # last-use, check MFA, check attached policies.
        Sid    = "IAMUserAudit"
        Effect = "Allow"
        Action = [
          "iam:ListUsers",
          "iam:ListAccessKeys",
          "iam:GetAccessKeyLastUsed",
          "iam:ListMFADevices",
          "iam:ListAttachedUserPolicies"
        ]
        Resource = "*"
      },
      {
        Sid    = "DynamoDBWriteFindings"
        Effect = "Allow"
        Action = ["dynamodb:PutItem"]
        Resource = [
          local.findings_table_arn,
          "${local.findings_table_arn}/index/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "security_scanner_basic" {
  role       = aws_iam_role.security_scanner.name
  policy_arn = local.basic_execution_policy_arn
}

# =============================================================================
# Role 3: Resource Cleanup
# Describes + DELETES zombie EBS volumes/EIPs; publishes SNS notifications.
#
# WARNING: this role has destructive permissions (DeleteVolume, ReleaseAddress,
# DeleteSnapshot). In a hardened production setup, scope these with a Condition
# on a tag like:
#   "ec2:ResourceTag/AutoCleanup": "true"
# That way the cleanup function can only delete resources explicitly marked
# for cleanup. Hardening TODO — see PROGRESS.md.
# =============================================================================
resource "aws_iam_role" "resource_cleanup" {
  name               = "${local.name_prefix}-resource-cleanup-role"
  description        = "Role for CloudGuard cleanup Lambda — describes and deletes zombie EC2 resources."
  assume_role_policy = local.lambda_assume_role_policy
}

resource "aws_iam_role_policy" "resource_cleanup" {
  name = "${local.name_prefix}-resource-cleanup-policy"
  role = aws_iam_role.resource_cleanup.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EC2ZombieDescribe"
        Effect = "Allow"
        Action = [
          "ec2:DescribeVolumes",
          "ec2:DescribeAddresses",
          "ec2:DescribeSnapshots"
        ]
        Resource = "*"
      },
      {
        # Destructive — see warning at top of this block.
        # DeleteSnapshot added in STEP 12 for the snapshot-cleanup auto-
        # remediate path; same Resource="*" + tag-Condition hardening TODO.
        Sid    = "EC2ZombieDelete"
        Effect = "Allow"
        Action = [
          "ec2:DeleteVolume",
          "ec2:ReleaseAddress",
          "ec2:DeleteSnapshot"
        ]
        Resource = "*"
      },
      {
        Sid    = "DynamoDBWriteFindingsAndRemediation"
        Effect = "Allow"
        Action = ["dynamodb:PutItem"]
        Resource = [
          local.findings_table_arn,
          local.remediation_log_arn,
          "${local.remediation_log_arn}/index/*"
        ]
      },
      {
        Sid      = "SNSPublishAlerts"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = local.alerts_topic_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "resource_cleanup_basic" {
  role       = aws_iam_role.resource_cleanup.name
  policy_arn = local.basic_execution_policy_arn
}

# =============================================================================
# Role 4: Report Generator
# Reads DynamoDB tables, writes HTML to S3, sends email, publishes SNS.
# =============================================================================
resource "aws_iam_role" "report_generator" {
  name               = "${local.name_prefix}-report-generator-role"
  description        = "Role for CloudGuard report generator Lambda — queries findings, writes reports."
  assume_role_policy = local.lambda_assume_role_policy
}

resource "aws_iam_role_policy" "report_generator" {
  name = "${local.name_prefix}-report-generator-policy"
  role = aws_iam_role.report_generator.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Read all 3 DynamoDB tables.
        Sid    = "DynamoDBQueryAndScan"
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          local.findings_table_arn,
          "${local.findings_table_arn}/index/*",
          local.cost_data_arn,
          "${local.cost_data_arn}/index/*",
          local.remediation_log_arn,
          "${local.remediation_log_arn}/index/*"
        ]
      },
      {
        # Write HTML reports to the reports bucket only. Object-level
        # permissions need the /* suffix on the bucket ARN.
        Sid      = "S3WriteReports"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${var.reports_bucket_arn}/*"
      },
      {
        # SES SendEmail does not have resource-level perms in the classic
        # sense — Resource is "*" with optional Conditions on identities.
        # We'll add a Condition restricting to verified identities in a
        # later hardening pass.
        Sid      = "SESSendEmail"
        Effect   = "Allow"
        Action   = ["ses:SendEmail"]
        Resource = "*"
      },
      {
        Sid      = "SNSPublishAlerts"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = local.alerts_topic_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "report_generator_basic" {
  role       = aws_iam_role.report_generator.name
  policy_arn = local.basic_execution_policy_arn
}
