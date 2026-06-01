# =============================================================================
# main.tf — CloudWatch module (STEP 22)
#
# One dashboard plus three classes of alarm, all wired to the cloudguard-alerts
# SNS topic:
#   - Lambda error rate > 5%      (per function, metric math errors/invocations)
#   - Lambda duration > 80% timeout (per function, Maximum statistic)
#   - Step Functions ExecutionsFailed >= 1
#
# Why per-function alarms (for_each) instead of one aggregate:
#   An aggregate "any Lambda errored" alarm tells you SOMETHING broke but not
#   WHICH function — you'd still have to dig through 4 log groups at 2 AM.
#   Per-function alarms point straight at the culprit. The cost is identical
#   (alarms are billed per alarm either way, and 10 alarms are free-tier).
#
# Why metric math for the error RATE:
#   CloudWatch has no native "error rate" metric — only raw Errors and
#   Invocations counts. (errors / invocations) * 100 is the true percentage.
#   On a low-traffic scheduled scanner, a raw "Errors >= 1" alarm would fire at
#   100% on a single transient throttle; the rate expression needs 5% of actual
#   traffic to be errors. When invocations = 0 the expression yields no
#   datapoint, so treat_missing_data = notBreaching keeps a quiet function quiet.
# =============================================================================

locals {
  name_prefix = "${var.project}-${var.environment}"
  fn_names    = keys(var.lambda_functions)

  # Common alarm wiring. ok_actions echo the topic on recovery when enabled so
  # on-call sees "back to OK", not just the trip.
  alarm_actions = [var.alarm_topic_arn]
  ok_actions    = var.include_ok_actions ? [var.alarm_topic_arn] : []
}

# =============================================================================
# Dashboard
#
# dashboard_body is built with jsonencode (not a raw heredoc) so widget metric
# lists are generated from the same lambda_functions / table inputs the alarms
# use — one source of truth, and a readable plan diff.
# =============================================================================
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.name_prefix

  dashboard_body = jsonencode({
    widgets = [
      # ---- Row 0: the three Lambda fleet views -----------------------------
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 8
        height = 6
        properties = {
          title   = "Lambda Invocations (Sum)"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          stat    = "Sum"
          metrics = [for fn in local.fn_names : ["AWS/Lambda", "Invocations", "FunctionName", fn]]
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 0
        width  = 8
        height = 6
        properties = {
          title   = "Lambda Errors (Sum)"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          stat    = "Sum"
          metrics = [for fn in local.fn_names : ["AWS/Lambda", "Errors", "FunctionName", fn]]
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 0
        width  = 8
        height = 6
        properties = {
          title   = "Lambda Duration (Avg + p99, ms)"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          # Avg shows the typical run; p99 surfaces the tail a mean hides —
          # exactly the runs creeping toward the timeout the duration alarm guards.
          metrics = flatten([
            for fn in local.fn_names : [
              ["AWS/Lambda", "Duration", "FunctionName", fn, { stat = "Average", label = "${fn} avg" }],
              ["AWS/Lambda", "Duration", "FunctionName", fn, { stat = "p99", label = "${fn} p99" }],
            ]
          ])
        }
      },

      # ---- Row 1: orchestration + storage ----------------------------------
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "Step Functions: ${var.state_machine_name} executions"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          stat    = "Sum"
          metrics = [
            ["AWS/States", "ExecutionsStarted", "StateMachineArn", var.state_machine_arn],
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", var.state_machine_arn],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", var.state_machine_arn],
            ["AWS/States", "ExecutionsTimedOut", "StateMachineArn", var.state_machine_arn],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title   = "DynamoDB consumed capacity (RCU/WCU, Sum)"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          stat    = "Sum"
          # PAY_PER_REQUEST tables still emit consumed-capacity metrics — this
          # widget is the evidence there's no provisioned ceiling being hit.
          metrics = flatten([
            for t in var.dynamodb_table_names : [
              ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", t],
              ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", t],
            ]
          ])
        }
      },
    ]
  })
}

# =============================================================================
# Alarm 1 (×N) — Lambda error rate > threshold%, via metric math.
# =============================================================================
resource "aws_cloudwatch_metric_alarm" "lambda_error_rate" {
  for_each = var.lambda_functions

  # each.key is already the fully-qualified function name (cloudguard-dev-...),
  # so we don't re-prefix — and the name still matches the cloudguard-dev-*
  # ArnLike pattern the SNS/KMS CloudWatch grants are scoped to.
  alarm_name          = "${each.key}-error-rate-high"
  alarm_description   = "Error rate for ${each.key} >= ${var.error_rate_threshold_percent}% over ${var.alarm_period_seconds}s. Computed as (Errors / Invocations) * 100."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = var.error_rate_threshold_percent
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.ok_actions

  metric_query {
    id          = "error_rate"
    expression  = "(errors / invocations) * 100"
    label       = "${each.key} error rate %"
    return_data = true
  }

  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Errors"
      dimensions  = { FunctionName = each.key }
      period      = var.alarm_period_seconds
      stat        = "Sum"
    }
  }

  metric_query {
    id = "invocations"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Invocations"
      dimensions  = { FunctionName = each.key }
      period      = var.alarm_period_seconds
      stat        = "Sum"
    }
  }
}

# =============================================================================
# Alarm 2 (×N) — Lambda duration > ratio × timeout.
#
# Statistic = Maximum: a single run that's about to time out is exactly what we
# want to catch — averaging would dilute one 290s run across many fast ones.
# Threshold is per-function: 300s timeout → 240000ms, 600s → 480000ms.
# =============================================================================
resource "aws_cloudwatch_metric_alarm" "lambda_duration" {
  for_each = var.lambda_functions

  alarm_name          = "${each.key}-duration-high"
  alarm_description   = "Max duration for ${each.key} exceeded ${var.duration_threshold_ratio * 100}% of its ${each.value.timeout}s timeout — the function is approaching a hard timeout."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  statistic           = "Maximum"
  period              = var.alarm_period_seconds
  threshold           = each.value.timeout * 1000 * var.duration_threshold_ratio
  dimensions          = { FunctionName = each.key }
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.ok_actions
}

# =============================================================================
# Alarm 3 (×1) — Step Functions execution failed.
#
# ExecutionsFailed counts executions that ended in the FAILED state. Note this
# is distinct from a scanner-branch Catch→Pass (STEP 16): a caught scanner
# failure still SUCCEEDS the execution, so this alarm fires only on a genuine
# unhandled workflow failure — the signal you actually want to page on.
# =============================================================================
resource "aws_cloudwatch_metric_alarm" "sfn_execution_failed" {
  alarm_name          = "${local.name_prefix}-sfn-execution-failed"
  alarm_description   = "Step Functions state machine ${var.state_machine_name} had >= 1 FAILED execution in ${var.alarm_period_seconds}s."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  statistic           = "Sum"
  period              = var.alarm_period_seconds
  threshold           = 1
  dimensions          = { StateMachineArn = var.state_machine_arn }
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.ok_actions
}
