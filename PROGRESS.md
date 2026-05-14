# CloudGuard — Build Progress Log

> Running log of what's been done, decisions made, and lessons learned.
> Updated at the end of every STEP. Read this at the start of every new session.

---

## Current Status

- **Last completed STEP:** 3 (Set Up Terraform Remote Backend)
- **Next up:** STEP 4 (Build the IAM Terraform Module)
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

### ⏭️ STEP 4 — Build the IAM Terraform Module
*Status: Not started — UP NEXT*

**What STEP 4 involves (read before starting):**
- File to work in: `terraform/modules/iam/main.tf`, `variables.tf`, `outputs.tf`
- Create one IAM role per Lambda function (4 roles total) with separate least-privilege policies.
- Each role: assume-role policy for `lambda.amazonaws.com` + CloudWatch Logs permissions + function-specific permissions.
- Roles: `cost_scanner`, `security_scanner`, `resource_cleanup`, `report_generator`
- Use `environment` variable so role names differ between dev/prod (e.g. `cloudguard-cost-scanner-dev`)
- Output all 4 role ARNs (consumed by the Lambda module in STEP 8)
- Done when: `terraform plan` in `terraform/environments/dev` shows the 4 roles (no apply yet)

---

### ⬜ STEP 5 — Build the DynamoDB Terraform Module
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

- [ ] Pick alert email address for SNS subscription (needed in STEP 7) — will go in `terraform.tfvars`
- [ ] Decide Slack vs email-only for alerts (Slack webhook stored in Secrets Manager if used)
- [ ] Confirm free tier limits before STEP 17 (`terraform apply`) — Lambda, DynamoDB, S3 all have free tiers; Step Functions has 4000 free state transitions/month

---

## Interview Prep Notes

- **STEP 2 — separate env folders over workspaces:** "Workspaces share code with different state files — fine for ephemeral environments like PR previews. For stable long-lived environments, separate folders give complete isolation: different configs, different backends, impossible to accidentally apply prod when you meant dev."

- **STEP 2 — why gitignore `*.tfstate`:** "State files contain real resource IDs, ARNs, and sometimes plaintext secrets. If state leaks to git, an attacker can map your entire infrastructure. Always use remote state with encryption — never in git."

- **STEP 3 — why S3 + `use_lockfile` over S3 + DynamoDB:** "Prior to Terraform 1.10, DynamoDB was required for locking because S3 had no atomic write primitive. From 1.10 onwards, the S3 backend uses S3's native conditional writes to create a `.tflock` file atomically — same guarantee, one fewer service to manage. I'm on 1.14.6 so I use native locking."

- **STEP 3 — why commit `.terraform.lock.hcl`:** "The lock file pins provider versions — in our case `hashicorp/aws v5.100.0`. Committing it means every developer and every CI run gets the exact same provider, not whatever is latest that day. It's the Terraform equivalent of a `package-lock.json`."

- **STEP 5 (DynamoDB billing mode):** _[fill in during STEP 5]_
- **STEP 8 (reusable Lambda module — why module vs inline):** _[fill in during STEP 8]_
- **STEP 15 (Step Functions over chained Lambdas):** _[fill in during STEP 15]_
