# =============================================================================
# variables.tf — Reusable Lambda module inputs (STEP 9)
#
# Same module is called 4× from dev/main.tf — once per scanner Lambda. Inputs
# are minimal so the caller doesn't have to think about CloudWatch log group
# names, archive paths, or KMS wiring.
# =============================================================================

# -----------------------------------------------------------------------------
# Naming & tagging
# -----------------------------------------------------------------------------
variable "function_name" {
  description = "Fully-qualified Lambda function name (e.g. cloudguard-dev-cost-scanner). The CloudWatch log group will be derived from this as /aws/lambda/<function_name>."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9-_]{1,64}$", var.function_name))
    error_message = "function_name must be 1-64 chars, letters/digits/hyphens/underscores only (AWS Lambda naming rules)."
  }
}

variable "project" {
  description = "Project name (cloudguard). Used for tagging only — function_name is the source of truth for naming."
  type        = string
  default     = "cloudguard"
}

variable "environment" {
  description = "Deployment environment (dev / prod). Used for tagging only."
  type        = string
}

# -----------------------------------------------------------------------------
# Runtime configuration
# -----------------------------------------------------------------------------
variable "handler" {
  description = "Lambda handler in <module>.<function> form (e.g. handler.lambda_handler)."
  type        = string
  default     = "handler.lambda_handler"
}

variable "runtime" {
  description = "Lambda runtime identifier. Pinned to python3.12 in dev/main.tf because that's what the Lambda execution environment exposes — local dev on 3.13.7 is a known mismatch (see PROGRESS.md)."
  type        = string
  default     = "python3.12"
}

variable "role_arn" {
  description = "ARN of the IAM execution role for this function (one per Lambda — from the iam module)."
  type        = string
}

variable "source_dir" {
  description = "Absolute or root-relative path to the source directory to zip. archive_file hashes the contents — any file change triggers a re-zip and a new function code SHA at plan time."
  type        = string
}

variable "environment_variables" {
  description = "Map of environment variables to inject. Encrypted at rest with the shared CMK (see kms_key_arn). Reads at function init use the role's KMS grant via lambda.<region>.amazonaws.com."
  type        = map(string)
  default     = {}
}

variable "timeout" {
  description = "Maximum execution time in seconds. 300s default — long enough for Cost Explorer pagination + DynamoDB batch writes."
  type        = number
  default     = 300

  validation {
    condition     = var.timeout >= 1 && var.timeout <= 900
    error_message = "Lambda timeout must be between 1 and 900 seconds (Lambda hard limit)."
  }
}

variable "memory_size" {
  description = "Memory in MB. 256 MB default — CPU is proportional to memory in Lambda, so this is also the CPU dial. Bump to 512+ if cold start or Cost Explorer parsing is slow."
  type        = number
  default     = 256

  validation {
    condition     = var.memory_size >= 128 && var.memory_size <= 10240 && var.memory_size % 64 == 0
    error_message = "memory_size must be 128-10240 MB in 64 MB increments (Lambda quota rules)."
  }
}

variable "layers" {
  description = "Optional list of Lambda layer ARNs (e.g. Lambda Insights, shared deps). Empty by default — we bundle everything via archive_file for STEP 9."
  type        = list(string)
  default     = []
}

# -----------------------------------------------------------------------------
# Concurrency, tracing, encryption
# -----------------------------------------------------------------------------
variable "reserved_concurrent_executions" {
  description = "Cap on concurrent executions of this function. Default 5: a misfiring EventBridge schedule cannot create a runaway bill. -1 disables the cap (Lambda's default unbounded behaviour)."
  type        = number
  default     = 5
}

variable "tracing_mode" {
  description = "X-Ray tracing mode. 'Active' captures every invocation; 'PassThrough' only when called by a traced upstream. 'Active' default — free up to 100k traces/month and gives Step Functions execution graphs a per-Lambda timeline."
  type        = string
  default     = "Active"

  validation {
    condition     = contains(["Active", "PassThrough"], var.tracing_mode)
    error_message = "tracing_mode must be 'Active' or 'PassThrough'."
  }
}

variable "kms_key_arn" {
  description = "ARN of the shared CMK from the kms module. Used to encrypt (a) the function's environment variables at rest and (b) the function's CloudWatch log group. Required — STEP 6 chose a CMK over AWS-managed precisely so audit, rotation, and revocation are under our control."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log group retention. 30 days default — long enough to debug last week's incident, short enough that log storage cost stays trivial."
  type        = number
  default     = 30
}