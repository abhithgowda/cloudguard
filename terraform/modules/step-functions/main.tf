# =============================================================================
# main.tf — Step Functions module (STEP 16, revised in STEP 17.5)
#
# Orchestrates the 3 CloudGuard scanner Lambdas as a single state machine:
#
#   ParallelScanners
#     ├─ CostScanner       (Retry x2, Catch → CostScanFailed)
#     ├─ SecurityScanner   (Retry x2, Catch → SecurityScanFailed)
#     └─ ResourceCleanup   (Retry x2, Catch → CleanupFailed)
#   (End)
#
# STEP 17.5 REVISION — GenerateReport removed from the workflow:
#   The 6-hourly EventBridge scan_schedule fires this state machine. If
#   GenerateReport stayed here, the report Lambda would run 4 times per day
#   and produce CONTENT-IDENTICAL output to the daily 08:00 IST report
#   (both use a 24-hour findings window). Pure email-noise redundancy.
#   The fix: scans now silently write findings to DynamoDB; reports are
#   EventBridge-scheduled separately by the daily (24h) + weekly (168h) rules
#   in the eventbridge module — they produce meaningfully different content.
#   See PROGRESS.md STEP 17.5 for the design discussion.
#
# Why STANDARD (not EXPRESS):
#   STANDARD workflows support executions up to 1 year, store complete history
#   in the SFN console, and bill per state transition. EXPRESS caps at 5 minutes
#   and bills per request — useful for high-TPS event-driven workloads, but
#   CloudGuard runs once every 6 hours and needs the visual execution graph
#   for debugging (STEP 20).
#
# Why ResultPath on ParallelScanners:
#   Default Parallel output is an array that REPLACES the state input. Keeping
#   the parallel results under `$.scanner_results` preserves the original
#   EventBridge Input (e.g. `{auto_remediate: false, source: "..."}`) for any
#   downstream inspection in execution history.
#
# Why Catch + Pass per branch (not Catch → Fail):
#   A single scanner failing must NOT abort the rest of the workflow. The Pass
#   state emits `{"status": "FAILED", "scanner": "<name>"}` so the per-branch
#   outcome is queryable in execution history.
#
# IAM scope:
#   - lambda:InvokeFunction limited to the 3 scanner Lambda ARNs (no
#     report_generator — it is no longer invoked from this workflow).
#   - logs:* needed only for SFN's vended-logs delivery (CreateLogDelivery
#     and friends) — all account-scoped APIs, can't be resource-scoped.
#   - xray:* for tracing — same constraint.
# =============================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  state_machine_name = "${var.project}-${var.environment}-workflow"
  role_name          = "${var.project}-${var.environment}-stepfunctions-role"

  # AWS console recognises the /aws/vendedlogs/states/ prefix as Step Functions
  # logs and groups them under the SFN service view. Matching the convention
  # also means anyone who created the log group via the console first would
  # land on the same name.
  log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}-Logs"

  # ---------------------------------------------------------------------------
  # Amazon States Language (ASL) workflow definition
  #
  # Authored as an HCL object + jsonencode() rather than a heredoc-templated
  # JSON file so:
  #   - Terraform validates the structure at plan time.
  #   - Lambda ARN interpolation uses native HCL (no templatefile/${} mixing).
  #   - The retry/catch parameters are addressable as variables for env-level
  #     tuning (prod might want MaxAttempts=3, dev keeps the blueprint's 2).
  # ---------------------------------------------------------------------------
  asl_definition = jsonencode({
    Comment = "CloudGuard ${var.environment} workflow — parallel scanners (silent; reports are EventBridge-scheduled separately, see STEP 17.5)."
    StartAt = "ParallelScanners"
    States = {
      ParallelScanners = {
        Type = "Parallel"
        # Preserve the original EventBridge Input at the top level and store
        # scanner outputs under $.scanner_results — keeps execution history
        # readable when inspecting payloads in the SFN console.
        ResultPath = "$.scanner_results"
        Branches = [
          # -- Branch 1: Cost scanner --------------------------------------
          {
            StartAt = "CostScanner"
            States = {
              CostScanner = {
                Type     = "Task"
                Resource = var.cost_scanner_arn
                Retry = [{
                  ErrorEquals     = ["States.ALL"]
                  MaxAttempts     = var.scanner_retry_max_attempts
                  BackoffRate     = var.scanner_retry_backoff_rate
                  IntervalSeconds = 1
                }]
                Catch = [{
                  ErrorEquals = ["States.ALL"]
                  Next        = "CostScanFailed"
                  ResultPath  = "$.error"
                }]
                End = true
              }
              CostScanFailed = {
                Type   = "Pass"
                Result = { status = "FAILED", scanner = "cost" }
                End    = true
              }
            }
          },
          # -- Branch 2: Security scanner ----------------------------------
          {
            StartAt = "SecurityScanner"
            States = {
              SecurityScanner = {
                Type     = "Task"
                Resource = var.security_scanner_arn
                Retry = [{
                  ErrorEquals     = ["States.ALL"]
                  MaxAttempts     = var.scanner_retry_max_attempts
                  BackoffRate     = var.scanner_retry_backoff_rate
                  IntervalSeconds = 1
                }]
                Catch = [{
                  ErrorEquals = ["States.ALL"]
                  Next        = "SecurityScanFailed"
                  ResultPath  = "$.error"
                }]
                End = true
              }
              SecurityScanFailed = {
                Type   = "Pass"
                Result = { status = "FAILED", scanner = "security" }
                End    = true
              }
            }
          },
          # -- Branch 3: Resource cleanup ----------------------------------
          # NOTE: auto_remediate is gated by both the per-env Lambda env var
          # AND the event payload (STEP 12 two-gate design). The state input
          # at ParallelScanners flows verbatim into each branch's Task, so
          # an EventBridge target (STEP 17) passing
          # `{"auto_remediate": true}` arrives here without state-machine
          # changes. The Lambda still refuses unless its env var ALSO opts in.
          {
            StartAt = "ResourceCleanup"
            States = {
              ResourceCleanup = {
                Type     = "Task"
                Resource = var.resource_cleanup_arn
                Retry = [{
                  ErrorEquals     = ["States.ALL"]
                  MaxAttempts     = var.scanner_retry_max_attempts
                  BackoffRate     = var.scanner_retry_backoff_rate
                  IntervalSeconds = 1
                }]
                Catch = [{
                  ErrorEquals = ["States.ALL"]
                  Next        = "CleanupFailed"
                  ResultPath  = "$.error"
                }]
                End = true
              }
              CleanupFailed = {
                Type   = "Pass"
                Result = { status = "FAILED", scanner = "cleanup" }
                End    = true
              }
            }
          },
        ]
        End = true
      }
    }
  })
}

