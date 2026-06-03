# =============================================================================
# main.tf — Remediation Approval module (STEP 25, post-DoD stretch)
#
# Human-in-the-loop layer on top of the resource_cleanup destructive path. This
# is a SEPARATE, manually-triggered state machine — the live 6-hourly scan
# workflow (modules/step-functions) is untouched, so nothing running breaks.
#
# Flow:
#   DetectZombies (cleanup Lambda, mode="detect")  → returns the zombie list
#     │
#   AnyZombies?  (Choice)
#     ├─ 0 found → NoZombies (terminal)
#     └─ >0      → RequestApproval
#                    Resource = ...:lambda:invoke.waitForTaskToken
#                    → approval Lambda emails signed Approve/Reject links,
#                      execution PAUSES on the task token (TimeoutSeconds caps it)
#                        ├─ SendTaskSuccess  → DeleteApproved (cleanup, mode="remediate")
#                        ├─ SendTaskFailure  → RemediationRejected (terminal)
#                        └─ States.Timeout   → ApprovalTimedOut (terminal, no delete)
#
# Why STANDARD + waitForTaskToken (the canonical "why Step Functions over
# SNS/SQS chaining" answer): a paused execution costs nothing (you pay per state
# transition, not wall-clock), survives up to a year, and is fully visible in
# the console with input/output history. Rebuilding this on SNS/SQS means
# hand-rolling a token store + a state machine on DynamoDB — exactly what SFN
# gives you for free.
#
# Link security (decision 3b): the email links carry an opaque approval_id +
# HMAC signature + expiry, NOT the raw task token. The token lives server-side
# in the approvals table; the callback Lambda verifies the signature and looks
# it up. Single-use, expiring, unforgeable without the SSM-held secret.
# =============================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  name_prefix          = "${var.project}-${var.environment}"
  state_machine_name   = "${local.name_prefix}-remediation"
  sfn_role_name        = "${local.name_prefix}-remediation-sfn-role"
  approvals_table_name = "${local.name_prefix}-approvals"
  hmac_param_name      = "/${var.project}/${var.environment}/remediation/hmac-secret"
  log_group_name       = "/aws/vendedlogs/states/${local.state_machine_name}-Logs"
}

# =============================================================================
# HMAC signing key — random, stored as an SSM SecureString.
#
# Encrypted with the AWS-managed alias/aws/ssm key (the SecureString default),
# NOT the shared CMK: that keeps the CMK key policy free of an ssm:ViaService
# grant. The secret never appears in the Lambda's environment or in git — only
# in (encrypted) Terraform state and SSM. SSM SecureString over a Lambda env
# var so the key can be rotated without redeploying the function.
# =============================================================================
resource "random_password" "hmac" {
  length  = 64
  special = false # alphanumeric — used as an HMAC key, no need for symbols
}

resource "aws_ssm_parameter" "hmac_secret" {
  name        = local.hmac_param_name
  description = "CloudGuard ${var.environment} remediation-approval HMAC signing key (STEP 25)."
  type        = "SecureString"
  value       = random_password.hmac.result

  tags = merge(var.tags, { Name = local.hmac_param_name })
}

# =============================================================================
# Approvals table — maps the opaque approval_id (in the email link) to the real
# Step Functions task token (kept server-side). TTL auto-purges decided/expired
# rows. Encrypted with the shared CMK like the other 3 tables.
# =============================================================================
resource "aws_dynamodb_table" "approvals" {
  name         = local.approvals_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "approval_id"

  tags = merge(var.tags, { Name = local.approvals_table_name })

  attribute {
    name = "approval_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }
}

# =============================================================================
# HTTP API (chosen over REST): two GET routes a human hits from an email link.
# Cheaper, lower-latency, simpler than REST — and we don't need REST's
# authorizer/usage-plan ecosystem because auth is HMAC-in-Lambda (decision 3b).
# =============================================================================
resource "aws_apigatewayv2_api" "this" {
  name          = "${local.name_prefix}-remediation-approval"
  protocol_type = "HTTP"
  description   = "CloudGuard ${var.environment} remediation Approve/Reject callback (STEP 25)."

  tags = merge(var.tags, { Name = "${local.name_prefix}-remediation-approval" })
}

resource "aws_apigatewayv2_integration" "approval" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.approval_lambda_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "approve" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "GET /approve"
  target    = "integrations/${aws_apigatewayv2_integration.approval.id}"
}

resource "aws_apigatewayv2_route" "reject" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "GET /reject"
  target    = "integrations/${aws_apigatewayv2_integration.approval.id}"
}

# $default stage with auto-deploy: the api_endpoint resolves at the root (no
# stage path segment), so the email link is {api_endpoint}/approve?... .
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  tags = merge(var.tags, { Name = "${local.name_prefix}-remediation-approval-stage" })
}

# Resource-based permission: only THIS API may invoke the approval Lambda.
# source_arn scopes it to this API's execution ARN (any stage/route under it).
resource "aws_lambda_permission" "apigw_invoke" {
  statement_id  = "AllowRemediationApiInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.approval_lambda_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

# =============================================================================
# Step Functions execution role — invoke the cleanup + approval Lambdas,
# deliver execution logs, emit X-Ray segments.
# =============================================================================
resource "aws_iam_role" "sfn" {
  name        = local.sfn_role_name
  description = "Role for CloudGuard ${var.environment} remediation state machine - invokes cleanup + approval Lambdas."

  tags = merge(var.tags, { Name = local.sfn_role_name })

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_invoke" {
  name = "${local.sfn_role_name}-lambda-invoke"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "InvokeRemediationLambdas"
      Effect = "Allow"
      Action = ["lambda:InvokeFunction"]
      Resource = [
        var.cleanup_lambda_arn,
        "${var.cleanup_lambda_arn}:*",
        var.approval_lambda_arn,
        "${var.approval_lambda_arn}:*",
      ]
    }]
  })
}

