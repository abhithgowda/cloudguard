# =============================================================================
# outputs.tf — Dev environment outputs
#
# Surface key resource identifiers so downstream tooling (CI/CD, scripts,
# `terraform output`) can consume them without parsing module internals.
# =============================================================================

output "iam_role_arns" {
  description = "ARNs of all 4 Lambda execution roles."
  value = {
    cost_scanner     = module.iam.cost_scanner_role_arn
    security_scanner = module.iam.security_scanner_role_arn
    resource_cleanup = module.iam.resource_cleanup_role_arn
    report_generator = module.iam.report_generator_role_arn
  }
}
