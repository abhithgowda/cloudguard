# =============================================================================
# variables.tf — CloudWatch module inputs (STEP 22)
#
# Reusable observability module: one dashboard + per-Lambda error-rate and
# duration alarms + a Step Functions failure alarm. All alarms fan out to the
# existing cloudguard-alerts SNS topic (see alarm_topic_arn). Built reusable so
# a future prod environment calls the same module with its own ARNs/names.
# =============================================================================

variable "project" {
  description = "Project name (cloudguard). Used as the naming prefix for the dashboard and every alarm — also what the SNS/KMS CloudWatch grants match via aws:SourceArn = arn:...:alarm:<project>-<environment>-*."
  type        = string
  default     = "cloudguard"
}

variable "environment" {
  description = "Deployment environment (dev / prod). Part of every alarm + dashboard name."
  type        = string
}

variable "aws_region" {
  description = "Region the dashboard widgets render metrics for. CloudWatch dashboard widgets are region-pinned in their JSON, so this must match the provider region."
  type        = string
}

# -----------------------------------------------------------------------------
# Targets to monitor
# -----------------------------------------------------------------------------
variable "lambda_functions" {
  description = <<-EOT
    Map of Lambda functions to monitor, keyed by function name. Each value
    carries the function's timeout in seconds — needed because the duration
    alarm threshold is 80% of the per-function timeout, and the report
    generator (600s) differs from the three scanners (300s).

    Example:
      {
        "cloudguard-dev-cost-scanner"     = { timeout = 300 }
        "cloudguard-dev-report-generator" = { timeout = 600 }
      }
  EOT
  type = map(object({
    timeout = number
  }))
}

variable "state_machine_arn" {
  description = "ARN of the Step Functions state machine — the dimension for the SFN dashboard widget and the ExecutionsFailed alarm."
  type        = string
}

variable "state_machine_name" {
  description = "Name of the Step Functions state machine — used in the dashboard widget title only (the metric dimension is the ARN)."
  type        = string
}

variable "dynamodb_table_names" {
  description = "List of DynamoDB table names whose consumed read/write capacity is plotted on the dashboard. Pass findings + cost-data + remediation-log."
  type        = list(string)
}

variable "alarm_topic_arn" {
  description = "ARN of the SNS topic that receives alarm notifications (and OK/recovery notifications). Reuses the existing cloudguard-alerts topic per the STEP 22 decision."
  type        = string
}

# -----------------------------------------------------------------------------
# Tuning knobs (defaults encode the blueprint thresholds)
# -----------------------------------------------------------------------------
variable "error_rate_threshold_percent" {
  description = "Lambda error-rate alarm threshold, as a percent. Blueprint says > 5%. Computed via metric math (errors / invocations * 100) so it's a true rate, not a raw count — a single error during a low-traffic scan can't trip it."
  type        = number
  default     = 5
}

variable "duration_threshold_ratio" {
  description = "Fraction of a function's configured timeout at which the duration alarm trips. Blueprint says 80% → 0.8. Applied per-function: 300s timeout → 240000ms, 600s timeout → 480000ms."
  type        = number
  default     = 0.8
}

variable "alarm_period_seconds" {
  description = "Evaluation period for every alarm, in seconds. 300s (5 min) aligns with the default CloudWatch metric resolution for Lambda/SFN and is short enough to page promptly without flapping on a single noisy datapoint."
  type        = number
  default     = 300
}

variable "include_ok_actions" {
  description = "If true, alarms also notify the SNS topic when they return to OK (recovery). On-call-correct default: you want to know the system healed, not just that it broke. Set false to suppress recovery emails."
  type        = bool
  default     = true
}
