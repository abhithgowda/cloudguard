output "findings_table_name" {
  description = "Name of the findings DynamoDB table."
  value       = aws_dynamodb_table.findings.name
}

output "findings_table_arn" {
  description = "ARN of the findings DynamoDB table."
  value       = aws_dynamodb_table.findings.arn
}

output "cost_data_table_name" {
  description = "Name of the cost-data DynamoDB table."
  value       = aws_dynamodb_table.cost_data.name
}

output "cost_data_table_arn" {
  description = "ARN of the cost-data DynamoDB table."
  value       = aws_dynamodb_table.cost_data.arn
}

output "remediation_log_table_name" {
  description = "Name of the remediation-log DynamoDB table."
  value       = aws_dynamodb_table.remediation_log.name
}

output "remediation_log_table_arn" {
  description = "ARN of the remediation-log DynamoDB table."
  value       = aws_dynamodb_table.remediation_log.arn
}
