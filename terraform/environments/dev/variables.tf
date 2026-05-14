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
