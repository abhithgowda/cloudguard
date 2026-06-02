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

# -----------------------------------------------------------------------------
# Tagging strategy (STEP 24)
#
# Owner + CostCenter complete the 5-tag universal set (Project, Environment,
# ManagedBy are set inline in the provider default_tags block). They live as
# variables so prod can override the owner/cost-center without touching the
# provider block, and so the values stay out of any hardcoded module internals.
# Values are plain hyphenated ASCII — IAM/S3/SNS tag validators reject em-dashes
# and (SNS) commas, a lesson from STEP 18.
# -----------------------------------------------------------------------------
variable "owner" {
  description = "Owner tag applied to every resource via default_tags. The person/team accountable for the resource — surfaces in Cost Explorer and resource inventory."
  type        = string
  default     = "abhith-bn"
}

variable "cost_center" {
  description = "CostCenter tag applied to every resource via default_tags. Used for cost-allocation grouping in Cost Explorer / Cost & Usage Reports once activated as a cost-allocation tag."
  type        = string
  default     = "devops"
}

variable "alert_email" {
  description = "Email address for SNS alert subscriptions (cost anomalies, security findings)"
  type        = string
  # No default — must be supplied in terraform.tfvars (gitignored)
}

variable "ses_sender_email" {
  description = "SES sender identity for report emails. Must be a verified identity in SES (one-click verification). Defaults to alert_email so a single click verifies both ends; override only if the sender domain differs from the alert recipient."
  type        = string
  default     = ""
}

variable "report_window_hours" {
  description = "Default report window in hours (EventBridge target inputs can override per-invocation). 24 = daily digest, 168 = weekly."
  type        = number
  default     = 24

  validation {
    condition     = var.report_window_hours > 0 && var.report_window_hours <= 720
    error_message = "report_window_hours must be between 1 and 720 (30 days)."
  }
}

variable "github_org" {
  description = "GitHub org or user that owns the cloudguard repo. Used by the github_oidc module to scope the trust policy of the plan + deploy roles."
  type        = string
  default     = "abhithcogni"
}

variable "github_repo" {
  description = "GitHub repository name. Used by the github_oidc module's trust policy `sub` condition."
  type        = string
  default     = "cloudguard"
}

variable "state_bucket_name" {
  description = "Name of the S3 bucket holding the Terraform remote state for this environment. Passed to the github_oidc module so the plan role can acquire S3 native locks."
  type        = string
  default     = "cloudguard-tf-state-abhithcogni"
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
