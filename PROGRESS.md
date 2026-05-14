# CloudGuard — Build Progress Log

> Running log of what's been done, decisions made, and lessons learned.
> Updated at the end of every STEP. Read this at the start of every new session.

---

## Current Status

- **Last completed STEP:** 5 (Build the DynamoDB Terraform Module)
- **Next up:** STEP 6 (Build the S3 Terraform Module)
- **Last updated:** 2026-05-14
- **Environment focus:** `dev` (region: `ap-south-1`)
- **AWS account:** Personal (free tier, own card)

---

## How to Resume in a New Session

1. Read this file top to bottom.
2. Read `PROJECT_BLUEPRINT.md` section for the next STEP.
3. Activate the venv: `cloudguard-env\Scripts\activate` (from repo root in PowerShell)
4. For any Terraform work: `cd terraform\environments\dev` — this is where `terraform plan/apply` runs.
5. The remote backend is already initialised — no need to re-run `setup_backend.sh`.
6. **Use PowerShell** for all file/directory operations (Bash resets cwd in this env).
7. Terraform is in the user's PATH but not Claude Code's shell — ask user to run `terraform` commands in their own terminal and paste output.

---

## STEP Completion Log

### ✅ STEP 1 — Set Up Development Environment
*Completed: 2026-05-14*

- **Tools installed (versions):**
  - Python: `3.13.7` — blueprint pins 3.12 (Lambda runtime). Risk noted: local/Lambda mismatch. Will catch in STEP 14 and STEP 19.
  - Terraform: `1.14.6` — installed via Cognizant software portal. At `C:\tools\terraform`, added to user PATH.
  - AWS CLI: `2.27.17`
  - Git: `2.51.0`
  - VS Code: Python, HashiCorp Terraform, GitLens, YAML (Red Hat) extensions installed.
- **Virtual environment:** `cloudguard-env/` at repo root. boto3 `1.43.7`, pytest `9.0.3` installed inside.
- **AWS account:** Personal free tier. IAM user `abhithV1` with admin access (dev only).
- **AWS CLI default region:** `ap-south-1`
- **Surprises:** Cognizant software portal used for Terraform + AWS CLI. Python 3.12 unavailable; proceeded with 3.13.7.

---

### ✅ STEP 2 — Set Up Repository Structure
*Completed: 2026-05-14*

- **Repo URL:** `https://github.com/abhithcogni/cloudguard.git`
- **Local path:** `C:\Users\2406667\Programming\AWS project\cloudguard`
- **Commit hash:** `a4953ed` (64 files, full folder tree)
- **Folder structure:** Full tree per `PROJECT_BLUEPRINT.md` section 5 — 18 directories, all module + source stubs.
- **`.gitignore` covers:** Python (`__pycache__`, venv, `.pyc`), Terraform (`.terraform/`, `*.tfstate`, `terraform.tfvars`), Lambda zips, IDE files, secrets.
- **Key decisions:**
  - Separate folders per env (`dev/`, `prod/`) over Terraform workspaces — safety: impossible to accidentally apply prod.
  - `terraform.tfvars.example` committed (safe template); `terraform.tfvars` gitignored (real values).
  - Real stub files (not `.gitkeep`) — VS Code shows the full project map immediately.
- **Surprises:** Bash shell in Claude Code resets cwd to git worktree — use PowerShell for all file ops.

---

### ✅ STEP 3 — Set Up Terraform Remote Backend
*Completed: 2026-05-14*

- **S3 bucket:** `cloudguard-tf-state-abhithcogni` (region: `ap-south-1`)
  - Versioning: ✅ Enabled
  - Encryption: ✅ SSE-S3 (AES256) — chose over SSE-KMS because free, zero config; KMS adds audit trail but costs ~$1/month per key, overkill for personal project state.
  - Public access block: ✅ All 4 settings = true
