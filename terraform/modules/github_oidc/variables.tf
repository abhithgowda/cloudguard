variable "project" {
  type        = string
  description = "Project name prefix for role names."
}

variable "environment" {
  type        = string
  description = "Environment name (dev/prod) — included in role names."
}

variable "github_org" {
  type        = string
  description = "GitHub org or user that owns the repo (e.g. 'abhithcogni')."

  validation {
    condition     = length(var.github_org) > 0
    error_message = "github_org must not be empty."
  }
}

variable "github_repo" {
  type        = string
  description = "GitHub repository name (e.g. 'cloudguard')."

  validation {
    condition     = length(var.github_repo) > 0
    error_message = "github_repo must not be empty."
  }
}

variable "state_bucket_name" {
  type        = string
  description = "S3 bucket holding the Terraform remote state. The plan role gets read+write here so it can acquire the S3 native lock."
}

variable "deploy_branch" {
  type        = string
  description = "Branch name that may assume the deploy role. Anything else gets AccessDenied via the trust policy's `sub` condition."
  default     = "main"
}
