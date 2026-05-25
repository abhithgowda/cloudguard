output "state_machine_arn" {
  description = "ARN of the CloudGuard state machine. Consumed by EventBridge (STEP 17) as the schedule target."
  value       = aws_sfn_state_machine.this.arn
}

output "state_machine_name" {
  description = "Name of the CloudGuard state machine (e.g. cloudguard-dev-workflow)."
  value       = aws_sfn_state_machine.this.name
}

output "role_arn" {
  description = "ARN of the IAM role assumed by Step Functions to invoke the 4 Lambdas + deliver logs/traces."
  value       = aws_iam_role.sfn.arn
}

output "role_name" {
  description = "Name of the Step Functions execution role."
  value       = aws_iam_role.sfn.name
}

output "log_group_name" {
  description = "CloudWatch log group receiving Step Functions execution logs (CMK-encrypted, 30-day retention)."
  value       = aws_cloudwatch_log_group.sfn.name
}

output "log_group_arn" {
  description = "ARN of the SFN execution log group."
  value       = aws_cloudwatch_log_group.sfn.arn
}
