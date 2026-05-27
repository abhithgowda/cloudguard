# =============================================================================
# main.tf — EventBridge module (STEP 17)
#
# Three scheduled rules, two targets, one role:
#
#   scan_schedule            ──► Step Functions state machine
#     (rate(6 hours))            (every 6 h; Input passes auto_remediate flag)
#
#   daily_report_schedule    ──► report_generator Lambda (directly)
#     (cron(30 2 * * ? *))       (08:00 IST daily; window = 24 h)
#
#   weekly_report_schedule   ──► report_generator Lambda (directly)
#     (cron(30 2 ? * MON *))     (08:00 IST Mondays; window = 168 h)
#
# IAM layout:
#   - aws_iam_role (assume by events.amazonaws.com) for the SFN target.
#   - aws_iam_role_policy: states:StartExecution on the one state machine ARN.
#   - aws_lambda_permission x2 (resource-based perms on the Lambda) — direct
#     Lambda invocations from EventBridge require the LAMBDA side to allow
#     events.amazonaws.com, not an IAM role on the EventBridge side.
#
# Why a third (weekly) rule beyond the blueprint:
#   STEP 13 designed the report Lambda for both 24 h and 168 h windows
#   ("one Lambda + two EventBridge rules") and the Lambda already reads
#   `event.get("report_window_hours")` as authoritative. The blueprint
#   specifies only the daily one — the weekly is the matching half of the
#   STEP 13 design. Documented in this STEP's decision log.
#
# Why the SFN target uses an IAM role but the Lambda targets use
# aws_lambda_permission (resource-based):
#   They are different invocation models. EventBridge → Step Functions calls
#   StartExecution under an IAM role identified by `role_arn` on the target.
#   EventBridge → Lambda direct calls InvokeFunction; AWS resolves the call
#   through the Lambda's resource policy (function policy), not through an
#   IAM role on the rule. Using both is the AWS-documented pattern.
# =============================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  scan_rule_name    = "${var.project}-${var.environment}-scan-schedule"
  daily_rule_name   = "${var.project}-${var.environment}-daily-report"
  weekly_rule_name  = "${var.project}-${var.environment}-weekly-report"
  role_name         = "${var.project}-${var.environment}-eventbridge-role"

  # Inputs passed verbatim to each target. The state machine receives this as
  # its execution input; the report_generator Lambda receives it as the event.
  # auto_remediate carries the SECOND of the two gates from STEP 12 — even if
  # true here, the cleanup Lambda still refuses unless its env var also opts in.
  scan_input = jsonencode({
    auto_remediate = var.auto_remediate
    source         = "eventbridge_scan_schedule"
  })

  daily_report_input = jsonencode({
    report_window_hours = var.daily_report_window_hours
    source              = "eventbridge_daily_report"
  })

  weekly_report_input = jsonencode({
    report_window_hours = var.weekly_report_window_hours
    source              = "eventbridge_weekly_report"
  })
}

# =============================================================================
# Rule 1: Periodic scan — every 6 hours → Step Functions
# =============================================================================
resource "aws_cloudwatch_event_rule" "scan_schedule" {
  name                = local.scan_rule_name
  description         = "CloudGuard ${var.environment}: trigger the parallel-scanner Step Functions workflow on a fixed schedule."
  schedule_expression = var.scan_schedule_expression
  state               = var.scan_rule_enabled ? "ENABLED" : "DISABLED"

  tags = {
    Name = local.scan_rule_name
  }
}

resource "aws_cloudwatch_event_target" "scan_schedule" {
  rule      = aws_cloudwatch_event_rule.scan_schedule.name
  target_id = "step-functions-workflow"
  arn       = var.state_machine_arn
  role_arn  = aws_iam_role.eventbridge.arn
  input     = local.scan_input
}

# =============================================================================
# Rule 2: Daily report — 08:00 IST → report_generator Lambda directly
# =============================================================================
resource "aws_cloudwatch_event_rule" "daily_report" {
  name                = local.daily_rule_name
  description         = "CloudGuard ${var.environment}: invoke the report_generator Lambda with a 24h window every day at 08:00 IST."
  schedule_expression = var.daily_report_schedule_expression
  state               = var.daily_report_rule_enabled ? "ENABLED" : "DISABLED"

  tags = {
    Name = local.daily_rule_name
  }
}

resource "aws_cloudwatch_event_target" "daily_report" {
  rule      = aws_cloudwatch_event_rule.daily_report.name
  target_id = "report-generator-daily"
  arn       = var.report_lambda_arn
  input     = local.daily_report_input
}

# =============================================================================
# Rule 3: Weekly report — 08:00 IST Mondays → report_generator Lambda directly
# =============================================================================
resource "aws_cloudwatch_event_rule" "weekly_report" {
  name                = local.weekly_rule_name
  description         = "CloudGuard ${var.environment}: invoke the report_generator Lambda with a 168h window every Monday at 08:00 IST."
  schedule_expression = var.weekly_report_schedule_expression
  state               = var.weekly_report_rule_enabled ? "ENABLED" : "DISABLED"

  tags = {
    Name = local.weekly_rule_name
  }
}

resource "aws_cloudwatch_event_target" "weekly_report" {
  rule      = aws_cloudwatch_event_rule.weekly_report.name
  target_id = "report-generator-weekly"
  arn       = var.report_lambda_arn
  input     = local.weekly_report_input
}

# =============================================================================
# IAM role for EventBridge → Step Functions
#
# Step Functions targets need an IAM role to authorise StartExecution. Lambda
# targets do NOT use this role (they use resource-based perms below).
# =============================================================================
resource "aws_iam_role" "eventbridge" {
  name        = local.role_name
  description = "Role assumed by EventBridge to start CloudGuard Step Functions executions."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "events.amazonaws.com" }
    }]
  })
}

# -----------------------------------------------------------------------------
# Inline policy: states:StartExecution on the ONE state machine ARN.
#
# Enumerating the exact ARN (not a wildcard) means a future state machine in
# the same account cannot be started by this role without an IAM change.
# Same defense-in-depth posture as the SFN role's Lambda-invoke grant.
# -----------------------------------------------------------------------------
resource "aws_iam_role_policy" "start_execution" {
  name = "${local.role_name}-start-execution"
  role = aws_iam_role.eventbridge.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "StartCloudGuardWorkflow"
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = [var.state_machine_arn]
    }]
  })
}

# =============================================================================
# Resource-based perms: allow EventBridge to invoke the report Lambda
#
# Two permissions because each rule's ARN is a distinct SourceArn — without
# both, only the rule whose ARN matches can invoke. Scoping SourceArn to the
# specific rule ARN (not the function ARN, not "*") means only THESE two
# rules can fire the Lambda. Anything else trying to invoke directly via
# EventBridge gets AccessDenied.
#
# The `aws:SourceAccount` condition (added via source_account) defends against
# the "confused deputy" pattern where another account's EventBridge could in
# principle invoke this Lambda. Same hardening shape as the S3 logs-bucket
# policy from STEP 7.
# =============================================================================
resource "aws_lambda_permission" "allow_daily_report" {
  statement_id  = "AllowDailyReportFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = var.report_lambda_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_report.arn
  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_lambda_permission" "allow_weekly_report" {
  statement_id  = "AllowWeeklyReportFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = var.report_lambda_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_report.arn
  source_account = data.aws_caller_identity.current.account_id
}
