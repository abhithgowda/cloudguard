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
