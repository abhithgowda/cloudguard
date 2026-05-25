# =============================================================================
# outputs.tf — Dev environment outputs
#
# Surface key resource identifiers so downstream tooling (CI/CD, scripts,
# `terraform output`) can consume them without parsing module internals.
# =============================================================================

output "iam_role_arns" {
  description = "ARNs of all 4 Lambda execution roles."
  value = {
    cost_scanner     = module.iam.cost_scanner_role_arn
    security_scanner = module.iam.security_scanner_role_arn
    resource_cleanup = module.iam.resource_cleanup_role_arn
    report_generator = module.iam.report_generator_role_arn
  }
}

output "dynamodb_table_names" {
  description = "Names of all 3 DynamoDB tables."
  value = {
    findings        = module.dynamodb.findings_table_name
    cost_data       = module.dynamodb.cost_data_table_name
    remediation_log = module.dynamodb.remediation_log_table_name
  }
}

output "dynamodb_table_arns" {
  description = "ARNs of all 3 DynamoDB tables."
  value = {
    findings        = module.dynamodb.findings_table_arn
    cost_data       = module.dynamodb.cost_data_table_arn
    remediation_log = module.dynamodb.remediation_log_table_arn
  }
}

output "kms_key_arn" {
  description = "ARN of the shared CMK (alias/cloudguard-{env}). Consumed by dynamodb/s3/sns modules."
  value       = module.kms.key_arn
}

output "kms_alias_name" {
  description = "Friendly alias name for the shared CMK."
  value       = module.kms.alias_name
}

output "s3_reports_bucket_name" {
  description = "Name of the S3 reports bucket (HTML reports + CSV exports)."
  value       = module.s3.reports_bucket_name
}

output "s3_reports_bucket_arn" {
  description = "ARN of the S3 reports bucket."
  value       = module.s3.reports_bucket_arn
}

output "s3_logs_bucket_name" {
  description = "Name of the S3 access-logs bucket (receives logs from the reports bucket)."
  value       = module.s3.logs_bucket_name
}

output "sns_topic_arn" {
  description = "ARN of the CloudGuard alerts SNS topic. Consumed by Lambdas (via env var) and downstream EventBridge wiring."
  value       = module.sns.topic_arn
}

output "sns_topic_name" {
  description = "Name of the CloudGuard alerts SNS topic."
  value       = module.sns.topic_name
}

output "sns_email_subscription_arn" {
  description = "ARN of the email subscription. Stays 'pending confirmation' until the recipient clicks the AWS confirmation link."
  value       = module.sns.email_subscription_arn
}

# -----------------------------------------------------------------------------
# Lambda outputs (STEP 9)
# -----------------------------------------------------------------------------
output "lambda_function_arns" {
  description = "ARNs of all 4 CloudGuard Lambda functions. Consumed by Step Functions (STEP 16) and EventBridge (STEP 17)."
  value = {
    cost_scanner     = module.cost_scanner.function_arn
    security_scanner = module.security_scanner.function_arn
    resource_cleanup = module.resource_cleanup.function_arn
    report_generator = module.report_generator.function_arn
  }
}

output "lambda_function_names" {
  description = "Names of all 4 CloudGuard Lambda functions."
  value = {
    cost_scanner     = module.cost_scanner.function_name
    security_scanner = module.security_scanner.function_name
    resource_cleanup = module.resource_cleanup.function_name
    report_generator = module.report_generator.function_name
  }
}

output "lambda_log_group_names" {
  description = "CloudWatch log group names for all 4 Lambdas (CMK-encrypted, 30-day retention)."
  value = {
    cost_scanner     = module.cost_scanner.log_group_name
    security_scanner = module.security_scanner.log_group_name
    resource_cleanup = module.resource_cleanup.log_group_name
    report_generator = module.report_generator.log_group_name
  }
}

# -----------------------------------------------------------------------------
# Step Functions outputs (STEP 16)
# -----------------------------------------------------------------------------
output "step_functions_state_machine_arn" {
  description = "ARN of the CloudGuard state machine. Consumed by EventBridge (STEP 17) as the schedule target."
  value       = module.step_functions.state_machine_arn
}

output "step_functions_state_machine_name" {
  description = "Name of the CloudGuard state machine (e.g. cloudguard-dev-workflow)."
  value       = module.step_functions.state_machine_name
}

output "step_functions_role_arn" {
  description = "ARN of the IAM role assumed by Step Functions."
  value       = module.step_functions.role_arn
}

output "step_functions_log_group_name" {
  description = "CloudWatch log group receiving SFN execution logs (CMK-encrypted, 30-day retention)."
  value       = module.step_functions.log_group_name
}