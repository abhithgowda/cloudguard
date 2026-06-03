# =============================================================================
# outputs.tf — Remediation Approval module outputs (STEP 25)
# =============================================================================

output "state_machine_arn" {
  description = "ARN of the remediation state machine. Start an execution here (console or CLI) to kick off a human-approved cleanup run."
  value       = aws_sfn_state_machine.this.arn
}

output "state_machine_name" {
  description = "Name of the remediation state machine (e.g. cloudguard-dev-remediation)."
  value       = aws_sfn_state_machine.this.name
}

output "sfn_role_arn" {
  description = "ARN of the IAM role the remediation state machine assumes."
  value       = aws_iam_role.sfn.arn
}

output "api_endpoint" {
  description = "Base URL of the Approve/Reject HTTP API. The approval Lambda receives this via the SFN payload (not as an env var) and appends /approve or /reject."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "approvals_table_name" {
  description = "Name of the approvals DynamoDB table (approval_id → task token, TTL-purged)."
  value       = aws_dynamodb_table.approvals.name
}

output "approvals_table_arn" {
  description = "ARN of the approvals DynamoDB table."
  value       = aws_dynamodb_table.approvals.arn
}

output "hmac_param_name" {
  description = "SSM SecureString parameter name holding the HMAC signing key. The approval Lambda reads it via HMAC_PARAM_NAME."
  value       = aws_ssm_parameter.hmac_secret.name
}

output "log_group_name" {
  description = "CloudWatch log group receiving remediation SFN execution logs (CMK-encrypted)."
  value       = aws_cloudwatch_log_group.sfn.name
}
