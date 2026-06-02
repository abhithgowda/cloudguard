variable "project" {
  description = "Project name used as a naming prefix (e.g. cloudguard)."
  type        = string
  default     = "cloudguard"
}

variable "environment" {
  description = "Deployment environment (dev, prod). Drives the state machine name suffix."
  type        = string
}

variable "tags" {
  description = "Extra tags merged onto every taggable resource in this module, on top of the provider default_tags (STEP 24). The caller passes a Component tag for finer-grained cost allocation. Default empty keeps the module usable standalone."
  type        = map(string)
  default     = {}
}

variable "cost_scanner_arn" {
  description = "ARN of the cost_scanner Lambda function (from module.cost_scanner)."
  type        = string
}

variable "security_scanner_arn" {
  description = "ARN of the security_scanner Lambda function (from module.security_scanner)."
  type        = string
}

variable "resource_cleanup_arn" {
  description = "ARN of the resource_cleanup Lambda function (from module.resource_cleanup)."
  type        = string
}

# STEP 17.5: report_generator_arn removed — the SFN workflow no longer invokes
# the report Lambda. Reports are EventBridge-scheduled separately (STEP 17).

variable "kms_key_arn" {
  description = <<-EOT
    ARN of the shared CMK (from module.kms.key_arn). Used to encrypt the
    Step Functions execution log group. The KMS key policy's
    AllowCloudWatchLogsEncrypt Sid must include the SFN log group ARN pattern
    in its kms:EncryptionContext condition — handled by the STEP 16 retrofit
    to the kms module.
  EOT
  type        = string
}

variable "log_retention_days" {
  description = "Retention for the Step Functions execution log group. Matches the Lambda module default."
  type        = number
  default     = 30

  validation {
    condition = contains(
      [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653],
      var.log_retention_days,
    )
    error_message = "log_retention_days must be one of CloudWatch's allowed values (1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653)."
  }
}

variable "logging_level" {
  description = <<-EOT
    Step Functions execution log level. ALL = every state transition + input/
    output (most useful for debug, free-tier safe at dev volumes). ERROR =
    only failed state transitions. OFF = no logging. Default ALL for dev; prod
    can downgrade.
  EOT
  type        = string
  default     = "ALL"

  validation {
    condition     = contains(["ALL", "ERROR", "FATAL", "OFF"], var.logging_level)
    error_message = "logging_level must be one of ALL, ERROR, FATAL, OFF."
  }
}

variable "include_execution_data" {
  description = "Whether to include state input/output in execution logs. Useful for debugging; review for PII in prod."
  type        = bool
  default     = true
}

variable "tracing_enabled" {
  description = "Enable X-Ray tracing for state machine executions. Matches Lambda tracing_mode=Active for end-to-end visibility."
  type        = bool
  default     = true
}

variable "scanner_retry_max_attempts" {
  description = "MaxAttempts on each scanner branch's Retry block. Blueprint default = 2 (3 total tries with exponential backoff)."
  type        = number
  default     = 2
}

variable "scanner_retry_backoff_rate" {
  description = "BackoffRate on each scanner branch's Retry block. Blueprint default = 2.0 (1s, 2s, 4s)."
  type        = number
  default     = 2.0
}

# STEP 17.5: report_retry_max_attempts removed — GenerateReport state is no
# longer part of the workflow.
