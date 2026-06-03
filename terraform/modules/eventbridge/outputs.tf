output "scan_rule_name" {
  description = "Name of the periodic scan EventBridge rule (target: Step Functions state machine)."
  value       = aws_cloudwatch_event_rule.scan_schedule.name
}

output "scan_rule_arn" {
  description = "ARN of the periodic scan EventBridge rule."
  value       = aws_cloudwatch_event_rule.scan_schedule.arn
}

output "daily_report_rule_name" {
  description = "Name of the daily report EventBridge rule (target: report_generator Lambda, window=24h)."
  value       = aws_cloudwatch_event_rule.daily_report.name
}

output "daily_report_rule_arn" {
  description = "ARN of the daily report EventBridge rule."
  value       = aws_cloudwatch_event_rule.daily_report.arn
}

output "weekly_report_rule_name" {
  description = "Name of the weekly report EventBridge rule (target: report_generator Lambda, window=168h)."
  value       = aws_cloudwatch_event_rule.weekly_report.name
}

output "weekly_report_rule_arn" {
  description = "ARN of the weekly report EventBridge rule."
  value       = aws_cloudwatch_event_rule.weekly_report.arn
}

output "remediation_schedule_rule_name" {
  description = "Name of the scheduled remediation EventBridge rule (target: remediation state machine). null when the remediation trigger isn't wired."
  value       = try(aws_cloudwatch_event_rule.remediation_schedule[0].name, null)
}

output "remediation_schedule_rule_arn" {
  description = "ARN of the scheduled remediation EventBridge rule. null when not wired."
  value       = try(aws_cloudwatch_event_rule.remediation_schedule[0].arn, null)
}

output "role_arn" {
  description = "ARN of the IAM role EventBridge assumes to invoke Step Functions."
  value       = aws_iam_role.eventbridge.arn
}

output "role_name" {
  description = "Name of the IAM role EventBridge assumes to invoke Step Functions."
  value       = aws_iam_role.eventbridge.name
}
