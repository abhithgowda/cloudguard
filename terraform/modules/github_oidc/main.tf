# =============================================================================
# main.tf — GitHub Actions OIDC module
#
# Creates the AWS-side trust for GitHub Actions to assume IAM roles via OIDC
# instead of long-lived access keys.
#
# Resources:
#   1. aws_iam_openid_connect_provider — registers GitHub's IdP with this AWS
#      account. ACCOUNT-GLOBAL: only one provider per IdP URL per account, so
#      if a prod environment later lives in the SAME AWS account, this resource
#      must move to a shared bootstrap state or be looked up via `data`. With
#      prod in a SEPARATE account (recommended), each account has its own.
#
#   2. aws_iam_role.github_plan — assumable from ANY branch or PR. Scoped to
#      ReadOnlyAccess + state-bucket write (Terraform plan needs to acquire
#      the S3 native lock and read state). Used by .github/workflows/ci.yml.
#
#   3. aws_iam_role.github_deploy — assumable ONLY from the `main` branch's
#      workflow runs. Scoped to AdministratorAccess for now (acknowledged
#      TODO: tighten to the specific service set CloudGuard manages — IAM,
#      KMS, DynamoDB, S3, SNS, Lambda, States, Events, Logs). Used by
#      .github/workflows/deploy.yml.
#
# The branch-scoped trust policy is the security boundary that lets us hand
# the plan role weaker permissions and the deploy role stronger ones without
# fearing that a malicious PR (which CAN edit the workflow file) can escalate
# from plan to apply — the deploy role's `sub` condition denies anything
# that didn't run against `refs/heads/main`.
# =============================================================================

# -----------------------------------------------------------------------------
# OIDC provider
#
# `url` MUST be `https://token.actions.githubusercontent.com` — that's the
# issuer GitHub puts in every OIDC token. AWS validates the token's signature
# against this URL.
#
# `client_id_list` MUST contain `sts.amazonaws.com` — that's the audience
# `aws-actions/configure-aws-credentials` requests when calling AssumeRoleWith-
# WebIdentity. The role's trust policy below also checks this `aud` claim.
#
# `thumbprint_list` was historically how AWS verified GitHub's TLS cert. Since
# 2023, IAM validates against its built-in library of public CA roots, so the
# thumbprint is effectively cosmetic — but the argument is still required and
# AWS examples publish the values below. We include two for resilience against
# a future cert rotation.
# -----------------------------------------------------------------------------
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

locals {
  name_prefix      = "${var.project}-${var.environment}"
  oidc_provider    = aws_iam_openid_connect_provider.github.arn
  oidc_audience    = "token.actions.githubusercontent.com:aud"
  oidc_subject     = "token.actions.githubusercontent.com:sub"
  repo_qualifier   = "repo:${var.github_org}/${var.github_repo}"
  state_bucket_arn = "arn:aws:s3:::${var.state_bucket_name}"
}

# =============================================================================
# Role 1 — github_plan
#
# Trust policy:
#   - Federated principal: the OIDC provider above.
#   - Action: sts:AssumeRoleWithWebIdentity (the only action a federated
#     principal can perform).
#   - aud condition: enforces that the token was minted with the audience our
#     `configure-aws-credentials` step requests (defense-in-depth — without
#     this, any token from GitHub's IdP minted for a different audience could
#     potentially be replayed).
#   - sub condition: StringLike on `repo:<org>/<repo>:*` — any workflow run
#     in this specific repo, on any branch or PR. The leading `repo:` and
#     trailing `*` together pin to this repo (so a different repo named
#     "cloudguard-fork" can't assume the role) while permitting PR + branch
#     contexts.
# =============================================================================
data "aws_iam_policy_document" "plan_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider]
    }
    condition {
      test     = "StringEquals"
      variable = local.oidc_audience
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = local.oidc_subject
      values   = ["${local.repo_qualifier}:*"]
    }
  }
}

resource "aws_iam_role" "github_plan" {
  name               = "${local.name_prefix}-github-plan-role"
  description        = "Assumed by GitHub Actions (any branch/PR) for terraform plan."
  assume_role_policy = data.aws_iam_policy_document.plan_assume_role.json
}

# ReadOnlyAccess is AWS's blessed read-only managed policy. It covers all the
# Describe/Get/List actions Terraform needs to refresh state and produce a
# plan diff. Using the managed policy (vs. hand-rolling a read policy) means
# AWS keeps it in sync as new services launch.
resource "aws_iam_role_policy_attachment" "plan_readonly" {
  role       = aws_iam_role.github_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# Terraform's S3 backend with `use_lockfile = true` writes a `.tflock` object
# to acquire the state lock. The plan job needs PutObject + DeleteObject for
# the lockfile and GetObject for the state itself. ReadOnlyAccess alone is
# NOT sufficient — `s3:PutObject` is a write action.
resource "aws_iam_role_policy" "plan_state_access" {
  name = "${local.name_prefix}-github-plan-state-access"
  role = aws_iam_role.github_plan.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "StateBucketReadWrite"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = "${local.state_bucket_arn}/*"
      },
      {
        Sid      = "StateBucketList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = local.state_bucket_arn
      },
    ]
  })
}

# =============================================================================
# Role 2 — github_deploy
#
# Same trust shape as plan, but the `sub` condition is locked to the `main`
# branch. A workflow running on a PR or feature branch CANNOT assume this
# role even if its YAML hardcodes the ARN — STS will reject the AssumeRole
# call with `AccessDenied`. This is the security boundary that makes OIDC
# materially safer than static keys: with static keys, anyone with the key
# can deploy; with OIDC + branch-scoped trust, only main-branch workflows can.
#
# Format reference: GitHub's `sub` claim for a push-to-main workflow run is
#   repo:<org>/<repo>:ref:refs/heads/<branch>
# (For PR-triggered runs it would be `repo:<org>/<repo>:pull_request`, which
# does NOT match this StringEquals condition.)
# =============================================================================
data "aws_iam_policy_document" "deploy_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider]
    }
    condition {
      test     = "StringEquals"
      variable = local.oidc_audience
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = local.oidc_subject
      values   = ["${local.repo_qualifier}:ref:refs/heads/${var.deploy_branch}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${local.name_prefix}-github-deploy-role"
  description        = "Assumed by GitHub Actions ONLY from the deploy branch for terraform apply."
  assume_role_policy = data.aws_iam_policy_document.deploy_assume_role.json
}

# TODO (hardening pass): replace AdministratorAccess with a custom policy
# scoped to the AWS service set CloudGuard actually manages — IAM, KMS,
# DynamoDB, S3, SNS, Lambda, States, Events, Logs, plus EC2/RDS/Config
# describe perms that some Lambda roles re-read. AdministratorAccess is the
# pragmatic dev choice; production should not run CI/CD with admin.
resource "aws_iam_role_policy_attachment" "deploy_admin" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
