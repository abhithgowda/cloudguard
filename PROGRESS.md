# CloudGuard — Build Progress Log

> Running log of what's been done, decisions made, and lessons learned.
> Updated at the end of every STEP. Read this at the start of every new session.

---

## Current Status

- **Last completed STEP:** 11 (Write the Security Scanner Lambda)
- **Next up:** STEP 12 (Write the Resource Cleanup Lambda)
- **Last updated:** 2026-05-17
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
*Completed: 2026-05-16 · Commit: `a01bf04`*

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

### ✅ STEP 9 — Build the Lambda Terraform Module (Reusable)
*Completed: 2026-05-16 · Commit: `dc75eeb`*

- **Files written:**
  - `terraform/modules/lambda/main.tf` — `data "archive_file"` + `aws_cloudwatch_log_group` + `aws_lambda_function` with `tracing_config`, `kms_key_arn`, `reserved_concurrent_executions`, `dynamic "environment"` block
  - `terraform/modules/lambda/variables.tf` — 14 inputs with type + range validation: `function_name` (regex), `project`, `environment`, `handler`, `runtime` (default `python3.12`), `role_arn`, `source_dir`, `environment_variables`, `timeout` (1–900, default 300), `memory_size` (128–10240 step 64, default 256), `layers`, `reserved_concurrent_executions` (default 5), `tracing_mode` (default `Active`), `kms_key_arn`, `log_retention_days` (default 30)
  - `terraform/modules/lambda/outputs.tf` — `function_arn`, `function_name`, `function_invoke_arn`, `log_group_name`, `log_group_arn`, `source_code_hash`
- **Files modified (KMS retrofit):**
  - `terraform/modules/kms/main.tf` — added 2 statements to the key policy:
    - `AllowLambdasViaLambda` — Lambda role ARNs get Encrypt/Decrypt/ReEncrypt*/GenerateDataKey*/DescribeKey scoped by `kms:ViaService = lambda.<region>.amazonaws.com` (env-var decrypt at cold start)
    - `AllowCloudWatchLogsEncrypt` — Service principal `logs.<region>.amazonaws.com` gets the encrypt suite scoped by `kms:EncryptionContext:aws:logs:arn` to `arn:aws:logs:<region>:<account>:log-group:/aws/lambda/${project}-${env}-*`
- **Files modified (dev wiring):**
  - `terraform/environments/dev/main.tf` — 4 invocations of the reusable lambda module (cost_scanner, security_scanner, resource_cleanup, report_generator). Each receives its own role ARN, source_dir, env vars wired to DynamoDB/SNS/S3, and the shared CMK. `report_generator` gets `memory_size = 512`, `timeout = 600`. `resource_cleanup` env vars include `AUTO_REMEDIATE = "false"` as a safety rail.
  - `terraform/environments/dev/outputs.tf` — added `lambda_function_arns`, `lambda_function_names`, `lambda_log_group_names` (each a map keyed by scanner)
  - `.gitignore` — added `**/.builds/` for `archive_file` scratch dirs
  - `terraform/environments/dev/.terraform.lock.hcl` — added `hashicorp/archive v2.8.0` (new provider dependency from `data "archive_file"`)
- **Defaults baked into the module (all defensible interview answers):**
  - `runtime = "python3.12"` — matches Lambda runtime (local is 3.13, known gap)
  - `timeout = 300` (5 min), `memory_size = 256` MB — sane for boto3-only workloads
  - `reserved_concurrent_executions = 5` — caps runaway-bill blast radius from a misfiring EventBridge schedule; -1 in caller would disable
  - `tracing_mode = "Active"` — X-Ray on every invocation (free up to 100k traces/month; gives Step Functions per-Lambda timeline)
  - `kms_key_arn` REQUIRED — env vars + log groups both encrypted with the shared CMK
  - `log_retention_days = 30` — long enough to debug, short enough to be free
