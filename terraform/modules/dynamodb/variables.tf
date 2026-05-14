variable "project" {
  description = "Project name used as a naming prefix for all resources."
  type        = string
  default     = "cloudguard"
}

variable "environment" {
  description = "Deployment environment (dev, prod)."
  type        = string
}
