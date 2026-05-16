# CloudGuard — Build Progress Log

> Running log of what's been done, decisions made, and lessons learned.
> Updated at the end of every STEP. Read this at the start of every new session.

---

## Current Status

- **Last completed STEP:** 8 (Build the SNS Terraform Module)
- **Next up:** STEP 9 (Build the Lambda Terraform Module — reusable)
- **Last updated:** 2026-05-16
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
7. Terraform IS in Claude Code's shell PATH (confirmed STEP 5) — `terraform plan` can be run directly without needing the user's terminal.

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
- **`terraform plan` result:** ✅ `Plan: 15 to add, 0 to change, 0 to destroy.` — 12 IAM resources (STEP 4, not yet applied) + 3 DynamoDB tables. No apply yet (blueprint does not require apply until STEP 18).
- **Note (2026-05-15):** STEP 5 currently uses AWS-managed `aws/dynamodb` key. Per blueprint amendment 2026-05-15, a new STEP 6 (KMS CMK Module) has been inserted; the DynamoDB module will be retrofitted in that session to consume `module.kms.key_arn`.

### ✅ STEP 6 — Build the KMS CMK Module
*Completed: 2026-05-16 · Commit: `65381f0`*

- **Files written:**
  - `terraform/modules/kms/main.tf` — 1 `aws_kms_key`, 1 `aws_kms_alias`, 1 `data "aws_iam_policy_document" "kms_key_policy"` with 4 statements
  - `terraform/modules/kms/variables.tf` — `project`, `environment`, `lambda_role_arns` (list)
  - `terraform/modules/kms/outputs.tf` — `key_arn`, `key_id`, `alias_arn`, `alias_name`
- **Files modified (DynamoDB retrofit):**
  - `terraform/modules/dynamodb/variables.tf` — added required `kms_key_arn` input
  - `terraform/modules/dynamodb/main.tf` — replaced all 3 `server_side_encryption` blocks with `{ enabled = true, kms_key_arn = var.kms_key_arn }`; updated header comment
- **Files modified (dev wiring):**
  - `terraform/environments/dev/main.tf` — added `module "kms"` between iam and dynamodb; passed `module.kms.key_arn` into the dynamodb module
  - `terraform/environments/dev/outputs.tf` — added `kms_key_arn` and `kms_alias_name` outputs
- **Key properties on the CMK:**
  - `enable_key_rotation = true` — annual automatic rotation
  - `deletion_window_in_days = 30` — maximum window; if scheduled for deletion in error, there's a month to cancel
  - `key_usage = "ENCRYPT_DECRYPT"` — symmetric encryption (default)
  - `multi_region = false` — single-region key; multi-region is for cross-region DR scenarios
- **Alias:** `alias/cloudguard-dev`
- **Key policy — design decisions:**
  - **3 separate `Sid`s for the Lambda grants** (`AllowLambdasViaDynamoDB`, `AllowLambdasViaS3`, `AllowLambdasViaSNS`) instead of one combined statement with a list of `kms:ViaService` values. More verbose, but each statement reads as a single purpose — easier to audit and to revoke one service later without touching the others.
  - **Root-account admin statement** (`kms:*` for the root principal) is non-negotiable on every CMK. Without it, a misconfigured policy can permanently lock you out — Terraform can't fix a key it can't touch.
  - **`kms:ViaService` Conditions** on every Lambda grant — a compromised role can only call KMS *through* the service it's meant to use. A leaked cost-scanner credential can't call `kms:Decrypt` directly; it has to go via DynamoDB.
  - **`aws_iam_policy_document` data source** instead of inline JSON heredoc — type-checked, references variables cleanly, surfaces typos at plan time.
  - **`bypass_policy_lockout_safety_check = false`** (default kept) — AWS will refuse to create a key with a policy that locks out root, catching the most common foot-gun.
- **`terraform plan` result:** ✅ `Plan: 17 to add, 0 to change, 0 to destroy.` — 12 IAM (STEP 4) + 3 DynamoDB (STEP 5, now with CMK refs) + 2 KMS. No apply (blueprint defers apply to STEP 18).