- **Key decisions:**
  - **Explicit `aws_cloudwatch_log_group` with `depends_on` on the function:** Lambda auto-creates a log group with NO retention and NO encryption on first invocation. If we don't declare it in Terraform, the first apply succeeds, the function runs, CW Logs auto-creates an unmanaged group, and the next apply fails trying to create a group that already exists. Declaring explicitly + `depends_on` on the function forces ordering: log group first (managed, encrypted, retained), function second.
  - **`data "archive_file"` (zip at plan time) vs. a packaging script:** Blueprint STEP 9 says use `archive_file`; STEP 19 will add `scripts/package_lambdas.sh` for `pip install -r requirements.txt` bundling. Both can coexist — `archive_file` zips whatever's in `source_dir`. At STEP 19, the source_dir can point at a pre-populated `package/` folder. Module doesn't need to change.
  - **`dynamic "environment"` block:** AWS only encrypts env vars with the CMK if at least one variable is set. Passing an empty map without the dynamic block creates an empty `environment {}` block, which AWS rejects. The dynamic block removes it entirely when there's nothing to inject.
  - **KMS retrofit shape — Lambda env vars vs CloudWatch Logs are different statement structures:** Lambda env-var decrypt is the Lambda execution role calling Decrypt via the Lambda service → principal is the role ARN, condition is `kms:ViaService`. CloudWatch Logs encryption is the Logs service principal encrypting on its own → principal is `logs.<region>.amazonaws.com`, condition is `kms:EncryptionContext:aws:logs:arn` scoped to our log-group ARN pattern. Two separate Sids because the security models are genuinely different.
  - **Log-group ARN pattern scoped to `${project}-${environment}-*` not `*`:** Without the EncryptionContext condition, the grant would let CloudWatch Logs encrypt ANY log group in the account with this key — including log groups outside CloudGuard. The pattern restricts the grant to log groups under `/aws/lambda/cloudguard-dev-*`. Defense-in-depth at the encryption-context layer.
  - **`reserved_concurrent_executions = 5` default:** A bug in a Lambda + EventBridge retry loop has bankrupted real teams. Capping at 5 means even a runaway scheduler can't spawn 1000 concurrent executions burning Cost Explorer API quota. Caller can raise per-function if needed; the safety rail is "deny by default."
  - **`AUTO_REMEDIATE = "false"` env var on resource_cleanup:** The cleanup Lambda has `ec2:DeleteVolume` + `ec2:ReleaseAddress` — destructive perms. Default false means STEP 12 code will scan and log findings but NOT delete unless overridden (by Step Functions input later). Same belt-and-braces logic as the bucket-policy enumerations: code defaults to safe; explicit action required to enable destruction.
  - **`report_generator` gets 512 MB / 600 s** (vs 256 / 300 default): HTML generation + DynamoDB Scan + S3 PutObject runs on a daily/weekly schedule and shouldn't get timed out mid-report. CPU in Lambda is proportional to memory; 512 MB also speeds up Python startup and the templating loop.
  - **`hashicorp/archive` provider:** New dependency introduced by `data "archive_file"`. `terraform init -upgrade` fetched v2.8.0, lock file updated and committed.
- **`terraform plan` result:** ✅ `Plan: 41 to add, 0 to change, 0 to destroy.` — 33 prior + 4 `aws_lambda_function` + 4 `aws_cloudwatch_log_group`. No apply (blueprint defers apply to STEP 18).

### ✅ STEP 10 — Write the Cost Scanner Lambda
*Completed: 2026-05-17 · Commit: `fbdd001`*

- **Files written:**
  - `src/cost_scanner/handler.py` — Lambda entrypoint. Reads `FINDINGS_TABLE`, `COST_DATA_TABLE`, `ENVIRONMENT` env vars (wired in STEP 9). Calls `get_cost_data` → `store_cost_data` → `detect_anomalies` → `store_findings`. Returns `{anomalies_found, total_daily_cost, services_scanned}`.
  - `src/cost_scanner/cost_analyzer.py` — pure helpers split out so STEP 15 unit tests can mock the boto3 clients and call directly without invoking the Lambda runtime: `get_cost_data`, `detect_anomalies`, `store_cost_data`, `store_findings`, `_severity_for`.
  - `src/cost_scanner/requirements.txt` — `boto3` only (already in the Lambda runtime, but listed for the STEP 19 packaging script).
