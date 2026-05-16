# =============================================================================
# main.tf — Reusable Lambda module (STEP 9)
#
# One module call per Lambda function. Produces:
#   1. a zip of var.source_dir via the archive_file data source (re-hashed at
#      plan time when any source file changes — drives function code updates),
#   2. a CloudWatch Log Group, declared explicitly so retention and KMS
#      encryption can be set (Lambda's auto-created log group has neither),
#   3. the Lambda function itself, with env vars + log group + tracing
#      configured; depends_on the log group so Lambda's first invocation
#      cannot race-create an unmanaged group with default retention.
#
# Encryption design (STEP 9 retrofit to KMS module):
#   - aws_lambda_function.kms_key_arn → encrypts env vars at rest. The
#     execution role's grant in the key policy uses kms:ViaService = lambda.*.
#   - aws_cloudwatch_log_group.kms_key_id → encrypts log events at rest.
#     The CloudWatch Logs service principal's grant in the key policy is
#     scoped by kms:EncryptionContext:aws:logs:arn to the CloudGuard log
#     group ARN pattern in this env.
# =============================================================================

# -----------------------------------------------------------------------------
# Source archive
#
# archive_file is evaluated at plan time. The zip is written under the module's
# build dir (gitignored) and re-created whenever any file under source_dir
# changes — Lambda gets a new source_code_hash and AWS deploys the new bundle.
# -----------------------------------------------------------------------------
data "archive_file" "source" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.module}/.builds/${var.function_name}.zip"
}

# -----------------------------------------------------------------------------
# CloudWatch Log Group
#
# Declared BEFORE the function so Lambda's first invocation doesn't auto-create
# an unmanaged group with no retention and no encryption (the AWS default).
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = {
    Function = var.function_name
  }
}

# -----------------------------------------------------------------------------
# The function
#
# depends_on the log group: without this, the very first apply would create
# the function, the function would run, CloudWatch Logs would auto-create
# the log group with no retention, and the next apply would fail trying to
# create a log group that already exists.
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "this" {
  function_name = var.function_name
  role          = var.role_arn
  handler       = var.handler
  runtime       = var.runtime

  filename         = data.archive_file.source.output_path
  source_code_hash = data.archive_file.source.output_base64sha256

  timeout                        = var.timeout
  memory_size                    = var.memory_size
  reserved_concurrent_executions = var.reserved_concurrent_executions
  layers                         = var.layers
  kms_key_arn                    = var.kms_key_arn

  tracing_config {
    mode = var.tracing_mode
  }

  # AWS only encrypts env vars with the CMK if at least one variable is set.
  # Passing an empty map removes the block entirely; dynamic block keeps the
  # module call ergonomic when a function happens to have no env vars.
  dynamic "environment" {
    for_each = length(var.environment_variables) > 0 ? [1] : []
    content {
      variables = var.environment_variables
    }
  }

  tags = {
    Function = var.function_name
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}