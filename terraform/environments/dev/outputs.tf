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