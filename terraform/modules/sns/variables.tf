# =============================================================================
# variables.tf — SNS module inputs
# =============================================================================

variable "project" {
  description = "Project name (e.g. cloudguard). Used in topic naming."
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, prod). Used in topic naming."
  type        = string
}

variable "kms_key_arn" {
  description = "ARN of the shared CMK used to encrypt messages at rest in the topic. Comes from the kms module."
  type        = string
}

variable "alert_email" {
  description = "Email address that receives CloudGuard alerts. AWS will send a confirmation email; the subscription stays pending until the link is clicked."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must look like a valid email address."
  }
}

variable "lambda_role_arns" {
  description = "ARNs of the Lambda execution roles allowed to Publish to the topic. Same 4 roles consumed by the kms and s3 modules."
  type        = list(string)
}

variable "cloudwatch_alarms_enabled" {
  description = <<-EOT
    When true, add a topic-policy statement allowing the CloudWatch service
    principal (cloudwatch.amazonaws.com) to sns:Publish to this topic, scoped
    via aws:SourceArn to alarms named <project>-<environment>-* in this account.

    Required because this topic's policy was deliberately locked down to root +
    the 4 Lambda roles (STEP 8) — the default "any same-account resource may
    publish" statement was removed, so without this, CloudWatch alarm
    notifications are silently dropped. Default false so the grant is opt-in;
    the dev environment sets it true in STEP 22.
  EOT
  type        = bool
  default     = false
}