- **Anomaly detection design:**
  - 30-day daily granularity Cost Explorer pull, grouped by `SERVICE` dimension.
  - Baseline = average of the prior N–1 days (excludes the day being evaluated — otherwise the spike dilutes its own baseline).
  - Threshold = 1.5x. `ratio >= 2.0` → `CRITICAL`, `ratio >= 1.5` → `HIGH` (matches blueprint).
  - Skip services with `len(day_costs) < 2` (brand-new services have no baseline — would false-positive every time).
  - Skip services with `avg_cost <= 0` (no div-by-zero, and "$0 → $5" is a turn-on event, not an anomaly).
- **DynamoDB writes:**
  - `cost-data` table: PK `date`, SK `service_name`, attribute `unblended_cost` (Decimal). Re-running the same day overwrites the row — latest data wins, idempotent for end-of-day re-evaluation.
  - `findings` table: PK `finding_id` (uuid), SK `timestamp` (ISO-8601 UTC), `category = "cost"`, `severity`, `resource_id` (service name), `resource_type = "aws_service"`, `check_name = "cost_anomaly_30d_baseline"`, `description` (human-readable), `expected_cost` / `actual_cost` / `ratio` as Decimal, `expires_at` (epoch seconds, +90 days) for the table's TTL attribute.
  - Both tables written via `table.batch_writer()` context manager — auto-batches up to 25 items and retries unprocessed items.
- **Key decisions:**
  - **Pure helpers in `cost_analyzer.py`, side-effects in `handler.py`:** the helpers take a boto3 client/resource as a parameter — STEP 15 mocks the client with `unittest.mock.Mock()` and asserts call args without ever touching AWS. The handler is the thin shell that initializes real clients and wires env vars; nothing to test there beyond an integration test.
  - **`Decimal(str(amount))`, not `Decimal(amount)`:** DynamoDB rejects Python floats (uses Decimal internally). Converting via `str()` preserves the textual precision Cost Explorer sends; `Decimal(0.1)` would produce `Decimal('0.1000000000000000055511151231257827021181583404541015625')` which is correct but ugly in the table.
  - **Pagination via `NextPageToken` loop, not `paginate`:** Cost Explorer's `get_cost_and_usage` uses a non-standard pagination key (`NextPageToken` rather than `NextToken`) so the standard `client.get_paginator()` doesn't apply. Hand-roll the loop; same shape as AWS examples.
  - **`finding_id = uuid.uuid4()` per anomaly per run (not deterministic):** Blueprint specifies uuid. Means re-running the scanner on the same anomaly creates duplicate findings — TTL cleans up at 90 days. A deterministic key like `(date, service_name)` would be idempotent but the blueprint says uuid, so I'm following the blueprint. Trade-off acknowledged.
  - **No SNS publish from this Lambda:** Blueprint puts notification in the Report Generator (STEP 13). Cost scanner only writes to DynamoDB. The `SNS_TOPIC_ARN` env var wired in STEP 9 is unused here — left in place for future use, cheap.
  - **`logger.setLevel(logging.INFO)` at module load:** Lambda's default log level is WARNING. Setting INFO at module init means scanner progress shows up in CloudWatch by default; can be downgraded to WARNING via env var later if it gets noisy.
- **Local sanity testing:** `python -c "import handler; import cost_analyzer"` passes. `detect_anomalies()` smoke-tested with 5 synthetic services covering anomaly, no-anomaly, single-day, zero-baseline, and CRITICAL-vs-HIGH severity paths — all produced the expected output. Real unit tests are STEP 15.
- **Known gap — local Python 3.13 vs Lambda 3.12:** carried forward from STEP 1. Code uses no 3.13-only syntax. Will validate via Lambda runtime on the first STEP 18 apply.


### ✅ STEP 11 — Write the Security Scanner Lambda
*Completed: 2026-05-17 · Commit: `c16a9e2`*