---

### ✅ STEP 7 — Build the S3 Terraform Module
*Completed: 2026-05-16 · Commit: `79c9ff5`*

- **Files written:**
  - `terraform/modules/s3/main.tf` — 2 buckets (`reports`, `logs`) + versioning, public-access-block, SSE, lifecycle, logging, bucket-policy resources for each, plus 2 `aws_iam_policy_document` data sources
  - `terraform/modules/s3/variables.tf` — `project`, `environment`, `reports_bucket_name`, `kms_key_arn`, `lambda_role_arns`
  - `terraform/modules/s3/outputs.tf` — `reports_bucket_name`, `reports_bucket_arn`, `reports_bucket_domain_name`, `logs_bucket_name`, `logs_bucket_arn`
- **Files modified (IAM retrofit):**
  - `terraform/modules/iam/variables.tf` — added required `reports_bucket_arn` input
  - `terraform/modules/iam/main.tf` — removed the hardcoded `local.reports_bucket_arn`; `report_generator` `s3:PutObject` policy now references `var.reports_bucket_arn`
- **Files modified (dev wiring):**
  - `terraform/environments/dev/main.tf` — added `locals { reports_bucket_name, reports_bucket_arn }` as the single source of truth; passed `reports_bucket_arn` into the iam module and `reports_bucket_name` into the new s3 module
  - `terraform/environments/dev/variables.tf` — added `bucket_suffix` (validated against S3 naming rules; no default)
  - `terraform/environments/dev/terraform.tfvars.example` — example `bucket_suffix = "your-handle"`
  - `terraform/environments/dev/terraform.tfvars` — set `bucket_suffix = "abhithcogni"` (gitignored, matches state-bucket convention from STEP 3)
  - `terraform/environments/dev/outputs.tf` — added `s3_reports_bucket_name`, `s3_reports_bucket_arn`, `s3_logs_bucket_name`
- **Bucket names produced:**
  - Reports: `cloudguard-dev-reports-abhithcogni`
  - Logs:    `cloudguard-dev-reports-abhithcogni-logs`
- **Reports bucket properties:**
  - Versioning: ✅ Enabled
  - Public access block: ✅ All 4 settings = true
  - Encryption: SSE-KMS with the shared CMK (`module.kms.key_arn`), `bucket_key_enabled = true` (~99% fewer KMS API calls at no cost)
  - Lifecycle: GLACIER_IR @ 90 days, expire @ 365 days; noncurrent → GLACIER_IR @ 30d / expire @ 90d; abort incomplete multipart uploads after 7d
  - Access logging: delivered to logs bucket under `reports-access/` prefix
  - Bucket policy: `Deny` all non-TLS requests (defense-in-depth, also a Checkov requirement) + `Allow` the 4 Lambda role ARNs to `PutObject` / `GetObject` / `ListBucket`
- **Logs bucket properties:**
  - SSE-S3 (AES256), NOT KMS — see decision below
  - Versioning enabled, all public access blocked
  - Lifecycle: expire @ 90 days (access logs balloon fast)
  - Bucket policy: Deny non-TLS + Allow `logging.s3.amazonaws.com` to `PutObject`, scoped by `aws:SourceArn = reports bucket ARN` and `aws:SourceAccount = this account` — prevents log-injection from other accounts
