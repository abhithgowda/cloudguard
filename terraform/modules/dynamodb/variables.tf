variable "project" {
  description = "Project name used as a naming prefix for all resources."
  type        = string
  default     = "cloudguard"
}

variable "environment" {
  description = "Deployment environment (dev, prod)."
  type        = string
}

variable "kms_key_arn" {
  description = <<-EOT
    ARN of the customer-managed KMS key used for server-side encryption on all
    3 tables. Supplied by the kms module (STEP 6). Replaces the AWS-managed
    aws/dynamodb key used during STEP 5.
  EOT
  type        = string
}