- **Files written:**
  - `src/security_scanner/handler.py` — Lambda entrypoint. Reads `FINDINGS_TABLE` env var, initializes ec2/s3/iam/dynamodb clients, calls all 4 checkers, stamps `finding_id`/`timestamp`/`expires_at`, batch-writes to DynamoDB. Returns `{total_findings, by_severity, by_check}`.
  - `src/security_scanner/sg_checker.py` — `check_security_groups(ec2_client)`. Severity ladder: `0.0.0.0/0` on all-traffic or SSH(22)/RDP(3389) → CRITICAL; on any other non-80/443 port → HIGH; on 80/443 → skipped (legitimate web). Handles IPv6 `::/0` and the all-protocol sentinel (`IpProtocol = "-1"`).
  - `src/security_scanner/s3_checker.py` — `check_s3_buckets(s3_client)`. 4 sub-checks per bucket: public access block disabled (HIGH), no default encryption (HIGH), `Principal = "*"` in policy (CRITICAL), versioning disabled (LOW). Each per-bucket API wrapped in try/except so one bad bucket can't kill the scan.
  - `src/security_scanner/iam_checker.py` — `check_iam_users(iam_client)`. Per user: access keys > 90d old (MEDIUM), keys unused 90+ days (MEDIUM), no MFA (HIGH), AdministratorAccess attached directly (HIGH).
  - `src/security_scanner/ebs_checker.py` — `check_ebs_encryption(ec2_client)`. **Added beyond literal blueprint spec** — STEP 11 `lambda_handler` lists `check_ebs_encryption()` in its orchestrator but the blueprint did not give it a dedicated file/spec. Severity: unencrypted in-use volume → HIGH, available volume → MEDIUM.
  - `src/security_scanner/requirements.txt` — `boto3` only.
- **Files modified (IAM retrofit):**
  - `terraform/modules/iam/main.tf` — security_scanner role: combined `EC2SecurityGroupsRead` into `EC2SecurityReadOnly` adding `ec2:DescribeVolumes` for the EBS check. Both are Describe* (no resource-level perms possible), so single statement.
- **`terraform plan` result:** ✅ `Plan: 41 to add, 0 to change, 0 to destroy.` — same shape as STEP 9 (nothing applied yet, so the retrofit just changes JSON inside a not-yet-created inline policy). No apply (blueprint defers to STEP 18).
- **Local smoke test:** All 5 modules import cleanly under venv (Python 3.13.7). Synthetic-data run of `check_security_groups` with 5 fake SGs produced exactly the expected 3 findings (CRITICAL all-open, CRITICAL ssh-open, HIGH postgres-open), correctly skipping port-80 public and the internal-10.x SG. Real unit tests are STEP 15.
- **Key decisions:**
  - **One file per resource type (`sg_checker.py`, `s3_checker.py`, `iam_checker.py`, `ebs_checker.py`) + thin handler:** Same pattern as STEP 10's pure-helpers split. Each checker takes its boto3 client as a parameter, so STEP 15 mocks the client and asserts call args without ever touching AWS. The handler is just orchestration + stamping + batch-write — nothing to unit-test there.
  - **Per-resource try/except inside each checker:** Without it, one bucket the scanner can't read (e.g. cross-account ACL block) aborts the entire S3 check. The wrap-and-log pattern keeps the scan running over all the buckets/users/volumes that DO succeed and surfaces the failures in CloudWatch logs.
  - **`finding_id`/`timestamp`/`expires_at` stamped centrally in the handler:** Checkers return "raw" findings — fields the checker knows (resource_id, severity, etc.). Handler adds the cross-cutting fields. Keeps checkers pure and matches the schema invariant across all categories (cost + security + cleanup): same handler responsibility, every Lambda.
  - **CRITICAL threshold on SSH/RDP, HIGH on other public-non-80/443:** Matches blueprint, matches real risk model. SSH-open-to-world is the textbook lateral-movement entry. Other public TCP ports are still wrong but rarely interactive shell access.
  - **EBS check beyond literal spec (recommended option, user-confirmed):** Blueprint's STEP 11 lambda_handler explicitly calls `check_ebs_encryption()` but section 4 does not give it dedicated file detail. Two choices: skip and leave the handler broken, or build it. Built it, with the matching IAM retrofit, because it's a high-value security check (EBS-at-rest encryption is a SOC2/PCI control) and the cost is one file plus one extra Describe action.
  - **`metadata` dict only when non-empty:** DynamoDB rejects empty maps in some paths; popping the key when there's nothing to add keeps the item schema lean. Cost-scanner findings did the same (no metadata field at all).
  - **`logger.setLevel(logging.INFO)` at module load:** Same default as cost_scanner — surfaces per-check counts in CloudWatch by default; can be turned down later.
