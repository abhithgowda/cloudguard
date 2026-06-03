# =============================================================================
# variables.tf — Remediation Approval module inputs (STEP 25)
# =============================================================================

variable "project" {
  description = "Project name used as a naming prefix (e.g. cloudguard)."
  type        = string
  default     = "cloudguard"
}

variable "environment" {
  description = "Deployment environment (dev, prod)."
  type        = string
}

variable "tags" {
  description = "Extra tags merged onto every taggable resource in this module, on top of the provider default_tags (STEP 24)."
  type        = map(string)
  default     = {}
}

variable "kms_key_arn" {
  description = "ARN of the shared CMK (module.kms.key_arn). Encrypts the approvals table and the SFN execution log group. The approval Lambda's role must be in the CMK's lambda_role_arns grant so it can read the CMK-encrypted table."
  type        = string
}

variable "cleanup_lambda_arn" {
  description = "ARN of the resource_cleanup Lambda — invoked twice: mode=detect, then mode=remediate after approval."
  type        = string
}

variable "approval_lambda_arn" {
  description = "ARN of the remediation_approval Lambda — the .waitForTaskToken target (notify) and the HTTP API integration (callback)."
  type        = string
}

variable "approval_lambda_name" {
  description = "Name of the remediation_approval Lambda — used by the aws_lambda_permission granting API Gateway invoke rights."
  type        = string
}

variable "approval_timeout_seconds" {
  description = "TimeoutSeconds on the .waitForTaskToken approval task. If the operator does nothing within this window the execution times out and NO resources are deleted (fail-safe). Default 86400 = 24h. Also the approvals-link / DynamoDB TTL lifetime."
  type        = number
  default     = 86400

  validation {
    condition     = var.approval_timeout_seconds >= 60 && var.approval_timeout_seconds <= 31536000
    error_message = "approval_timeout_seconds must be between 60 and 31536000 (1 year, the STANDARD workflow cap)."
  }
}

variable "task_retry_max_attempts" {
  description = "MaxAttempts on the Lambda-invoke tasks' Retry block (detect + delete). Matches the scan workflow's default of 2."
  type        = number
  default     = 2
}

variable "task_retry_backoff_rate" {
  description = "BackoffRate on the Lambda-invoke tasks' Retry block."
  type        = number
  default     = 2.0
}

variable "log_retention_days" {
  description = "Retention for the SFN execution log group."
  type        = number
  default     = 30

  validation {
    condition = contains(
      [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653],
      var.log_retention_days,
    )
    error_message = "log_retention_days must be one of CloudWatch's allowed values."
  }
}

variable "logging_level" {
  description = "Step Functions execution log level (ALL / ERROR / FATAL / OFF)."
  type        = string
  default     = "ALL"

  validation {
    condition     = contains(["ALL", "ERROR", "FATAL", "OFF"], var.logging_level)
    error_message = "logging_level must be one of ALL, ERROR, FATAL, OFF."
  }
}

variable "include_execution_data" {
  description = "Include state input/output in execution logs. Note: input/output here can contain the resource list (no secrets — the task token is logged by SFN itself, not echoed in our payloads)."
  type        = bool
  default     = true
}

variable "tracing_enabled" {
  description = "Enable X-Ray tracing for the remediation state machine."
  type        = bool
  default     = true
}
