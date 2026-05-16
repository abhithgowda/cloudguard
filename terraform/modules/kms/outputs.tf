# =============================================================================
# outputs.tf — KMS module outputs
#
# Consumed by:
#   - dynamodb module (server_side_encryption.kms_key_arn)
#   - s3 module (STEP 7: aws_s3_bucket_server_side_encryption_configuration)
#   - sns module (STEP 8: aws_sns_topic.kms_master_key_id)
# =============================================================================

output "key_arn" {
  description = "ARN of the shared CMK. Pass this to dynamodb/s3/sns modules."
  value       = aws_kms_key.main.arn
}

output "key_id" {
  description = "Key ID of the shared CMK (the UUID, not the ARN)."
  value       = aws_kms_key.main.key_id
}

output "alias_arn" {
  description = "ARN of the alias (alias/cloudguard-{env})."
  value       = aws_kms_alias.main.arn
}

output "alias_name" {
  description = "Alias name (alias/cloudguard-{env}). SNS prefers the alias name over the ARN."
  value       = aws_kms_alias.main.name
}