# =============================================================================
# Execution log group
#
# Declared explicitly (not auto-created on first execution) so we can set
# retention + KMS encryption — same pattern as the Lambda module's log group
# in STEP 9. The KMS retrofit in this STEP widens the AllowCloudWatchLogsEncrypt
# Sid in the shared CMK policy to cover this log group's ARN pattern.
# =============================================================================
resource "aws_cloudwatch_log_group" "sfn" {
  name              = local.log_group_name
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = {
    StateMachine = local.state_machine_name
  }
}

# =============================================================================
# IAM role for Step Functions
#
# Step Functions assumes this role to invoke the 4 Lambdas, deliver execution
# logs to CloudWatch, and emit X-Ray trace segments. Trust policy locks the
# assume action to the SFN service principal — no other service can assume
# this role.
# =============================================================================
resource "aws_iam_role" "sfn" {
  name        = local.role_name
  description = "Role for CloudGuard ${var.environment} Step Functions state machine — invokes 4 Lambdas, delivers logs + X-Ray."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })
}

# -----------------------------------------------------------------------------
# Inline policy 1: lambda:InvokeFunction on EXACTLY the 3 scanner Lambda ARNs.
#
# STEP 17.5: report_generator removed — the SFN no longer invokes the report
# Lambda (reports are EventBridge-scheduled, see PROGRESS.md STEP 17.5).
#
# Hard-listing ARNs (rather than `arn:aws:lambda:*:*:function:cloudguard-${env}-*`)
# means a future Lambda accidentally named cloudguard-dev-anything cannot be
# invoked by THIS workflow without an IAM change. Tight blast radius.
#
# Both the function ARN AND `<arn>:*` are included — `:*` covers qualified
# versions/aliases, which AWS requires when the function is invoked by
# qualifier; including both is the AWS-documented safe form.
# -----------------------------------------------------------------------------
resource "aws_iam_role_policy" "lambda_invoke" {
  name = "${local.role_name}-lambda-invoke"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "InvokeCloudGuardScanners"
      Effect = "Allow"
      Action = ["lambda:InvokeFunction"]
      Resource = [
        var.cost_scanner_arn,
        "${var.cost_scanner_arn}:*",
        var.security_scanner_arn,
        "${var.security_scanner_arn}:*",
        var.resource_cleanup_arn,
        "${var.resource_cleanup_arn}:*",
      ]
    }]
  })
}

