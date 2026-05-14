# =============================================================================
# outputs.tf — IAM module outputs
#
# These role ARNs are consumed by the Lambda module (STEP 8) when it creates
# the actual Lambda functions and needs to attach an execution role to each.
# =============================================================================

output "cost_scanner_role_arn" {
  description = "ARN of the IAM role for the cost scanner Lambda."
  value       = aws_iam_role.cost_scanner.arn
}

output "security_scanner_role_arn" {
  description = "ARN of the IAM role for the security scanner Lambda."
  value       = aws_iam_role.security_scanner.arn
}

output "resource_cleanup_role_arn" {
  description = "ARN of the IAM role for the resource cleanup Lambda."
  value       = aws_iam_role.resource_cleanup.arn
}

output "report_generator_role_arn" {
  description = "ARN of the IAM role for the report generator Lambda."
  value       = aws_iam_role.report_generator.arn
}

# Role NAMES exported too — useful for IAM policy attachments and CloudTrail
# searches where the name is more readable than the ARN.
output "cost_scanner_role_name" {
  description = "Name of the cost scanner IAM role."
  value       = aws_iam_role.cost_scanner.name
}

output "security_scanner_role_name" {
  description = "Name of the security scanner IAM role."
  value       = aws_iam_role.security_scanner.name
}

output "resource_cleanup_role_name" {
  description = "Name of the resource cleanup IAM role."
  value       = aws_iam_role.resource_cleanup.name
}

output "report_generator_role_name" {
  description = "Name of the report generator IAM role."
  value       = aws_iam_role.report_generator.name
}
