output "oidc_provider_arn" {
  value       = aws_iam_openid_connect_provider.github.arn
  description = "ARN of the GitHub Actions OIDC provider. Account-global — share this across environments."
}

output "plan_role_arn" {
  value       = aws_iam_role.github_plan.arn
  description = "ARN to set as AWS_PLAN_ROLE_ARN repo variable. Used by ci.yml (terraform plan)."
}

output "deploy_role_arn" {
  value       = aws_iam_role.github_deploy.arn
  description = "ARN to set as AWS_DEPLOY_ROLE_ARN repo variable. Used by deploy.yml (terraform apply). Only assumable from the configured deploy branch."
}
