# CloudGuard — Build Progress Log

> Running log of what's been done, decisions made, and lessons learned.
> Updated at the end of every STEP. Read this at the start of every new session.

---

## Current Status

- **Last completed STEP:** 2 (Set Up Repository Structure)
- **Next up:** STEP 3 (Set Up Terraform Remote Backend)
- **Last updated:** 2026-05-14
- **Environment focus:** `dev` (region: `ap-south-1`)
- **AWS account:** Personal (free tier, own card)

---

## STEP Completion Log

### ✅ STEP 1 — Set Up Development Environment
*Completed: 2026-05-14*

- **Tools installed (versions):**
  - Python: `3.13.7` — note: blueprint pins 3.12, but 3.12 was unavailable on this machine. Risk noted: local runtime differs from Lambda's `python3.12`. Will catch issues in STEP 14 (unit tests) and STEP 19 (end-to-end).
  - Terraform: `1.14.6` — installed via Cognizant internal software portal ("Community Windows-Freeware"). Binary placed at `C:\tools\terraform`, added to User PATH. Satisfies blueprint's `>= 1.5` requirement.
  - AWS CLI: `2.27.17` — installed and confirmed with `aws sts get-caller-identity`.
  - Git: `2.51.0`
  - VS Code: installed with extensions — Python (Microsoft), HashiCorp Terraform, GitLens, YAML (Red Hat).
- **Virtual environment:** `cloudguard-env/` created at repo root using `python -m venv`. boto3 `1.43.7` and pytest `9.0.3` installed inside venv. Location: `cloudguard-env\Lib\site-packages`.
- **AWS account type:** Personal (free tier, own card)
- **AWS CLI configured for default region:** `ap-south-1`
- **IAM user:** `abhithV1` (admin access — dev only; least-privilege roles will be enforced at Lambda level via Terraform in STEP 4)
- **Surprises / notes:**
  - Cognizant has an internal software request portal — used for Terraform and AWS CLI installs.
  - Original Terraform install path had a space in folder name; moved to `C:\tools\terraform` for cleanliness.
  - `virtualenv` package not installed separately — used built-in `python -m venv` instead (same outcome for our use case).
  - Python 3.12 unavailable; proceeding with 3.13.7 with noted risk.

---

### ✅ STEP 2 — Set Up Repository Structure
*Completed: 2026-05-14*

- **Repo URL:** `https://github.com/abhithcogni/cloudguard.git`
- **Local path:** `C:\Users\2406667\Programming\AWS project\cloudguard`
- **Initial commit hash:** `a613fa6` (first commit)
- **STEP 2 commit hash:** `a4953ed` (STEP 2: initial project structure — 64 files)
- **Folder structure created:** Full tree per `PROJECT_BLUEPRINT.md` section 5 — 18 directories, all module and source stubs created.
- **`.gitignore` patterns added:**
  - Python: `__pycache__/`, `*.py[cod]`, `cloudguard-env/`, `.env`
  - Terraform: `.terraform/`, `.terraform.lock.hcl`, `*.tfstate`, `*.tfstate.backup`, `*.tfplan`, `terraform.tfvars`, `crash.log`
  - Lambda zips: `*.zip`, `terraform/environments/dev/*.zip`
  - IDE: `.vscode/`, `.idea/`, `.DS_Store`, `Thumbs.db`
  - Secrets: `*.pem`, `*.key`
- **Decisions made:**
  - Used `terraform.tfvars.example` (committed, safe placeholder) + gitignored `terraform.tfvars` (real values). Standard open-source Terraform pattern.
  - Created real empty stub files (e.g., `handler.py`, `main.tf`) rather than `.gitkeep` — gives a browsable project map in VS Code immediately.
  - Chose **separate folders per environment** (`dev/`, `prod/`) over Terraform workspaces. Reason: workspaces risk wrong-environment applies; separate folders give full config isolation and make accidental prod apply nearly impossible.
- **Surprises / notes:**
  - Git bash shell in Claude Code kept resetting cwd to worktree; switched to PowerShell for all file/directory creation.

---

### ⏭️ STEP 3 — Set Up Terraform Remote Backend
*Status: Not started — UP NEXT*

### ⬜ STEP 4 — Build the IAM Terraform Module
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
| 2026-05-14 | Separate folders per env (`dev/`, `prod/`) over Terraform workspaces | Workspaces risk wrong-env apply; folders give full isolation | Workspaces — better for ephemeral/PR envs, not stable long-lived envs |
| 2026-05-14 | `terraform.tfvars.example` committed, `terraform.tfvars` gitignored | Prevents secrets in git; example documents required vars for new devs | Committing tfvars — rejected: leaks emails, bucket names, account context |
| 2026-05-14 | Python 3.13.7 instead of 3.12 | 3.12 unavailable on machine; 3.12 is Lambda runtime — risk accepted | Install 3.12 alongside 3.13 — user unable to do so on Cognizant machine |

---

## Problems Hit & Resolved

| Date | STEP | Problem | Resolution | Lesson |
|------|------|---------|------------|--------|
| 2026-05-14 | STEP 1 | Python 3.12 unavailable | Proceeded with 3.13.7; risk noted for Lambda runtime mismatch | Always pin runtime versions early; Lambda `python3.12` runtime is the target |
| 2026-05-14 | STEP 2 | Bash shell in Claude Code reset cwd to git worktree on every command | Switched to PowerShell for all directory/file creation | Use PowerShell for Windows file ops in Claude Code sessions |

---

## Open Questions / TODOs

- [ ] Pick alert email address for SNS subscription (needed in STEP 7)
- [ ] Pick unique suffix for Terraform state bucket name (`cloudguard-tf-state-<???>`) — needed in STEP 3
- [ ] Decide Slack vs email-only for alerts (Slack webhook stored in Secrets Manager?)
- [ ] Confirm: will `terraform apply` be run against personal AWS account? Free tier limits apply.

---

## Interview Prep Notes

- **STEP 2 (why separate env folders over workspaces):** "Workspaces share code with different state files — fine for ephemeral environments like PR previews. For stable long-lived environments like dev and prod, separate folders give complete isolation: different configs, different backends, impossible to accidentally apply prod when you meant dev."
- **STEP 2 (why gitignore `*.tfstate`):** "State files contain real resource IDs, ARNs, and sometimes secrets in plaintext. If state leaks, an attacker can map your entire infrastructure. Always remote state with encryption, never in git."
- **STEP 5 (DynamoDB tables, billing mode):** _[fill in]_
- **STEP 8 (reusable Lambda module — why module vs. inline?):** _[fill in]_
- **STEP 15 (Step Functions over chained Lambdas):** _[fill in]_
