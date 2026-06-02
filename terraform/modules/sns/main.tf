# =============================================================================
# main.tf — SNS module (STEP 8)
#
# Single fan-out topic for every CloudGuard alert. Subscribers (email today,
# Slack/SMS/Lambda later) attach to this one topic; producers (the 4 Lambdas)
# Publish to this one topic. Message-attribute filtering can route by severity
# at the subscription level later without a re-architecture.
#
# Why a single topic, not one per severity / one per category:
#   - Fan-out is SNS's native model — adding a CRITICAL-only subscriber later
#     means a FilterPolicy on that subscription, not a second topic.
#   - One ARN to wire into 4 Lambda IAM policies (it already is — see
#     terraform/modules/iam/main.tf, `local.alerts_topic_arn`).
#
# Encryption:
#   SSE on the topic with the shared CMK (module.kms.key_arn). The KMS key
#   policy already has an `AllowLambdasViaSNS` Sid (kms:ViaService scoped to
#   sns.<region>.amazonaws.com) — no KMS policy change required here.
# =============================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  topic_name = "${var.project}-${var.environment}-alerts"

  # CloudWatch alarms created by the cloudwatch module (STEP 22) are named
  # <project>-<environment>-*. Scoping the CloudWatch publish grant by this
  # aws:SourceArn pattern means only OUR alarms can publish via the service
  # principal — not any alarm anyone creates in the account.
  alarm_arn_pattern = "arn:aws:cloudwatch:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:alarm:${var.project}-${var.environment}-*"
}

# =============================================================================
# Topic
# =============================================================================
resource "aws_sns_topic" "alerts" {
  name              = local.topic_name
  kms_master_key_id = var.kms_key_arn

  tags = merge(var.tags, {
    Name    = local.topic_name
    Purpose = "CloudGuard alert fan-out for cost / security / cleanup / report-generator notifications"
  })
}

# =============================================================================
# Email subscription
#
# AWS sends a confirmation email to var.alert_email when this resource is
# created; the subscription stays in `PendingConfirmation` until the recipient
# clicks the link. Terraform CANNOT confirm the subscription — that's a manual
# step by design, so an attacker who steals Terraform credentials can't
# silently subscribe a victim's inbox.
#
# `confirmation_timeout_in_minutes` is not relevant for email (it applies to
# HTTPS endpoints). For email, the link in the AWS confirmation email is valid
# for 3 days.
# =============================================================================
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# =============================================================================
# Topic policy
#
# Same defense-in-depth pattern as the S3 reports bucket policy:
#   - Explicit Deny on non-TLS (aws:SecureTransport = false) — Checkov item,
#     and an uncircumventable floor against plaintext Publish/Subscribe.
#   - Explicit Allow for the 4 Lambda role ARNs to sns:Publish. Listed by
#     ARN, no wildcards — the audit is one `cat` away.
#   - Account-root admin so the topic policy can never lock itself out.
#
# Identity-policy + resource-policy is ANDed for cross-service principals,
# so a leaked credential outside those 4 roles is rejected at the topic even
# if its IAM policy says otherwise.
# =============================================================================
data "aws_iam_policy_document" "topic_policy" {
  # ---------------------------------------------------------------------------
  # Root-account admin — same reasoning as the KMS key policy: an SNS topic
  # policy that omits root can lock you out of modifying the topic via the
  # console / API. Terraform itself runs as an IAM principal; this statement
  # guarantees the account owner always retains control.
  # ---------------------------------------------------------------------------
  statement {
    sid    = "EnableRootAccountAdmin"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    # SNS rejects "sns:*" in topic policies ("Policy statement action out of
    # service scope!") because the wildcard expands to include account-level
    # actions like sns:CreateTopic / sns:ListTopics that aren't topic-scoped.
    # Enumerate the topic-scoped actions explicitly. This is the full list of
    # actions that operate against a topic ARN (AWS SNS API reference, 2026).
    actions = [
      "sns:AddPermission",
      "sns:DeleteTopic",
      "sns:GetDataProtectionPolicy",
      "sns:GetTopicAttributes",
      "sns:ListSubscriptionsByTopic",
      "sns:ListTagsForResource",
      "sns:Publish",
      "sns:PutDataProtectionPolicy",
      "sns:RemovePermission",
      "sns:SetTopicAttributes",
      "sns:Subscribe",
      "sns:TagResource",
      "sns:UntagResource",
    ]
    resources = [aws_sns_topic.alerts.arn]
  }

  # ---------------------------------------------------------------------------
  # Deny insecure transport. SNS endpoints already speak TLS by default; this
  # is the explicit floor that ensures a misconfigured client cannot Publish
  # over HTTP.
  # ---------------------------------------------------------------------------
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["sns:Publish", "sns:Subscribe"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    resources = [aws_sns_topic.alerts.arn]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # ---------------------------------------------------------------------------
  # Allow the 4 Lambda execution roles to Publish. The IAM module already
  # grants sns:Publish on this exact ARN to cost_scanner, security_scanner,
  # resource_cleanup, and report_generator (see terraform/modules/iam/main.tf,
  # `local.alerts_topic_arn`). This statement is the resource-side half of
  # the AND.
  # ---------------------------------------------------------------------------
  statement {
    sid    = "AllowLambdaRolesPublish"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = var.lambda_role_arns
    }

    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }

  # ---------------------------------------------------------------------------
  # Allow CloudWatch alarms to Publish (STEP 22).
  #
  # The CloudWatch service publishes alarm notifications as the
  # cloudwatch.amazonaws.com service principal — NOT as one of the Lambda roles
  # and NOT as the account root. The locked-down policy above grants neither,
  # so without this statement an alarm transition is silently dropped.
  #
  # Scoped two ways: the principal is only the CloudWatch service, and
  # aws:SourceArn pins it to alarms named <project>-<environment>-* in this
  # account — so an unrelated alarm elsewhere in the account cannot use this
  # topic as its action target. Gated by var.cloudwatch_alarms_enabled.
  # ---------------------------------------------------------------------------
  dynamic "statement" {
    for_each = var.cloudwatch_alarms_enabled ? [1] : []
    content {
      sid    = "AllowCloudWatchAlarmsPublish"
      effect = "Allow"

      principals {
        type        = "Service"
        identifiers = ["cloudwatch.amazonaws.com"]
      }

      actions   = ["sns:Publish"]
      resources = [aws_sns_topic.alerts.arn]

      condition {
        test     = "ArnLike"
        variable = "aws:SourceArn"
        values   = [local.alarm_arn_pattern]
      }
    }
  }
}

resource "aws_sns_topic_policy" "alerts" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.topic_policy.json
}