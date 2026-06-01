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

variable "github_actions_role_arns" {
  description = <<-EOT
    ARNs of the GitHub Actions OIDC roles that need to manage CMK-encrypted
    Lambda environment variables. Pass the github_plan and github_deploy role
    ARNs from the github_oidc module.

    Why this is needed (STEP 21 hotfix): Terraform's plan refresh phase
    decrypts each Lambda's env vars to compare with config. The deploy phase
    re-encrypts them when applying. Both operations need kms:ViaService=lambda
    on this CMK. Without these grants, CI plan shows all env vars as drift
    (silent Decrypt AccessDenied returns empty variables) and deploy apply
    fails with explicit Encrypt AccessDenied.

    Scoped via kms:ViaService = lambda.<region>.amazonaws.com — these roles
    CANNOT use the CMK to read DynamoDB rows or decrypt S3 objects directly.
    Empty list disables the grant entirely (for envs that don't use OIDC CI).
  EOT
  type        = list(string)
  default     = []
}

variable "cloudwatch_alarms_enabled" {
  description = <<-EOT
    When true, add a key-policy statement granting the CloudWatch service
    principal kms:Decrypt + kms:GenerateDataKey* on this CMK, scoped via
    kms:ViaService = sns.<region>.amazonaws.com.

    Required because the alerts SNS topic is encrypted with this CMK. When a
    CloudWatch alarm publishes to that topic, SNS calls GenerateDataKey with
    cloudwatch.amazonaws.com as the principal — and the key policy must grant
    it, or the publish fails and the notification is silently dropped (the
    classic "my alarm never emailed me" gotcha). The ViaService condition
    confines CloudWatch to using this key ONLY through SNS — it cannot decrypt
    DynamoDB rows or S3 objects. Default false; dev sets it true in STEP 22.
  EOT
  type        = bool
  default     = false
}
