# =============================================================================
# variables.tf — S3 module inputs
# =============================================================================

variable "project" {
  description = "Project name — prefix on bucket names and tags (e.g. 'cloudguard')."
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev / prod). Part of the bucket name."
  type        = string
}

variable "reports_bucket_name" {
  description = "Globally-unique name for the reports bucket. Constructed by the caller (typically '$${project}-$${environment}-reports-$${suffix}') so the IAM module and the S3 module agree on the same string from one source of truth."
  type        = string
}

variable "kms_key_arn" {
  description = "ARN of the customer-managed KMS key (CMK) used for SSE-KMS encryption of the reports bucket. The logs bucket is intentionally SSE-S3 (AES256) — see main.tf for the reasoning."
  type        = string
}

variable "lambda_role_arns" {
  description = "List of Lambda execution role ARNs allowed to write to the reports bucket. The bucket policy restricts s3:PutObject to exactly these principals — no other identity can write reports, even if their IAM policy says they can."
  type        = list(string)
}