# Vended-logs delivery — same account-scoped APIs as the scan workflow's SFN
# role; these don't support resource-level perms (AWS-documented Resource="*").
resource "aws_iam_role_policy" "logs_delivery" {
  name = "${local.sfn_role_name}-logs-delivery"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "VendedLogsDelivery"
      Effect = "Allow"
      Action = [
        "logs:CreateLogDelivery",
        "logs:GetLogDelivery",
        "logs:UpdateLogDelivery",
        "logs:DeleteLogDelivery",
        "logs:ListLogDeliveries",
        "logs:PutResourcePolicy",
        "logs:DescribeResourcePolicies",
        "logs:DescribeLogGroups",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "xray" {
  count = var.tracing_enabled ? 1 : 0

  name = "${local.sfn_role_name}-xray"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "XRayTracing"
      Effect = "Allow"
      Action = [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets",
      ]
      Resource = "*"
    }]
  })
}

# =============================================================================
# Execution log group (CMK-encrypted). The shared CMK's AllowCloudWatchLogsEncrypt
# Sid already covers the /aws/vendedlogs/states/<project>-<env>-* pattern
# (STEP 16 retrofit), so this name is in scope without a key-policy change.
# =============================================================================
resource "aws_cloudwatch_log_group" "sfn" {
  name              = local.log_group_name
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = merge(var.tags, { StateMachine = local.state_machine_name })
}

# =============================================================================
# The remediation state machine.
# =============================================================================
locals {
  asl_definition = jsonencode({
    Comment = "CloudGuard ${var.environment} human-in-the-loop remediation (STEP 25). Detect → approve via email → delete; pauses on a task token while awaiting the operator."
    StartAt = "DetectZombies"
    States = {
      # 1) Detect-only invocation of the cleanup Lambda. Returns the zombie list.
      DetectZombies = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.cleanup_lambda_arn
          Payload      = { mode = "detect" }
        }
        ResultSelector = {
          "resources.$"      = "$.Payload.resources"
          "resource_count.$" = "$.Payload.resource_count"
          "savings.$"        = "$.Payload.estimated_monthly_savings_usd"
        }
        ResultPath = "$.detect"
        Retry = [{
          ErrorEquals     = ["States.ALL"]
          MaxAttempts     = var.task_retry_max_attempts
          BackoffRate     = var.task_retry_backoff_rate
          IntervalSeconds = 1
        }]
        Next = "AnyZombies"
      }

      # 2) Short-circuit when there's nothing to approve.
      AnyZombies = {
        Type = "Choice"
        Choices = [{
          Variable          = "$.detect.resource_count"
          NumericGreaterThan = 0
          Next              = "RequestApproval"
        }]
        Default = "NoZombies"
      }

      NoZombies = {
        Type   = "Pass"
        Result = { status = "NO_ZOMBIES" }
        End    = true
      }

      # 3) Pause on a task token while the approval Lambda emails the operator.
      RequestApproval = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke.waitForTaskToken"
        Parameters = {
          FunctionName = var.approval_lambda_arn
          Payload = {
            "taskToken.$"      = "$$.Task.Token"
            "resources.$"      = "$.detect.resources"
            "executionName.$"  = "$$.Execution.Name"
            apiBaseUrl         = aws_apigatewayv2_api.this.api_endpoint
          }
        }
        TimeoutSeconds = var.approval_timeout_seconds
        ResultPath     = "$.approval"
        Catch = [
          {
            ErrorEquals = ["States.Timeout"]
            Next        = "ApprovalTimedOut"
            ResultPath  = "$.error"
          },
          {
            ErrorEquals = ["RemediationRejected"]
            Next        = "RemediationRejected"
            ResultPath  = "$.error"
          },
          {
            ErrorEquals = ["States.ALL"]
            Next        = "ApprovalFailed"
            ResultPath  = "$.error"
          },
        ]
        Next = "DeleteApproved"
      }

      # 4) Approved → delete the EXACT approved list (no re-detection).
      DeleteApproved = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.cleanup_lambda_arn
          Payload = {
            mode             = "remediate"
            auto_remediate   = true
            "resources.$"    = "$.detect.resources"
          }
        }
        ResultPath = "$.remediation"
        Retry = [{
          ErrorEquals     = ["States.ALL"]
          MaxAttempts     = var.task_retry_max_attempts
          BackoffRate     = var.task_retry_backoff_rate
          IntervalSeconds = 1
        }]
        End = true
      }

      # Rejected / timed out are clean terminals — NO deletion happened.
      RemediationRejected = {
        Type   = "Pass"
        Result = { status = "REJECTED" }
        End    = true
      }

      ApprovalTimedOut = {
        Type   = "Pass"
        Result = { status = "TIMED_OUT" }
        End    = true
      }

      # An unexpected approval-task error (e.g. the SES send raised) is a real
      # failure — surface it rather than silently succeeding.
      ApprovalFailed = {
        Type  = "Fail"
        Error = "ApprovalFailed"
        Cause = "The approval task failed unexpectedly (see execution history)."
      }
    }
  })
}

resource "aws_sfn_state_machine" "this" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = local.asl_definition

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = var.include_execution_data
    level                  = var.logging_level
  }

  tracing_configuration {
    enabled = var.tracing_enabled
  }

  tags = merge(var.tags, { Name = local.state_machine_name })

  depends_on = [
    aws_iam_role_policy.lambda_invoke,
    aws_iam_role_policy.logs_delivery,
    aws_iam_role_policy.xray,
  ]
}