- **Key decisions:**
  - **Bucket-name uniqueness via suffix variable (NOT random_id):** S3 bucket names are globally unique across all AWS accounts. Used `bucket_suffix` from gitignored tfvars (same pattern as the state bucket in STEP 3) — produces deterministic names that don't change between plans. `random_id` would force IAM to consume the bucket ARN as an output and break the clean "construct once in locals" pattern.
  - **Bucket name as a `local` in `dev/main.tf`, not reconstructed in each module:** The IAM module builds the bucket ARN for `s3:PutObject`; the S3 module creates the bucket. If each rebuilt the name from inputs, a future drift (someone changes the format in one module but not the other) silently breaks the permission. One `local`, two consumers.
  - **Logs bucket = SSE-S3, reports bucket = SSE-KMS:** S3 access-log delivery is performed by the `logging.s3.amazonaws.com` service principal; if the target bucket is SSE-KMS, the service needs `kms:GenerateDataKey` on the CMK, adding another grant for log metadata that contains no payload data. SSE-S3 is AWS's recommended path for log destinations.
  - **`GLACIER_IR` over `GLACIER`:** Reports may be linked from an audit ticket months later — Glacier Flexible Retrieval (hours to restore) blocks that workflow. GLACIER_IR keeps the same archive-tier pricing with millisecond retrieval.
  - **`Deny aws:SecureTransport = false` on both buckets:** Forces HTTPS for every S3 request. Checkov flags this as missing on every bucket without it. Belt-and-braces — TLS is the default in modern SDKs, but the explicit Deny makes it impossible to disable.
  - **Bucket policy on reports bucket allows the Lambda role ARNs directly (not `*` with a Condition):** Identity-policy + resource-policy = AND, so a leaked credential outside those 4 roles is blocked at the bucket even if its IAM policy says otherwise. Listing the principals explicitly makes the audit trivial — `cat bucket-policy.json` shows exactly who can write.
  - **`bucket_key_enabled = true`:** S3 bucket keys are envelope encryption at the bucket level. Each PutObject would normally call KMS `GenerateDataKey`; with bucket keys, one key per ~5-minute window is reused for all uploads. ~99% fewer KMS calls = ~99% lower KMS request bill. No security trade-off.
  - **`SourceArn` + `SourceAccount` conditions on the logs-bucket Allow:** Without these the policy would (theoretically) let any S3 logging service in any account write to this bucket. Scoping by source ARN and account is the AWS-recommended pattern for service-principal Allow statements (the "confused deputy" prevention).
- **`terraform plan` result:** ✅ `Plan: 30 to add, 0 to change, 0 to destroy.` — 12 IAM (STEP 4, now with `reports_bucket_arn` input) + 3 DynamoDB (STEP 5) + 2 KMS (STEP 6) + 13 S3 (this STEP). No apply (blueprint defers apply to STEP 18).

### ✅ STEP 8 — Build the SNS Terraform Module
*Completed: 2026-05-16 · Commit: `<TBD>`*

- **Files written:**
  - `terraform/modules/sns/main.tf` — 1 `aws_sns_topic` (KMS-encrypted), 1 `aws_sns_topic_subscription` (email), 1 `aws_sns_topic_policy` from an `aws_iam_policy_document` with 3 statements
  - `terraform/modules/sns/variables.tf` — `project`, `environment`, `kms_key_arn`, `alert_email` (regex-validated), `lambda_role_arns`
  - `terraform/modules/sns/outputs.tf` — `topic_arn`, `topic_name`, `email_subscription_arn`
- **Files modified (dev wiring):**
  - `terraform/environments/dev/main.tf` — added `module "sns"` consuming `module.kms.key_arn`, `var.alert_email`, and the 4 Lambda role ARNs
  - `terraform/environments/dev/outputs.tf` — added `sns_topic_arn`, `sns_topic_name`, `sns_email_subscription_arn`
