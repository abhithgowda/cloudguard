# =============================================================================
# outputs.tf — CloudWatch module outputs (STEP 22)
# =============================================================================

output "dashboard_name" {
  description = "Name of the CloudWatch dashboard (cloudguard-<env>). Open at console → CloudWatch → Dashboards."
  value       = aws_cloudwatch_dashboard.main.dashboard_name
}

output "dashboard_arn" {
  description = "ARN of the CloudWatch dashboard."
  value       = aws_cloudwatch_dashboard.main.dashboard_arn
}

output "error_rate_alarm_names" {
  description = "Names of the per-Lambda error-rate alarms."
  value       = [for a in aws_cloudwatch_metric_alarm.lambda_error_rate : a.alarm_name]
}

output "duration_alarm_names" {
  description = "Names of the per-Lambda duration alarms."
  value       = [for a in aws_cloudwatch_metric_alarm.lambda_duration : a.alarm_name]
}

output "sfn_failure_alarm_name" {
  description = "Name of the Step Functions execution-failed alarm."
  value       = aws_cloudwatch_metric_alarm.sfn_execution_failed.alarm_name
}
