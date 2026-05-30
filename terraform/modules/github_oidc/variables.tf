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

variable "deploy_environment" {
  type        = string
  description = "GitHub Actions Environment name that may assume the deploy role. When a workflow uses `environment: <name>`, GitHub mints the OIDC token with `sub = repo:<org>/<repo>:environment:<name>` (NOT ref-based). This must match the workflow's `environment:` value."
  default     = "dev"
}

variable "deploy_branch" {
  type        = string
  description = "Branch that the workflow MUST be running on to assume the deploy role. Enforced as a second StringEquals condition on the `ref` claim — defense-in-depth alongside the GitHub Environment protection rule. Set to '' to disable the branch check (not recommended)."
  default     = "main"
}
