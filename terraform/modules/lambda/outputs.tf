# =============================================================================
# outputs.tf — Reusable Lambda module outputs (STEP 9)
#
# Consumed by:
#   - terraform/environments/dev/outputs.tf (surface to operators)
#   - step-functions module (STEP 16: function ARNs become Task Resource fields)
#   - eventbridge module (STEP 17: report_generator ARN is a target)
# =============================================================================

output "function_arn" {
  description = "ARN of the Lambda function. Used by Step Functions Task states and EventBridge targets."
  value       = aws_lambda_function.this.arn
}

output "function_name" {
  description = "Lambda function name (matches var.function_name)."
  value       = aws_lambda_function.this.function_name
}

output "function_invoke_arn" {
  description = "Lambda invoke ARN (the apigateway-friendly form). Useful if we ever front a function with API Gateway."
  value       = aws_lambda_function.this.invoke_arn
}

output "log_group_name" {
  description = "CloudWatch log group name (/aws/lambda/<function_name>)."
  value       = aws_cloudwatch_log_group.lambda.name
}

output "log_group_arn" {
  description = "CloudWatch log group ARN."
  value       = aws_cloudwatch_log_group.lambda.arn
}

output "source_code_hash" {
  description = "Base64-encoded SHA256 of the zipped source. Changes whenever any file in source_dir changes — handy for verifying a deploy actually shipped new code."
  value       = aws_lambda_function.this.source_code_hash
}