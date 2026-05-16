# =============================================================================
# outputs.tf — SNS module outputs
# =============================================================================

output "topic_arn" {
  description = "ARN of the CloudGuard alerts topic. Consumed by the Lambdas (via env var) and by EventBridge dead-letter targets later."
  value       = aws_sns_topic.alerts.arn
}

output "topic_name" {
  description = "Name of the CloudGuard alerts topic."
  value       = aws_sns_topic.alerts.name
}

output "email_subscription_arn" {
  description = "ARN of the email subscription. Will be 'pending confirmation' until the recipient clicks the AWS confirmation link."
  value       = aws_sns_topic_subscription.alerts_email.arn
}