- **Open TODO (carried, not regressed):**
  - Scope `ses:SendEmail` to verified-identity ARN (from STEP 7).
  - Scope `ec2:DeleteVolume`/`ec2:ReleaseAddress` with tag-based Condition (from STEP 4).

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
| 2026-05-16 | Lambda module — declare `aws_cloudwatch_log_group` explicitly with `depends_on` on the function | Lambda auto-creates a log group with no retention and no encryption on first invocation; explicit declaration is the only way to set retention + KMS, and the dependency ordering prevents a "log group already exists" failure on the second apply | Let Lambda auto-create the log group — fails our encryption requirement and our 30-day retention requirement |
| 2026-05-16 | Default `reserved_concurrent_executions = 5` on every Lambda | A misfiring EventBridge schedule + retry loop is the textbook runaway-bill scenario for serverless; capping concurrency is cheap insurance. Caller can raise per-function | Unbounded (Lambda default) — works fine until it doesn't; the cost of being wrong is real money |
| 2026-05-16 | X-Ray active tracing on by default | Free up to 100k traces/month; gives Step Functions execution graphs a per-Lambda timeline; trivial to demo in interview | `PassThrough` (only trace when called from a traced upstream) — saves nothing since we're under the free tier and lose visibility |
| 2026-05-16 | Encrypt Lambda env vars AND CloudWatch log groups with the shared CMK | Env vars often hold table names + topic ARNs which are not secrets but ARE infrastructure intel; log groups can leak request payloads. Both at-rest with the CMK = same audit/rotation/revocation story as DynamoDB/S3/SNS. Required two new statements in the KMS policy (different shapes for the Lambda role grant vs the CW Logs service grant) | Leave Lambda env vars + log groups on the AWS-managed default — works, costs nothing, but breaks the "everything under one auditable CMK" story that's the whole point of STEP 6 |
| 2026-05-16 | CloudWatch Logs grant in KMS policy scoped by `kms:EncryptionContext:aws:logs:arn` ArnLike pattern | Without the EncryptionContext condition, the grant lets CloudWatch Logs encrypt any log group in the account with our CMK. Restricting to `/aws/lambda/${project}-${env}-*` keeps the grant scoped to CloudGuard's Lambdas only | No EncryptionContext condition — works, but the grant is overly broad; same shape Checkov would flag |
| 2026-05-16 | `data "archive_file"` in the module (not a packaging-script-only flow) | Blueprint STEP 9 spec; gives Terraform a `source_code_hash` driver so code changes flow into plans without manual zip steps; coexists with the STEP 19 packaging script which can pre-populate a `package/` source_dir | Skip archive_file, rely entirely on the STEP 19 bash script — works but Terraform can't tell when code changed and won't update the function on `apply` unless the script ran first |
| 2026-05-16 | `dynamic "environment"` block on `aws_lambda_function` | AWS rejects an empty `environment {}` block; passing an empty map to a static block would error. Dynamic block omits the block entirely when no env vars | Always emit the block — fails for functions that legitimately have no env vars |
| 2026-05-16 | `AUTO_REMEDIATE = "false"` env var on resource_cleanup Lambda | Cleanup role has `ec2:DeleteVolume`/`ec2:ReleaseAddress` — destructive. Defaulting to dry-run mode means the function will scan and log findings but NOT delete until an explicit override (Step Functions input later) flips it. Belt-and-braces with the role-level Condition TODO | Default to true — IAM allows it, role is built for it. Rejected: a code bug shouldn't be able to release every EIP in the account. |
| 2026-05-17 | Cost scanner: pure helpers (`cost_analyzer.py`) + thin handler (`handler.py`) | Helpers take boto3 client as a parameter — STEP 15 mocks the client and tests logic without an AWS call. Handler is the wiring shell, nothing to test there | Single-file Lambda — simpler but every helper test would need to patch module-level `boto3.client(...)` initialization order |
| 2026-05-17 | Baseline = average of prior N–1 days, exclude the day being evaluated | Including today in its own baseline dilutes the spike (a 5x spike on day 30 with 29 days of $1 baseline still has avg $1.13, ratio drops from 5.0 to 4.4 — minor here but breaks at higher cardinality) | Include all days in baseline — simpler arithmetic, but a self-diluting signal |
| 2026-05-17 | Skip services with `len(day_costs) < 2` or `avg_cost <= 0` | Brand-new services or those at $0 baseline would either fail with div-by-zero or false-positive every first scan after enablement | Treat as anomaly when first non-zero spend appears — useful signal but high noise; can revisit when SNS routing has filters |
| 2026-05-17 | `uuid.uuid4()` finding_id over deterministic `(date, service_name)` | Blueprint specifies uuid. Duplicates on re-run cleaned up by 90-day TTL | Deterministic id `cost-<date>-<service>` — idempotent but deviates from blueprint |
| 2026-05-17 | `Decimal(str(amount))` not `Decimal(amount)` for DynamoDB | DynamoDB rejects floats; `str()` preserves Cost Explorer's textual precision and keeps the stored value human-readable | `Decimal(amount)` — produces ugly binary-float precision artifacts in the table |
| 2026-05-17 | Security scanner: one file per resource type (sg/s3/iam/ebs) + thin handler | Same pure-helpers-with-injected-client pattern as STEP 10. Each checker is mockable in STEP 15 without moto; handler is just orchestration. Adds a small fan-out cost in file count but keeps each file under 200 lines and single-responsibility | Single-file scanner — simpler, but every check shares boto3 state and every unit test patches module-level globals |
| 2026-05-17 | Per-resource try/except inside each checker | One unreadable bucket / one IAM user we can't introspect must not abort the whole scan. Wrap-and-log keeps the scan going over the successful resources and surfaces failures in CloudWatch | No wrapping — simpler code, but one cross-account-blocked bucket kills the entire S3 check on every scheduled run |
| 2026-05-17 | Stamp `finding_id`/`timestamp`/`expires_at` centrally in the handler, not in each checker | Checkers stay pure (resource_id + severity + check_name + description). Handler owns the cross-cutting schema invariant — same shape across cost / security / cleanup categories | Stamp inside each checker — duplicates the same 4 lines per checker; schema drift if one checker forgets a field |
| 2026-05-17 | Added EBS encryption checker + retrofitted IAM with `ec2:DescribeVolumes` (beyond literal blueprint spec) | Blueprint STEP 11 lambda_handler lists `check_ebs_encryption()` but doesn't give it a dedicated file/spec. Building it costs 1 file + 1 Describe action; skipping it leaves the handler call broken and drops a SOC2/PCI-relevant check | (a) Skip entirely — handler call would 404. (b) Stub with NotImplementedError — handler would 500 in production. Building it is the honest read of the blueprint |

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