# -----------------------------------------------------------------------------
# Inline policy 2: CloudWatch Logs vended-logs delivery.
#
# Step Functions uses the CloudWatch Logs "log delivery" subsystem (the same
# one used by API Gateway, AppSync, etc.) to write execution logs. These APIs
# are account-scoped and don't support resource-level perms — Resource = "*"
# is the AWS-documented requirement.
#
# Reference: AWS docs — "Logging using CloudWatch Logs" for Step Functions.
# -----------------------------------------------------------------------------
resource "aws_iam_role_policy" "logs_delivery" {
  name = "${local.role_name}-logs-delivery"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "VendedLogsDelivery"
      Effect = "Allow"
      Action = [
        "logs:CreateLogDelivery",
        "logs:GetLogDelivery",
        "logs:UpdateLogDelivery",
        "logs:DeleteLogDelivery",
        "logs:ListLogDeliveries",
        "logs:PutResourcePolicy",
        "logs:DescribeResourcePolicies",
        "logs:DescribeLogGroups",
      ]
      Resource = "*"
    }]
  })
}

# -----------------------------------------------------------------------------
# Inline policy 3: X-Ray tracing.
#
# Required when `tracing_configuration.enabled = true`. Same Resource = "*"
# constraint as the logs-delivery grant — X-Ray APIs are account-scoped.
# -----------------------------------------------------------------------------
resource "aws_iam_role_policy" "xray" {
  count = var.tracing_enabled ? 1 : 0

  name = "${local.role_name}-xray"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "XRayTracing"
      Effect = "Allow"
      Action = [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets",
      ]
      Resource = "*"
    }]
  })
}

# =============================================================================
# The state machine
#
# `definition` is the ASL JSON built above. `logging_configuration` wires the
# execution logs to our pre-created KMS-encrypted log group. `tracing_configuration`
# enables X-Ray segments per state transition — combined with the Lambda
# tracing_config in STEP 9, this gives an end-to-end timeline across the
# workflow + each Lambda invocation in the X-Ray console.
#
# `depends_on` on the inline policies ensures the role can perform all required
# actions BEFORE the state machine is first eligible to execute (otherwise the
# first invocation can race the policy attachment).
# =============================================================================
resource "aws_sfn_state_machine" "this" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = local.asl_definition

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = var.include_execution_data
    level                  = var.logging_level
  }

  tracing_configuration {
    enabled = var.tracing_enabled
  }

  tags = {
    Name = local.state_machine_name
  }

  depends_on = [
    aws_iam_role_policy.lambda_invoke,
    aws_iam_role_policy.logs_delivery,
    aws_iam_role_policy.xray,
  ]
}
