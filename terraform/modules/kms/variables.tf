variable "project" {
  description = "Project name used as a naming prefix (e.g. cloudguard)."
  type        = string
  default     = "cloudguard"
}

variable "environment" {
  description = "Deployment environment (dev, prod). Drives the alias suffix."
  type        = string
}

variable "lambda_role_arns" {
  description = <<-EOT
    ARNs of the Lambda execution roles that need to use this CMK.
    Pass the 4 role ARNs from the iam module. Each ARN gets Encrypt/Decrypt/
    ReEncrypt*/GenerateDataKey*/DescribeKey, scoped via kms:ViaService to
    DynamoDB, S3, and SNS in the current region.
  EOT
  type        = list(string)
}