- **STEP 9 — Why a reusable Lambda module instead of 4 inline blocks:** "Four functions, same shape: a zip, a log group, the function itself, identical IAM/KMS wiring. Inlining means changing five things in five places when (not if) we add tracing, change retention, or rotate to a new runtime. A module makes 'add a Lambda' a 10-line call. The other reason is testability — a module's variables.tf is a typed interface, with regex validation on function_name and range validation on memory_size, so a typo at the call site fails at `terraform plan` instead of `terraform apply`."

- **STEP 9 — Why declare the CloudWatch log group in Terraform when Lambda auto-creates one:** "Lambda's auto-created log group has the worst defaults possible: no retention (logs live forever, billing forever) and no encryption (CloudWatch's default key, not yours). If you declare the log group explicitly with `retention_in_days = 30` and `kms_key_id = <CMK>`, you control both. The catch is ordering — if the function runs first, the auto-created group already exists and your Terraform resource conflicts with it. The fix is `depends_on = [aws_cloudwatch_log_group.lambda]` on the function — log group created first, function second, no race."

- **STEP 9 — `reserved_concurrent_executions` and why default to a low cap:** "Lambda's default is unbounded concurrency up to the account limit (1000+). A bug in an EventBridge schedule retry loop — say a Lambda that fails fast and triggers a `States.ALL` retry every second — can spawn hundreds of concurrent executions burning Cost Explorer API quota and writing to DynamoDB at full PAY_PER_REQUEST cost. Capping at 5 by default means the worst case is bounded to 5 concurrent executions per function. Production functions that legitimately need more concurrency can override; the safety rail is 'deny by default, raise on demand.'"