- **DynamoDB lock table:** NOT created. Terraform >= 1.10 supports native S3 locking via `use_lockfile = true`. User has 1.14.6 — DynamoDB is unnecessary.
- **Files written:**
  - `scripts/setup_backend.sh` — documents and automates the S3 bucket creation steps
  - `terraform/environments/dev/backend.tf` — S3 backend config with `use_lockfile = true`, `required_version >= 1.10`, AWS provider `~> 5.0`
  - `terraform/environments/dev/variables.tf` — 4 variables: `aws_region`, `environment`, `project`, `alert_email`
  - `terraform/environments/dev/terraform.tfvars.example` — safe template (no real values)
  - `terraform/environments/dev/main.tf` — AWS provider block with `default_tags`
- **`terraform init` result:** ✅ Success. AWS provider `v5.100.0` installed. Backend "s3" configured.
- **Lock file:** `terraform/environments/dev/.terraform.lock.hcl` — pins AWS provider at `v5.100.0`. **Committed** (Terraform recommends this; ensures identical provider versions on every `init`).
- **Bug fixed:** `.terraform.lock.hcl` was incorrectly added to `.gitignore` in STEP 2. Removed in this STEP.
- **GitHub Actions fix:** Both `ci.yml` and `deploy.yml` changed from `on: push` to `on: workflow_dispatch` — stops spurious emails on every commit. Will be properly built in STEP 20.
- **Surprises:**
  - Terraform not in Claude Code's shell PATH (only in user's PowerShell). Workaround: user runs `terraform` commands in their own terminal and pastes output.
  - `.terraform.lock.hcl` should be committed, not gitignored — corrected.

---

### ✅ STEP 4 — Build the IAM Terraform Module
*Completed: 2026-05-14*

- **Files written:**
  - `terraform/modules/iam/main.tf` — 4 roles, 4 inline policies, 4 managed-policy attachments. Uses data sources for account_id + region; locals for naming + assume-role policy + resource ARNs.
  - `terraform/modules/iam/variables.tf` — `environment`, `project`
  - `terraform/modules/iam/outputs.tf` — 4 role ARNs + 4 role names
  - `terraform/environments/dev/main.tf` — wired up the iam module
  - `terraform/environments/dev/outputs.tf` — surfaces `iam_role_arns` map
  - `terraform/environments/dev/terraform.tfvars` — created locally with real `alert_email` (gitignored — not committed)