- **Topic name produced:** `cloudguard-dev-alerts` (matches the ARN already granted in the IAM module's `local.alerts_topic_arn` — no IAM retrofit needed).
- **Topic properties:**
  - SSE-KMS via the shared CMK (`module.kms.key_arn`) — the KMS policy's `AllowLambdasViaSNS` Sid (with `kms:ViaService = sns.<region>.amazonaws.com`, written in STEP 6) covers Lambda Publish-time encrypt calls. No KMS policy change in this STEP.
  - One email subscription. AWS sends a confirmation email on `apply`; subscription stays in `PendingConfirmation` until the recipient clicks the link (3-day validity).
- **Topic policy — 3 statements:**
  1. `EnableRootAccountAdmin` — `sns:*` for `arn:aws:iam::<account>:root`. Same lockout-protection pattern as the KMS key policy in STEP 6.
  2. `DenyInsecureTransport` — `Deny sns:Publish/Subscribe` when `aws:SecureTransport = false`. Defense-in-depth against plaintext Publish from a misconfigured client.
  3. `AllowLambdaRolesPublish` — `sns:Publish` allowed only for the 4 Lambda execution role ARNs. Listed explicitly; no wildcards.
- **Key decisions:**
  - **Single fan-out topic over per-severity / per-category topics:** SNS's native model is one topic, many subscribers; routing CRITICAL-only later means a `FilterPolicy` on that subscription, not a second topic. Also keeps the IAM ARN list to one entry per role.
  - **Email-only this STEP, Slack deferred:** Keeps scope small. Slack would require Secrets Manager (not yet built) and an HTTPS subscription with retry policy — a future enhancement, not a STEP 8 requirement.
  - **Topic policy enumerates 4 Lambda role ARNs (not `Principal = "*"` + `aws:PrincipalArn` Condition):** Same defense-in-depth pattern as the S3 reports bucket. `cat topic-policy.json` shows exactly who can Publish. Identity-policy AND resource-policy must both Allow.
  - **`aws_iam_policy_document` data source for the topic policy** (not raw JSON heredoc): type-checked, references variables cleanly, typos surface at plan time. Same pattern used in the KMS and S3 modules.
  - **Email regex validation on the `alert_email` variable:** Catches typos at `plan` time instead of `apply` time when AWS rejects an invalid endpoint format. The regex is intentionally permissive (RFC 5322-strict is impractical and would reject valid edge cases).
  - **No SES hardening in this STEP** (open TODO). SES isn't actually called until the report_generator Lambda (post-STEP 13); scoping `ses:SendEmail` to a verified-identity ARN now would require editing the IAM module without a way to test the change. Deferred to the post-STEP 13 hardening pass.
- **`terraform plan` result:** ✅ `Plan: 33 to add, 0 to change, 0 to destroy.` — 30 prior + 1 SNS topic + 1 subscription + 1 topic policy. No apply (blueprint defers apply to STEP 18).
- **Note on email confirmation:** The first `terraform apply` (STEP 18) will trigger a `Subscription Confirmation` email from AWS. Until the link is clicked, the subscription's `pending_confirmation = true` and no alerts will deliver. This is intentional AWS UX — Terraform cannot self-confirm an email subscription (anti-spam design).

---

### ⬜ STEP 9 — Build the Lambda Terraform Module (Reusable)
### ⬜ STEP 10 — Write the Cost Scanner Lambda
### ⬜ STEP 11 — Write the Security Scanner Lambda
### ⬜ STEP 12 — Write the Resource Cleanup Lambda
### ⬜ STEP 13 — Write the Report Generator Lambda
### ⬜ STEP 14 — Write the Shared Utilities
### ⬜ STEP 15 — Write Unit Tests
### ⬜ STEP 16 — Build the Step Functions Workflow
### ⬜ STEP 17 — Build the EventBridge Terraform Module
### ⬜ STEP 18 — Wire Everything Together in Dev Environment
### ⬜ STEP 19 — Create the Lambda Packaging Script
### ⬜ STEP 20 — Test the System End-to-End
### ⬜ STEP 21 — Build the CI/CD Pipeline
### ⬜ STEP 22 — Add CloudWatch Dashboard
### ⬜ STEP 23 — Write Documentation
### ⬜ STEP 24 — Add Resource Tagging Strategy

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
| 2026-05-15 | Inserted new STEP 6 — Build the KMS CMK Module (renumbered subsequent steps; total 23 → 24) | Interview cred: must demonstrate CMK lifecycle, key policy with `kms:ViaService`, envelope encryption (Definition-of-Done interview Q). Original STEP 5 choice (AWS-managed key) was defensible for dev cost but gives no key policy/audit control. | (a) Leave AWS-managed keys — free, zero config, no audit. (b) Per-service CMKs ($3/month, better blast-radius isolation) — overkill for personal dev. Chose single shared CMK at $1/month. |
| 2026-05-16 | KMS key policy: one `Sid` per consuming service, not one combined statement | Each statement reads as a single purpose. Revoking S3's access later means removing one Sid — no risk of touching the DynamoDB or SNS grant by mistake. | One combined statement with `kms:ViaService` as a list of all 3 — terser but mixes concerns; harder to audit-diff. |
| 2026-05-16 | Lambda grants scoped with `kms:ViaService` Condition | Defense-in-depth: a compromised role can only call KMS *through* the consuming service. A leaked cost-scanner credential cannot call `kms:Decrypt` directly. | No Condition — works, but turns the role into a general KMS principal that can decrypt outside of DynamoDB/S3/SNS pathways. |
| 2026-05-16 | Used `aws_iam_policy_document` data source for the KMS policy, not inline JSON | Type-checked by Terraform, references variables cleanly, surfaces typos at plan time | Raw JSON heredoc — works but loses HCL validation and string-interp clarity |
| 2026-05-16 | `deletion_window_in_days = 30` (maximum) | If the key is scheduled for deletion by mistake, there is a full month to cancel before the material is destroyed. Cost: zero. | 7 days (minimum) — faster cleanup but tight recovery window for a personal project where mistakes are likely |
| 2026-05-16 | `multi_region = false` | Single-region deployment; multi-region CMKs are for cross-region replicas/DR | Multi-region — adds management overhead without a use case here |
| 2026-05-16 | S3 bucket name uniqueness via `bucket_suffix` tfvar, not `random_id` | S3 names are globally unique; suffix produces a deterministic name and avoids forcing IAM to consume the bucket ARN as an output (which would create a module-ordering cycle) | `random_id` — works but name changes on destroy/recreate; account-id suffix — leaks account-id into git |
| 2026-05-16 | Reports bucket name defined once as a `local` in `dev/main.tf`, consumed by both IAM and S3 | Single source of truth — if either module reconstructed the name from inputs, a future format drift would silently break IAM permissions | Reconstruct in each module — concise but fragile |
| 2026-05-16 | Reports bucket = SSE-KMS, logs bucket = SSE-S3 | Log delivery service would need `kms:GenerateDataKey` on the CMK to write to a KMS-encrypted target; access logs contain no payload data — SSE-S3 is AWS's recommended pattern for log destinations | SSE-KMS on logs bucket too — works but adds another grant to the key policy with no security upside |
| 2026-05-16 | Storage class `GLACIER_IR` for 90-day transition (not `GLACIER`/Flexible Retrieval) | Reports may be linked from an audit ticket months later — Flexible Retrieval (hours to restore) blocks that workflow. GLACIER_IR has the same archive pricing with millisecond retrieval. | `GLACIER` Flexible Retrieval — cheaper for write-once-never-read archives, but reports may be opened |
| 2026-05-16 | `Deny aws:SecureTransport = false` on both buckets | Forces HTTPS for every request — explicit deny is uncircumventable, modern SDK default does the same on the happy path | Rely on SDK defaults — works for our code, but no protection against a misconfigured client |
| 2026-05-16 | Reports bucket policy enumerates the 4 Lambda role ARNs (not `Principal = "*"` with Conditions) | Audit trail is one cat away; bucket policy + IAM policy = AND, so leaked credentials outside those 4 roles are blocked at the bucket | `Principal = "*"` + `aws:PrincipalArn` Condition — equally secure but reads worse |
| 2026-05-16 | `bucket_key_enabled = true` on the reports bucket | S3 bucket keys reuse one data key per ~5-min window; ~99% fewer `kms:GenerateDataKey` calls and ~99% lower KMS bill at zero security cost | Per-object KMS calls (default) — wastes money for no benefit |
| 2026-05-16 | Logs-bucket policy scoped with `aws:SourceArn` + `aws:SourceAccount` | Prevents the confused-deputy pattern where any account's S3 logging service could write here | Just allow `logging.s3.amazonaws.com` without source conditions — works, but is the textbook unsafe pattern |
| 2026-05-16 | Single SNS topic over per-severity / per-category topics | SNS's native fan-out model — CRITICAL-only routing later is a subscription `FilterPolicy`, not a second topic. Keeps IAM `local.alerts_topic_arn` to one ARN | Topic per severity (CRITICAL/HIGH/INFO) — works but multiplies IAM grants, KMS conditions, and topic policies for no functional gain at this scale |
| 2026-05-16 | Email-only alert subscription for STEP 8; Slack deferred | Slack drags Secrets Manager (not yet built) and an HTTPS subscription with retry/dead-letter policy into a STEP scoped to SNS. Defer until alert volume justifies the channel | Add Slack subscription now — would close the open TODO but bloat STEP 8's blast radius and force a Secrets Manager mini-STEP |
| 2026-05-16 | SNS topic policy enumerates 4 Lambda role ARNs as Publish principals | Defense-in-depth: identity-policy AND resource-policy must both Allow. Leaked credential outside those 4 roles is rejected at the topic. Audit is one `cat` away | `Principal = "*"` + `aws:PrincipalArn` Condition — equally secure but reads worse and obscures the audit |
| 2026-05-16 | Email regex validation on `alert_email` variable at the module boundary | Fails at `plan` time instead of `apply` time when AWS rejects malformed endpoints — tightens the feedback loop | No validation — Terraform accepts the value and AWS errors during apply, costing a round trip |

---

## Problems Hit & Resolved

| Date | STEP | Problem | Resolution | Lesson |
|------|------|---------|------------|--------|
| 2026-05-14 | STEP 1 | Python 3.12 unavailable | Proceeded with 3.13.7; risk noted | Always pin runtime versions early |
| 2026-05-14 | STEP 2 | Bash in Claude Code resets cwd to git worktree | Use PowerShell for all file/dir ops | PowerShell is reliable; Bash is not in this env |
| 2026-05-14 | STEP 2 | `.terraform.lock.hcl` incorrectly added to `.gitignore` | Removed from gitignore in STEP 3; lock file committed | Lock file = commit; `.terraform/` dir = ignore |
| 2026-05-14 | STEP 3 | Terraform not in Claude Code's PATH at the time | Workaround: user ran terraform in their own terminal. **Corrected STEP 5:** Terraform IS in Claude Code's shell PATH — `terraform plan/init` can run directly. | PATH availability may depend on session startup order; always try directly first |
| 2026-05-14 | STEP 3 | GitHub Actions firing on every push (empty workflow files) | Changed trigger to `workflow_dispatch` until STEP 20 | Stub workflow files need a safe trigger |

---

## Open Questions / TODOs

- [x] Pick alert email address — set in local `terraform.tfvars` during STEP 4
- [ ] Decide Slack vs email-only for alerts (Slack webhook stored in Secrets Manager if used)
- [ ] Confirm free tier limits before STEP 18 (`terraform apply`) — Lambda, DynamoDB, S3 all have free tiers; Step Functions has 4000 free state transitions/month; KMS CMK = $1/month (not free tier)
- [x] **STEP 6 retrofit:** swap STEP 5 DynamoDB tables from `aws/dynamodb` managed key to `module.kms.key_arn` — done in STEP 6 (2026-05-16)
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

- **STEP 6 — Customer-managed KMS key (CMK) vs AWS-managed key:** "AWS-managed keys (`aws/dynamodb`, `aws/s3`, etc.) tick the encrypt-at-rest checkbox but give you zero control. With a CMK I can (a) write a key policy that says *exactly* which principals can Decrypt, (b) see every Decrypt call in CloudTrail under my key's ID, (c) rotate on my own schedule, and (d) revoke access instantly by disabling the key without touching the table or bucket. For a regulated workload you need every one of those — for a personal dev environment, the $1/month is the cost of building the muscle memory before doing it in prod."

- **STEP 6 — Envelope encryption explained:** "Symmetric encryption is fast on large data but you can't safely send the master key around. KMS solves this with envelope encryption: when DynamoDB writes an item, it calls `GenerateDataKey` on my CMK. KMS returns two copies of a fresh data key — one plaintext, one encrypted under the CMK. DynamoDB encrypts the row with the plaintext data key, stores the encrypted data key next to the ciphertext, and immediately discards the plaintext. To read, DynamoDB calls `Decrypt` on the encrypted data key, KMS hands back the plaintext, the row is decrypted, and the plaintext is discarded again. The CMK itself never touches the data — it only ever encrypts and decrypts other (much smaller) data keys. That's why it scales: one CMK can protect petabytes."

- **STEP 6 — Why `kms:ViaService` matters:** "Without the Condition, granting a role `kms:Decrypt` lets it call Decrypt directly against the key from anywhere — Lambda code, CLI, anywhere with credentials. With `kms:ViaService = dynamodb.<region>.amazonaws.com`, the key will only honor Decrypt calls that originate from the DynamoDB service on my behalf. If a cost-scanner credential leaks, the attacker can't just `aws kms decrypt` blobs — they'd have to be coming through DynamoDB, which means they'd already need DynamoDB read on the specific table. It's defense-in-depth at the cryptography layer."

- **STEP 6 — Why the root-account admin statement is non-negotiable:** "KMS key policies are evaluated *in addition to* IAM policies, but if a key policy doesn't grant access, IAM can't override that. If you write a key policy that omits root and accidentally locks out every principal you listed, you have created an unusable key that you also can't delete or modify — Terraform can't fix a policy it doesn't have permission to read. AWS's `bypass_policy_lockout_safety_check` defaults to `false` specifically to prevent this. The root statement is the escape hatch."

- **STEP 6 — Single shared CMK vs per-service CMKs:** "Per-service CMKs are the textbook answer for blast-radius isolation — compromise the DynamoDB key, the S3 bucket is still safe. They cost $1/month per key, so three services = $3/month plus key-policy duplication. For a personal dev project, $1 single shared key is the right trade. In a regulated production deployment — PCI, SOC2, HIPAA — the right call flips: per-service CMKs with tighter policies, possibly per-table or per-bucket, justified by the audit and isolation requirements."
- **STEP 7 — Why S3 bucket names need a suffix:** "S3 bucket names share one global namespace across every AWS account in the world — there is exactly one `cloudguard-dev-reports`, and whoever creates it first owns it. So bucket names need a per-account uniqueness suffix. I put it in a tfvars variable rather than letting the module generate a `random_id`, because a deterministic name means the same Terraform code produces the same bucket on every machine and the IAM policy that references the bucket ARN doesn't break when someone destroys-and-recreates the bucket."

- **STEP 7 — Identity policy vs resource policy (the AND rule):** "An S3 PutObject succeeds only if BOTH the caller's identity policy (their IAM role policy) AND the bucket's resource policy allow it — they're ANDed, not ORed. In CloudGuard the IAM module grants the 4 Lambda roles `s3:PutObject` on the reports bucket, AND the bucket policy enumerates those same 4 role ARNs. If a credential leaks to a fifth identity, the IAM side might be bypassed by an admin policy attached to that identity, but the bucket policy still rejects the write because that identity isn't in the principal list. That's defense-in-depth — two independent gates have to fail."

- **STEP 7 — Why `Deny aws:SecureTransport = false`:** "The condition `aws:SecureTransport = false` is true for any request that arrived over HTTP. An explicit `Deny` on `s3:*` when that condition is true means a plaintext request can't succeed even if every other policy on the bucket would allow it. Modern SDKs default to HTTPS, but `Deny` is uncircumventable — it covers a misconfigured CLI, a curl command someone tries during debugging, a future SDK version that changes its default. The cost is zero, the floor it sets is hard."

- **STEP 7 — How S3 bucket keys reduce KMS spend:** "Without bucket keys, every PutObject calls KMS `GenerateDataKey` to mint a unique data key, encrypts the object with it, and stores the encrypted data key alongside. At scale that becomes a real KMS bill — KMS charges per request, and bucket keys turn ~10,000 KMS calls into ~1. With `bucket_key_enabled = true`, S3 mints one data key per bucket per ~5-minute window and reuses it across uploads in that window. The encryption guarantee is unchanged — every object is still encrypted with a unique data key derived from the bucket key — but the KMS request count drops by roughly 99%."

- **STEP 7 — Confused deputy and `aws:SourceArn`:** "The classic confused-deputy problem: an AWS service can be granted permission to call into your account on someone else's behalf. The S3 logging service principal can write objects — without scoping, any other AWS customer could theoretically configure their bucket to deliver logs to mine. `aws:SourceArn = <my reports bucket ARN>` and `aws:SourceAccount = <my account>` on the Allow statement say: only honor PutObject calls from MY S3 logging service writing logs about MY bucket. AWS recommends this pattern on every service-principal Allow statement."

- **STEP 8 — Why a single SNS topic over per-severity topics:** "SNS is a fan-out service — one topic, many subscribers, with optional per-subscription filter policies. If I split CRITICAL and INFO into two topics, every Lambda needs two `sns:Publish` grants and two ARNs to remember, the KMS key policy needs two `kms:ViaService` Conditions to keep tight, and the topic-policy duplication doubles. The same routing is achievable with a `FilterPolicy` on a single subscription: `{ severity: [\"CRITICAL\"] }` on the on-call Slack subscriber, no filter on the email subscriber. One topic stays the right answer until the producer/consumer fan-out is genuinely heterogeneous — different services with different access patterns — and at that scale the right move is usually EventBridge, not multi-topic SNS."

- **STEP 8 — Why the topic policy enumerates 4 Lambda role ARNs explicitly:** "S3 reports bucket, SNS alerts topic, and (later) the Secrets Manager secret all follow the same rule: identity policy AND resource policy must both allow. The IAM module grants `sns:Publish` on the topic ARN; the topic policy lists those same 4 role ARNs in its Allow statement. A credential leaked outside those 4 roles is rejected at the topic — even if the leaked credential has an `sns:*` IAM policy attached. `Principal = \"*\"` plus an `aws:PrincipalArn` Condition is equivalent in coverage, but the explicit list is what an auditor wants to see — `cat topic-policy.json` answers 'who can publish?' in one read."

- **STEP 8 — Why email subscriptions stay PendingConfirmation:** "By design — Terraform cannot self-confirm an email subscription. If it could, an attacker with Terraform credentials could silently subscribe a victim's inbox to a high-volume topic and use SNS as a spam relay. AWS sends a confirmation email; until the recipient clicks the link (valid for 3 days), the subscription's `pending_confirmation = true` and no messages deliver to that endpoint. Same anti-confused-deputy logic as `aws:SourceArn`/`aws:SourceAccount` on the S3 logging bucket policy — the service refuses to be tricked into delivering somewhere it wasn't explicitly told to."

- **STEP 8 — KMS encryption on SNS and how it links to STEP 6:** "Topic-level SSE-KMS encrypts message bodies at rest. The shared CMK from STEP 6 already had `AllowLambdasViaSNS` Sid with `kms:ViaService = sns.<region>.amazonaws.com` — written ahead of time exactly so STEP 8 wouldn't need to touch the KMS policy. When a Lambda calls `sns:Publish`, SNS calls `kms:GenerateDataKey` on the CMK *on the Lambda's behalf* — the `kms:ViaService` Condition checks that the call's `userAgent`-equivalent path goes through SNS, so a leaked Lambda credential can't directly call `kms:Encrypt` outside the SNS path."

- **STEP 9 (reusable Lambda module — why module vs inline):** _[fill in during STEP 9]_
- **STEP 16 (Step Functions over chained Lambdas):** _[fill in during STEP 16]_
