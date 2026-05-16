# =============================================================================
# outputs.tf — S3 module outputs
# =============================================================================

output "reports_bucket_name" {
  description = "Name of the CloudGuard reports bucket."
  value       = aws_s3_bucket.reports.id
}

output "reports_bucket_arn" {
  description = "ARN of the CloudGuard reports bucket. Consumed by the report_generator Lambda env vars and (in dev/main.tf) reused to build the IAM resource ARN."
  value       = aws_s3_bucket.reports.arn
}

output "reports_bucket_domain_name" {
  description = "Regional domain name of the reports bucket — useful for constructing pre-signed URLs in the report_generator Lambda."
  value       = aws_s3_bucket.reports.bucket_regional_domain_name
}

output "logs_bucket_name" {
  description = "Name of the S3 access-logs bucket (receives logs from the reports bucket)."
  value       = aws_s3_bucket.logs.id
}

output "logs_bucket_arn" {
  description = "ARN of the access-logs bucket."
  value       = aws_s3_bucket.logs.arn
}