- **STEP 9 — X-Ray active tracing trade-off:** "Active tracing samples every invocation and emits trace segments to X-Ray. Free up to 100k traces/month — for a system that scans every 6 hours, that's roughly 4 scans × 4 Lambdas × 30 days = 480 traces a month, two orders of magnitude under the free tier. The benefit in the interview demo is the Step Functions execution graph: you click a parallel branch and see Cost Explorer pagination took 800ms, DynamoDB BatchWrite took 200ms — a real per-Lambda timeline. PassThrough only traces when called from a traced upstream — for ad-hoc invocations or initial development that's a worse default."

- **STEP 9 — Encrypting Lambda env vars + log groups with the same CMK as DynamoDB/S3/SNS:** "Env vars carry table names, topic ARNs, bucket names — not secrets, but infrastructure intel that an attacker reading them learns the shape of your data plane from. Log groups carry request payloads, AWS API responses, and sometimes accidental PII from misconfigured logging. Both go to the shared CMK so they sit under the same audit/rotation/revocation story as the data tables. Disable the CMK and the entire stack is read-protected as one unit — that's the architectural invariant STEP 6 was set up to give us."

- **STEP 9 — Two different KMS policy statement shapes for Lambda vs CloudWatch Logs:** "Lambda env-var decrypt is the function's execution role calling Decrypt via the Lambda service — so the principal is the role ARN and the Condition is `kms:ViaService = lambda.<region>.amazonaws.com`. CloudWatch Logs encryption is the Logs service principal doing its own encrypt on log events — the principal is `logs.<region>.amazonaws.com` and the Condition is `kms:EncryptionContext:aws:logs:arn` matching the log group ARN. Two statements, two different security models, both expressing 'this key can only be used by THIS service for THESE resources.'"

- **STEP 9 — Why dry-run-by-default on the resource cleanup Lambda:** "The cleanup role has `ec2:DeleteVolume` and `ec2:ReleaseAddress` — anything wrong with the scan logic could release every EIP and delete every available EBS volume in the account. The IAM hardening TODO is to scope those actions with a `Condition: ec2:ResourceTag/AutoCleanup = true`, but that requires tagging discipline we don't have yet. In the meantime: `AUTO_REMEDIATE = false` env var. Code scans, logs findings, sends SNS alerts — but doesn't actually delete. Step Functions input later can flip the flag to enable destruction once we trust the detection logic. Same defense pattern as the `Deny aws:SecureTransport = false` on S3: rely on multiple independent gates, default to safe."
- **STEP 10 — Why split `handler.py` from `cost_analyzer.py`:** "The handler is the I/O boundary — it reads env vars, builds boto3 clients, returns the Lambda response. The analyzer is pure logic — it takes a client as a parameter, takes a dict in, returns a dict out, never touches the environment. That split is what makes the logic testable: in STEP 15 I pass a `Mock()` for the boto3 client and assert exactly what `get_cost_and_usage` was called with, without ever needing AWS credentials or moto. Single-file Lambdas are simpler when there's no logic worth testing — for anything with branching, split."

