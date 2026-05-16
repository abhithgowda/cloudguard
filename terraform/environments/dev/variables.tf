# =============================================================================
# variables.tf — Input variables for the dev environment
# =============================================================================

variable "aws_region" {
  description = "AWS region to deploy resources into"
  type        = string
  default     = "ap-south-1"
}

variable "environment" {
  description = "Deployment environment name (dev / prod)"
  type        = string
  default     = "dev"
}

variable "project" {
  description = "Project name — used as a prefix on all resource names and tags"
  type        = string
  default     = "cloudguard"
}

variable "alert_email" {
  description = "Email address for SNS alert subscriptions (cost anomalies, security findings)"
  type        = string
  # No default — must be supplied in terraform.tfvars (gitignored)
}

variable "bucket_suffix" {
  description = "Globally-unique suffix appended to S3 bucket names. S3 bucket names share one namespace across every AWS account on Earth — without a suffix, 'cloudguard-dev-reports' would collide with anyone else who picked the same name. Set this in the gitignored terraform.tfvars (e.g. your GitHub handle) so it stays out of source control."
  type        = string
  # No default — must be supplied in terraform.tfvars (gitignored)

  validation {
    condition     = can(regex("^[a-z0-9-]{3,30}$", var.bucket_suffix))
    error_message = "bucket_suffix must be 3-30 chars, lowercase letters, digits, and hyphens only (S3 bucket naming rules)."
  }
}
