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

# -----------------------------------------------------------------------------
# EventBridge outputs (STEP 17)
# -----------------------------------------------------------------------------
output "eventbridge_rule_names" {
  description = "Names of all 3 EventBridge rules: periodic scan + daily + weekly report."
  value = {
    scan_schedule = module.eventbridge.scan_rule_name
    daily_report  = module.eventbridge.daily_report_rule_name
    weekly_report = module.eventbridge.weekly_report_rule_name
  }
}

output "eventbridge_rule_arns" {
  description = "ARNs of all 3 EventBridge rules."
  value = {
    scan_schedule = module.eventbridge.scan_rule_arn
    daily_report  = module.eventbridge.daily_report_rule_arn
    weekly_report = module.eventbridge.weekly_report_rule_arn
  }
}

output "eventbridge_role_arn" {
  description = "ARN of the IAM role EventBridge assumes to start Step Functions executions."
  value       = module.eventbridge.role_arn
}

# -----------------------------------------------------------------------------
# GitHub Actions OIDC outputs (STEP 21)
#
# After `terraform apply`, paste these ARNs into GitHub:
#   Repo Settings → Secrets and variables → Actions → Variables tab:
#     AWS_PLAN_ROLE_ARN   = <plan_role_arn output>
#     AWS_DEPLOY_ROLE_ARN = <deploy_role_arn output>
#   AWS_REGION = "ap-south-1"  (or hardcode in the workflows — your call)
#
# These are VARIABLES not SECRETS — role ARNs are not sensitive; the security
# boundary is the trust policy, not the ARN itself.
# -----------------------------------------------------------------------------
output "github_oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider in this AWS account."
  value       = module.github_oidc.oidc_provider_arn
}

output "github_plan_role_arn" {
  description = "Role for CI: terraform plan + ReadOnlyAccess + state-bucket write. Set as AWS_PLAN_ROLE_ARN in GitHub repo variables."
  value       = module.github_oidc.plan_role_arn
}

output "github_deploy_role_arn" {
  description = "Role for deploy: terraform apply + AdministratorAccess. Assumable ONLY from the main branch via the trust policy. Set as AWS_DEPLOY_ROLE_ARN in GitHub repo variables."
  value       = module.github_oidc.deploy_role_arn
}

# -----------------------------------------------------------------------------
# Remediation approval outputs (STEP 25)
# -----------------------------------------------------------------------------
output "remediation_state_machine_arn" {
  description = "ARN of the human-in-the-loop remediation state machine. Start an execution here (console / CLI) to trigger an approval-gated cleanup."
  value       = module.remediation.state_machine_arn
}

output "remediation_api_endpoint" {
  description = "Base URL of the Approve/Reject HTTP API (STEP 25). The approval Lambda appends /approve or /reject + a signed query string."
  value       = module.remediation.api_endpoint
}

output "remediation_approvals_table_name" {
  description = "Name of the approvals DynamoDB table (approval_id → task token, TTL-purged)."
  value       = module.remediation.approvals_table_name
}

output "remediation_approval_lambda_name" {
  description = "Name of the remediation approval Lambda (notify + callback)."
  value       = module.remediation_approval.function_name
}

# -----------------------------------------------------------------------------
# CloudWatch outputs (STEP 22)
# -----------------------------------------------------------------------------
output "cloudwatch_dashboard_name" {
  description = "Name of the CloudWatch dashboard. Console → CloudWatch → Dashboards → cloudguard-dev."
  value       = module.cloudwatch.dashboard_name
}

output "cloudwatch_alarm_names" {
  description = "All CloudWatch alarm names created in STEP 22: per-Lambda error-rate + duration, plus the SFN failure alarm."
  value = {
    error_rate  = module.cloudwatch.error_rate_alarm_names
    duration    = module.cloudwatch.duration_alarm_names
    sfn_failure = module.cloudwatch.sfn_failure_alarm_name
  }
}