- **STEP 10 — Why exclude the day being evaluated from its own baseline:** "If you average N days and compare day N against that average, the day's own value pulls the baseline toward itself. A genuine spike looks smaller than it is — the bigger the spike, the more the average is dragged up, the smaller the apparent ratio. Comparing day N against the average of days 1..N-1 keeps the baseline independent of the value under test. Same reason rolling forecasts in finance use trailing windows, not centered ones."

- **STEP 10 — Why `PAY_PER_REQUEST` table writes use `batch_writer()`:** "DynamoDB's `PutItem` is one request per item — 30 services × 30 days = 900 PutItem calls for the cost-data write alone. `batch_writer()` is a client-side context manager that buffers up to 25 items per `BatchWriteItem` call, automatically flushes when full, and retries any unprocessed items returned in the response. Same data, ~36 API calls instead of 900. On a PAY_PER_REQUEST table, every write is billed at the same per-request rate either way, but the throughput and the latency improve by an order of magnitude."

- **STEP 10 — Why floats become Decimal before going to DynamoDB:** "DynamoDB's number type is an arbitrary-precision decimal — it explicitly rejects Python floats because float-to-decimal conversion introduces binary-precision artifacts (`Decimal(0.1)` is not `0.1`). The boto3 SDK enforces this. The fix is `Decimal(str(amount))` — convert to a string first, then to Decimal, so the value the API sent (e.g. `'1.2345'`) becomes the exact value stored in the table. It's a small detail but it's the kind of thing that gets caught in code review when someone notices `1.0000000000000000055` in a cost report."

- **STEP 11 — Why split each checker into its own file:** "Same logic as the cost scanner split: each checker takes its boto3 client as a parameter and returns a list of finding dicts. The handler is the I/O boundary — env vars, real clients, DynamoDB batch write. The checkers are pure logic. That gives unit tests a single seam: pass in a `Mock()` for the client, assert the call args, assert the returned findings. The alternative — one monolithic Lambda — works but every test ends up patching module-level boto3 initialization, which is fragile and hides what's actually being verified."

- **STEP 11 — Why CRITICAL on SSH/RDP open to the world, HIGH on other public ports:** "SSH on port 22 and RDP on 3389 are the most common initial-access vectors for compromised AWS accounts — they're interactive shells, so a successful brute-force or credential-stuffing attack gives you an immediate command line. Verizon's DBIR has them at the top of cloud-breach root causes every year. Other ports open to 0.0.0.0/0 (Postgres on 5432, Mongo on 27017, etc.) are still wrong, but they require an additional exploitation step beyond authentication. The severity ladder reflects that — CRITICAL for direct shell paths, HIGH for the rest."

- **STEP 11 — Per-resource try/except around each AWS call:** "If `get_bucket_encryption` raises on one bucket — say cross-account ACL blocks our read — and we don't catch it, the entire S3 check aborts. That's the textbook 'one bad apple' failure mode. The pattern is: wrap each per-resource call, log the failure to CloudWatch so it's visible, return None from the inner function, continue with the next bucket. The scan always completes; failures are surfaced; the operator decides what to do about the unreadable resource. This is the same defensive pattern you'd apply to any batch-of-N pipeline where one item shouldn't kill the run."

- **STEP 11 — Why I added EBS encryption check beyond the literal blueprint:** "Blueprint section 4 lists `check_ebs_encryption()` in the `lambda_handler` orchestrator, but the per-checker spec section doesn't include EBS — that's an inconsistency in the blueprint. The honest read is that the author intended it but forgot the per-file detail. Two ways to handle that: skip the call and leave a broken orchestrator, or build the checker. I built it because EBS-at-rest encryption is a SOC2 control and PCI 3.4 requirement, and the cost was one file plus one extra `ec2:DescribeVolumes` action in the IAM role. The retrofit pattern is the same one we used in STEP 6 (DynamoDB → KMS) — flag the gap, propose the fix, get confirmation, retrofit, plan."

- **STEP 16 (Step Functions over chained Lambdas):** _[fill in during STEP 16]_
