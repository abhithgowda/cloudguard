# =============================================================================
# variables.tf — IAM module inputs
# =============================================================================

variable "environment" {
  description = "Deployment environment (dev / prod). Used in role names so dev and prod don't collide."
  type        = string
}

variable "project" {
  description = "Project name — prefix on all role names (e.g. 'cloudguard')."
  type        = string
}

variable "reports_bucket_arn" {
  description = "ARN of the S3 reports bucket. Supplied by the caller so the bucket name (which includes a globally-unique suffix) is the source of truth in one place — the IAM policy and the S3 module agree by sharing this value rather than reconstructing it independently."
  type        = string
}
