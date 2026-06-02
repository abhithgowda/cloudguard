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

variable "ses_sender_email" {
  description = "The verified SES sender identity the report-generator Lambda is allowed to send AS (STEP 18.5 hardening). The report_generator role's ses:SendEmail grant is scoped to this identity's ARN and gated by a ses:FromAddress Condition, so a compromised role cannot send mail from any other verified identity in the account. Caller passes local.ses_sender_email (which falls back to alert_email)."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.ses_sender_email))
    error_message = "ses_sender_email must be a single valid email address (it becomes both the SES identity ARN and the ses:FromAddress Condition value)."
  }
}