- **Role naming convention:** `${project}-${environment}-${function}-role` (e.g. `cloudguard-dev-cost-scanner-role`)
- **Permissions design — key decisions:**
  - **Inline policies** (not customer-managed): each policy is unique to one role, inline makes ownership obvious and policy auto-deletes with role.
  - **`AWSLambdaBasicExecutionRole`** (AWS-managed) attached to every role for CloudWatch Logs perms — don't reinvent AWS-blessed patterns.
  - **Resource scoping**:
    - DynamoDB → scoped to specific table ARNs built from naming convention (tables don't exist yet, but ARNs are deterministic)
    - S3 reports bucket → scoped to `arn:aws:s3:::cloudguard-dev-reports/*`
    - SNS alerts topic → scoped to `arn:aws:sns:<region>:<account>:cloudguard-dev-alerts`
    - `ce:*`, `ec2:Describe*`, `rds:Describe*`, `iam:List*`, `ses:SendEmail` → `Resource = "*"` (AWS API limitation — these actions don't support resource-level perms)
    - **`ec2:DeleteVolume`, `ec2:ReleaseAddress`** → `Resource = "*"` with WARNING comment. In production, scope with Condition on tag `ec2:ResourceTag/AutoCleanup = true`. Hardening TODO.
- **`terraform plan` result:** ✅ `Plan: 12 to add, 0 to change, 0 to destroy.` — 4 roles + 4 inline policies + 4 managed-policy attachments. No apply yet (per STEP 4 blueprint).

---

### ✅ STEP 5 — Build the DynamoDB Terraform Module
*Completed: 2026-05-14*

- **Files written:**
  - `terraform/modules/dynamodb/main.tf` — 3 DynamoDB tables with all schema, GSIs, TTL, PITR, KMS
  - `terraform/modules/dynamodb/variables.tf` — `project`, `environment`
  - `terraform/modules/dynamodb/outputs.tf` — 6 outputs: name + ARN for each of the 3 tables
  - `terraform/environments/dev/main.tf` — wired up the dynamodb module
  - `terraform/environments/dev/outputs.tf` — added `dynamodb_table_names` and `dynamodb_table_arns` outputs
- **Table names (match IAM module ARNs exactly):**
  - `cloudguard-dev-findings` — PK `finding_id`, SK `timestamp`; GSI: `severity-index`, `category-index`; TTL: `expires_at`
  - `cloudguard-dev-cost-data` — PK `date`, SK `service_name`; no GSIs
  - `cloudguard-dev-remediation-log` — PK `remediation_id`, SK `timestamp`; GSI: `status-index`
- **Key decisions:**
  - **PAY_PER_REQUEST over provisioned:** Scanner runs every 6 hours — traffic is bursty, not steady. Provisioned capacity requires you to predict RCUs/WCUs and either over-provision (wastes money) or under-provision (throttles). PAY_PER_REQUEST scales automatically and costs nothing when idle — correct for an infrequent automated workload.
  - **KMS with AWS-managed key (`aws/dynamodb`):** Blueprint requires KMS encryption. Using the AWS-managed DynamoDB key (`enabled = true`, no custom key ARN) — it's free, zero config, and still encrypts at rest with KMS. Customer-managed key costs $1/month per key and adds management overhead; not justified for a personal dev environment.
  - **GSI sort key = `timestamp`:** All GSIs use `timestamp` as the sort key so queries return results in chronological order by default. The alternative (no sort key) would return results in arbitrary order and make "latest N critical findings" queries less efficient.
  - **TTL only on findings table:** Cost data and remediation logs are operational records worth keeping indefinitely (or until PITR recovery window). Findings are ephemeral — a 90-day auto-expiry matches the IAM key rotation policy window and keeps the table lean.
  - **PITR on all 3 tables:** Point-in-Time Recovery gives a 35-day rollback window for free on PAY_PER_REQUEST tables. Cheap insurance against accidental writes during testing.
- **`terraform plan` result:** ✅ `Plan: 15 to add, 0 to change, 0 to destroy.` — 12 IAM resources (STEP 4, not yet applied) + 3 DynamoDB tables. No apply yet (blueprint does not require apply until STEP 17).

### ⬜ STEP 6 — Build the S3 Terraform Module
### ⬜ STEP 7 — Build the SNS Terraform Module
### ⬜ STEP 8 — Build the Lambda Terraform Module (Reusable)
### ⬜ STEP 9 — Write the Cost Scanner Lambda
### ⬜ STEP 10 — Write the Security Scanner Lambda
### ⬜ STEP 11 — Write the Resource Cleanup Lambda
### ⬜ STEP 12 — Write the Report Generator Lambda
### ⬜ STEP 13 — Write the Shared Utilities
### ⬜ STEP 14 — Write Unit Tests
### ⬜ STEP 15 — Build the Step Functions Workflow
### ⬜ STEP 16 — Build the EventBridge Terraform Module
### ⬜ STEP 17 — Wire Everything Together in Dev Environment
### ⬜ STEP 18 — Create the Lambda Packaging Script
### ⬜ STEP 19 — Test the System End-to-End
### ⬜ STEP 20 — Build the CI/CD Pipeline
### ⬜ STEP 21 — Add CloudWatch Dashboard
### ⬜ STEP 22 — Write Documentation
### ⬜ STEP 23 — Add Resource Tagging Strategy

**Legend:** ✅ done · ⏭️ up next · 🛑 blocked · ⬜ not started

---

## Decision Log

| Date | Decision | Reasoning | Alternative considered |
|------|----------|-----------|------------------------|
| 2026-05-14 | Separate folders per env (`dev/`, `prod/`) over Terraform workspaces | Impossible to accidentally apply prod; full config isolation per env | Workspaces — better for ephemeral/PR envs, not stable long-lived envs |
| 2026-05-14 | `terraform.tfvars.example` committed, `terraform.tfvars` gitignored | Prevents secrets in git; example documents required vars | Committing tfvars — rejected: leaks emails, bucket names, account context |
| 2026-05-14 | Python 3.13.7 instead of 3.12 | 3.12 unavailable; 3.12 is Lambda runtime — risk accepted, will catch in tests | Install 3.12 alongside 3.13 — unavailable on Cognizant machine |
| 2026-05-14 | S3 native locking (`use_lockfile = true`) instead of DynamoDB | Terraform >= 1.10 supports it natively; removes a dependency; user on 1.14.6 | DynamoDB lock table — still valid, gives visible lock state, but unnecessary overhead |
| 2026-05-14 | SSE-S3 (AES256) for state bucket, not SSE-KMS | Free, zero config; KMS adds audit trail but costs money — overkill for personal project | SSE-KMS — better for company accounts needing audit trails of state access |
| 2026-05-14 | Commit `.terraform.lock.hcl` | Terraform official recommendation; pins provider versions for reproducible inits | Gitignore it — rejected: then provider version can drift between machines |
| 2026-05-14 | Inline policies per role (not customer-managed) | Each policy is unique to one role; inline makes ownership obvious and auto-deletes with role | Customer-managed — only better if shared across roles |
| 2026-05-14 | Attach `AWSLambdaBasicExecutionRole` for Logs perms | AWS-blessed pattern, don't reinvent the wheel | Custom inline Logs policy — works but adds maintenance |
| 2026-05-14 | Build DynamoDB/SNS/S3 ARNs in IAM via naming convention (resources don't exist yet) | Tighter than `Resource = "*"`; deterministic ARN format; ARNs validated at apply not plan | Pass real ARNs as inputs — better long term but creates ordering complexity; revisit if drift |
| 2026-05-14 | `ec2:DeleteVolume`/`ReleaseAddress` with `Resource = "*"` for now | Can't know zombie resource IDs ahead of time | Tag-based Condition `ec2:ResourceTag/AutoCleanup = true` — hardening TODO |
| 2026-05-14 | DynamoDB PAY_PER_REQUEST billing mode | Bursty workload (scan every 6 hrs, idle between); provisioned would require capacity guessing | Provisioned — better for sustained high-throughput workloads where you know your RCU/WCU |
| 2026-05-14 | KMS using AWS-managed key (`aws/dynamodb`) not customer-managed | Free, zero config, still KMS-backed; CMK costs $1/month per key — overkill for personal dev | Customer-managed KMS key — better for regulated environments needing key policy control + audit trail |
| 2026-05-14 | PITR enabled on all 3 DynamoDB tables | 35-day rollback window; free on PAY_PER_REQUEST tables; cheap insurance during testing phase | Disable PITR — saves nothing (it's free), removes safety net |

---

## Problems Hit & Resolved

| Date | STEP | Problem | Resolution | Lesson |
|------|------|---------|------------|--------|
| 2026-05-14 | STEP 1 | Python 3.12 unavailable | Proceeded with 3.13.7; risk noted | Always pin runtime versions early |
| 2026-05-14 | STEP 2 | Bash in Claude Code resets cwd to git worktree | Use PowerShell for all file/dir ops | PowerShell is reliable; Bash is not in this env |
| 2026-05-14 | STEP 2 | `.terraform.lock.hcl` incorrectly added to `.gitignore` | Removed from gitignore in STEP 3; lock file committed | Lock file = commit; `.terraform/` dir = ignore |
| 2026-05-14 | STEP 3 | Terraform not in Claude Code's PATH | User runs terraform commands in their own PowerShell, pastes output | Don't try to run terraform via Claude Code's shell |
| 2026-05-14 | STEP 3 | GitHub Actions firing on every push (empty workflow files) | Changed trigger to `workflow_dispatch` until STEP 20 | Stub workflow files need a safe trigger |

---

## Open Questions / TODOs

- [x] Pick alert email address — set in local `terraform.tfvars` during STEP 4
- [ ] Decide Slack vs email-only for alerts (Slack webhook stored in Secrets Manager if used)
- [ ] Confirm free tier limits before STEP 17 (`terraform apply`) — Lambda, DynamoDB, S3 all have free tiers; Step Functions has 4000 free state transitions/month
- [ ] **Hardening (post-STEP 17):** Scope `ec2:DeleteVolume`/`ec2:ReleaseAddress` in resource_cleanup role with `Condition: ec2:ResourceTag/AutoCleanup=true`
- [ ] **Hardening (post-STEP 7):** Scope `ses:SendEmail` with Condition on verified SES identity ARN

---

## Interview Prep Notes

- **STEP 2 — separate env folders over workspaces:** "Workspaces share code with different state files — fine for ephemeral environments like PR previews. For stable long-lived environments, separate folders give complete isolation: different configs, different backends, impossible to accidentally apply prod when you meant dev."

- **STEP 2 — why gitignore `*.tfstate`:** "State files contain real resource IDs, ARNs, and sometimes plaintext secrets. If state leaks to git, an attacker can map your entire infrastructure. Always use remote state with encryption — never in git."

- **STEP 3 — why S3 + `use_lockfile` over S3 + DynamoDB:** "Prior to Terraform 1.10, DynamoDB was required for locking because S3 had no atomic write primitive. From 1.10 onwards, the S3 backend uses S3's native conditional writes to create a `.tflock` file atomically — same guarantee, one fewer service to manage. I'm on 1.14.6 so I use native locking."

- **STEP 3 — why commit `.terraform.lock.hcl`:** "The lock file pins provider versions — in our case `hashicorp/aws v5.100.0`. Committing it means every developer and every CI run gets the exact same provider, not whatever is latest that day. It's the Terraform equivalent of a `package-lock.json`."

- **STEP 4 — why inline policy over managed:** "Each Lambda's policy is unique — nothing shared between roles. Inline policy makes the ownership relationship obvious (this policy belongs to this role, nothing else) and the policy is deleted automatically when the role is deleted. Customer-managed policies are better when the same permissions are attached to multiple roles — they have their own ARN, can be versioned, and updated independently."

- **STEP 4 — why I have `Resource = "*"` on some statements:** "Not all AWS actions support resource-level permissions. `ce:GetCostAndUsage`, `ec2:DescribeInstances`, `iam:ListUsers`, `ses:SendEmail` — none of these accept a Resource ARN. AWS publishes a service authorization reference table that lists this per action. For everything that COULD be scoped, I did — DynamoDB tables, SNS topic, S3 bucket — all scoped to specific ARNs built from a naming convention. For destructive EC2 actions that can't pre-scope, in production I'd add a tag-based Condition."

- **STEP 4 — least privilege vs least permissive:** "Least privilege isn't `Resource = "*"` — that's just permissive. Least privilege means the role can do exactly what it needs and nothing more. For cost scanner that means: Cost Explorer read, EC2/RDS describe (can't be scoped further), DynamoDB writes scoped to exactly two tables. The cost scanner cannot — and will never be able to — touch S3, SNS, IAM, or any other DynamoDB table."

- **STEP 5 — DynamoDB PAY_PER_REQUEST vs provisioned:** "Provisioned capacity requires you to predict read and write capacity units upfront. If you under-provision, DynamoDB throttles your requests. If you over-provision, you pay for idle capacity. For CloudGuard, the scanners run on a schedule — traffic is completely bursty: zero for 6 hours, then a burst of writes when a scan completes. PAY_PER_REQUEST handles that burst automatically, costs nothing when idle, and removes the operational burden of capacity planning. It's slightly more expensive per request than provisioned at high, sustained throughput — but for a scan-on-schedule system, it's the right call."

- **STEP 5 — Why GSIs on severity and category:** "DynamoDB is a key-value store. Without GSIs, fetching all CRITICAL findings would require a full table scan — reads every item, expensive and slow. A GSI on `severity` makes it a single Query call: `severity = CRITICAL`, sorted by `timestamp`. Same logic for `category` — lets the report generator pull all cost findings or all security findings without scanning everything else."

- **STEP 5 — Why TTL on findings but not the other two tables:** "TTL lets DynamoDB auto-delete items based on a Unix timestamp attribute, at no cost. Findings are time-bounded — a 90-day-old security finding is stale, the resource may have been fixed. Auto-expiry keeps the table lean and avoids manual cleanup jobs. Cost data and remediation logs are operational records — you want to keep them to spot trends and audit what was auto-deleted."
- **STEP 8 (reusable Lambda module — why module vs inline):** _[fill in during STEP 8]_
- **STEP 15 (Step Functions over chained Lambdas):** _[fill in during STEP 15]_
