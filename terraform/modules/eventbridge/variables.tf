variable "project" {
  description = "Project name used as a naming prefix (e.g. cloudguard)."
  type        = string
  default     = "cloudguard"
}

variable "environment" {
  description = "Deployment environment (dev, prod). Drives rule + role name suffixes."
  type        = string
}

variable "tags" {
  description = "Extra tags merged onto every taggable resource in this module, on top of the provider default_tags (STEP 24). The caller passes a Component tag for finer-grained cost allocation. Default empty keeps the module usable standalone."
  type        = map(string)
  default     = {}
}

# -----------------------------------------------------------------------------
# Targets — provided by the caller from outputs of the step_functions and
# report_generator modules. Names are surfaced separately from ARNs because
# aws_lambda_permission needs the function NAME (not the ARN) for its
# function_name argument.
# -----------------------------------------------------------------------------
variable "state_machine_arn" {
  description = "ARN of the Step Functions state machine (target of the periodic scan rule)."
  type        = string
}

variable "report_lambda_arn" {
  description = "ARN of the report_generator Lambda (target of the daily and weekly report rules)."
  type        = string
}

variable "report_lambda_name" {
  description = "Name of the report_generator Lambda. Required by aws_lambda_permission, which addresses functions by name."
  type        = string
}

# -----------------------------------------------------------------------------
# Schedule expressions
#
# AWS EventBridge accepts two forms:
#   - rate(<n> <unit>) — fixed interval, no second-precision drift
#   - cron(<min> <hour> <day-of-month> <month> <day-of-week> <year>)
#     (6-field cron — note the YEAR field, not standard 5-field cron)
#
# AWS cron expressions are in UTC. IST = UTC + 5:30, so 08:00 IST = 02:30 UTC.
# `?` is required where `*` would otherwise collide between day-of-month and
# day-of-week — pick the one you want to specify, use `?` on the other.
# -----------------------------------------------------------------------------
variable "scan_schedule_expression" {
  description = "Schedule for the parallel scanner workflow. Blueprint default: every 6 hours."
  type        = string
  default     = "rate(6 hours)"
}

variable "daily_report_schedule_expression" {
  description = "Schedule for the daily report. Blueprint default: 02:30 UTC (08:00 IST), every day."
  type        = string
  default     = "cron(30 2 * * ? *)"
}

variable "weekly_report_schedule_expression" {
  description = <<-EOT
    Schedule for the weekly (168 h) report. 02:30 UTC on Mondays (08:00 IST Monday).
    Same report_generator Lambda as the daily rule — the rule's Input field
    overrides REPORT_WINDOW_HOURS per-invocation. See STEP 13's "one Lambda +
    two EventBridge rules" decision.
  EOT
  type        = string
  default     = "cron(30 2 ? * MON *)"
}

# -----------------------------------------------------------------------------
# auto_remediate gate (the second of STEP 12's two gates)
#
# This sets the `auto_remediate` field in the JSON payload EventBridge passes
# to Step Functions for the periodic scan. The first gate is the Lambda's
# AUTO_REMEDIATE env var (set in module.resource_cleanup). The cleanup Lambda
# refuses to act unless BOTH gates are true — see STEP 12 decision log.
#
# Default false means every scheduled run is dry-run. True async approval
# (per-resource Approve/Reject links) is the post-DoD STEP 25 stretch.
# -----------------------------------------------------------------------------
variable "auto_remediate" {
  description = "Value passed as the EventBridge target's `auto_remediate` field on the scheduled scan. Default false = dry-run. Real remediation requires the Lambda env var AUTO_REMEDIATE=true AS WELL."
  type        = bool
  default     = false
}

# -----------------------------------------------------------------------------
# Tunables for the report windows. EventBridge passes these as the
# `report_window_hours` field in the Input JSON; the report_generator Lambda
# treats event input as authoritative over the REPORT_WINDOW_HOURS env var.
# -----------------------------------------------------------------------------
variable "daily_report_window_hours" {
  description = "Window passed to the report_generator Lambda by the daily rule. Default 24h."
  type        = number
  default     = 24

  validation {
    condition     = var.daily_report_window_hours >= 1 && var.daily_report_window_hours <= 720
    error_message = "daily_report_window_hours must be between 1 and 720 (30 days)."
  }
}

variable "weekly_report_window_hours" {
  description = "Window passed to the report_generator Lambda by the weekly rule. Default 168h (7 days)."
  type        = number
  default     = 168

  validation {
    condition     = var.weekly_report_window_hours >= 1 && var.weekly_report_window_hours <= 720
    error_message = "weekly_report_window_hours must be between 1 and 720 (30 days)."
  }
}

# -----------------------------------------------------------------------------
# Toggles to disable individual rules without removing them from state.
# Useful for: (a) freezing scheduled runs while debugging in dev, (b) prod
# pause windows for cost-control sanity. EventBridge bills nothing for a
# DISABLED rule — cheaper than destroying + recreating.
# -----------------------------------------------------------------------------
variable "scan_rule_enabled" {
  description = "Set false to disable the scheduled scan rule without destroying it."
  type        = bool
  default     = true
}

variable "daily_report_rule_enabled" {
  description = "Set false to disable the daily report rule without destroying it."
  type        = bool
  default     = true
}

variable "weekly_report_rule_enabled" {
  description = "Set false to disable the weekly report rule without destroying it."
  type        = bool
  default     = true
}
