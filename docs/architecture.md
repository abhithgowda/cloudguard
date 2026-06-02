# CloudGuard — Architecture

This document explains every component of CloudGuard, how data flows through the
system, and the design decisions (with trade-offs) behind the build. Where the
implementation deviates from the original project blueprint, the deviation and
its reasoning are called out explicitly.

For a high-level picture and the ASCII diagram, see the
[README](../README.md#architecture-as-built). For operational procedures, see
the [runbook](runbook.md).

---

## 1. System overview

CloudGuard has two independent execution flows:

1. **The scan flow** — every 6 hours, EventBridge starts a Step Functions state
   machine that runs three scanner Lambdas in parallel. Each writes its findings
   to DynamoDB and returns. The scan flow produces **no email** — it is silent
   by design.
2. **The report flow** — on its own daily and weekly schedules, EventBridge
   invokes the report-generator Lambda directly. It reads the accumulated
   findings/cost/remediation data from DynamoDB, builds an HTML report, stores
   it in S3, and notifies a human via SES + SNS.

Everything is encrypted at rest with a single shared customer-managed KMS key,
deployed by Terraform, and shipped by a GitHub Actions OIDC pipeline.

---

## 2. Components

### IAM (`terraform/modules/iam`)

Four IAM roles — **one per Lambda** — each with a tightly-scoped inline policy
plus the AWS-managed `AWSLambdaBasicExecutionRole` for CloudWatch Logs.

- **cost_scanner** — `ce:GetCostAndUsage`/`GetCostForecast`, `dynamodb:PutItem`
  on the cost-data + findings tables, `sns:Publish` on the alerts topic.
- **security_scanner** — read-only describe/list across EC2 SGs, S3 bucket
  config, IAM users/keys, EBS, and Config; `dynamodb:PutItem` on findings.
- **resource_cleanup** — EC2 describe for EBS/EIP/snapshots, plus the three
  **destructive** actions (`DeleteVolume`, `ReleaseAddress`, `DeleteSnapshot`)
  which are **gated on an `ec2:ResourceTag/AutoCleanup = "true"` condition**
  (STEP 18.5 hardening — the third remediation gate). DynamoDB writes to
  findings + remediation-log.
- **report_generator** — DynamoDB read on all three tables, `s3:PutObject`/
  `GetObject` on the reports bucket, `sns:Publish`, and `ses:SendEmail` scoped
  to the **single verified sender identity** via the resource ARN **and** a
  `ses:FromAddress` condition (STEP 18.5).

Resource ARNs are built from the deterministic naming convention
(`${project}-${environment}-…`), so the IAM module and the resource modules
agree on names without a dependency cycle. Actions that genuinely don't support
resource-level permissions (`ce:*`, `ec2:Describe*`, `iam:List*`) use
`Resource = "*"` — documented inline.

### KMS / encryption (`terraform/modules/kms`)

A **single shared customer-managed CMK** (`alias/cloudguard-dev`) provides
envelope encryption for the DynamoDB tables, the S3 reports bucket, the SNS
topic, and the CloudWatch log groups. Configured with:

- `enable_key_rotation = true` (annual automatic rotation)
- `deletion_window_in_days = 30` (max recovery window)
- A key policy granting the root account admin, the four Lambda roles
  encrypt/decrypt scoped by `kms:ViaService` (dynamodb/s3/sns per service), the
  two GitHub OIDC roles (so CI plan/apply can refresh- and apply-encrypt Lambda
  env vars), and the `cloudwatch.amazonaws.com` principal (so alarms can publish
  to the encrypted SNS topic — STEP 22).

### DynamoDB (`terraform/modules/dynamodb`)

Three tables, all **PAY_PER_REQUEST**, all **PITR-enabled**, all **SSE-KMS** with
the shared CMK:

| Table | PK | SK | GSIs | TTL |
|---|---|---|---|---|
| `findings` | `finding_id` | `timestamp` | `severity-index`, `category-index` | `expires_at` (90d) |
| `cost-data` | `date` | `service_name` | — | — |
| `remediation-log` | `remediation_id` | `timestamp` | `status-index` | — |

`finding_id` is a **deterministic hash**, not a UUID (see
[de-duplication](#finding-de-duplication-step-215)). The GSIs let the report
generator and operators query by severity / category / remediation status
without a full table scan. TTL on `findings` auto-expires stale findings after
90 days with no cleanup job.

### S3 (`terraform/modules/s3`)

Two buckets:

- **Reports bucket** — SSE-KMS (shared CMK, `bucket_key_enabled` to cut KMS API
  calls ~99%), versioning on, **all four public-access-block settings true**,
  lifecycle (transition to `GLACIER_IR` at 90d, expire at 365d, plus noncurrent-
  version cleanup and multipart-upload abort), access logging to the logs bucket,
  and a bucket policy that (a) **denies any non-TLS request** and (b) allows only
  the four Lambda roles to read/write. This is defense-in-depth on top of IAM.
- **Logs bucket** — receives the reports bucket's access logs. **SSE-S3 (AES256),
  not KMS** — the S3 logging service principal would otherwise need an extra
  `kms:GenerateDataKey` grant for little security upside (logs carry request
  metadata, not payload). Its policy scopes log delivery to this account's
  reports bucket via `aws:SourceArn` + `aws:SourceAccount`.

### SNS (`terraform/modules/sns`)

A single `cloudguard-dev-alerts` topic, KMS-encrypted, with an email
subscription (stays *pending* until the recipient clicks the AWS confirmation
link). The four Lambda roles get `sns:Publish`; CloudWatch alarms get a
`SourceArn`-scoped (`alarm:cloudguard-dev-*`) Publish grant (STEP 22).

### Lambda (`terraform/modules/lambda` — reusable, invoked 4×)

A single reusable module zips a source directory (`archive_file`), creates the
function, and creates a CMK-encrypted CloudWatch log group with 30-day
retention. Each invocation gets least-privilege role wiring, CMK-encrypted env
vars, `reserved_concurrent_executions = 5` (caps runaway-bill blast radius), and
**X-Ray active tracing** (for an end-to-end timeline through Step Functions).

| Function | Memory | Timeout | Role |
|---|---|---|---|
| cost_scanner | 256 MB | 300 s | cost_scanner_role |
| security_scanner | 256 MB | 300 s | security_scanner_role |
| resource_cleanup | 256 MB | 300 s | resource_cleanup_role |
| report_generator | **512 MB** | **600 s** | report_generator_role |

The report generator gets more memory (CPU scales with it) and time because HTML
generation + S3 upload + SES/SNS happen in one invocation. Each function's
deploy artifact lives in `src/<fn>/build/`, populated by the packaging script —
the `build/` directory holds the function's own `.py` files **plus a copy of
`src/shared/`** so `from shared.dynamo_client import …` resolves at runtime.

### Step Functions (`terraform/modules/step-functions`)

A **STANDARD** state machine: a single `ParallelScanners` state with three
branches (cost / security / cleanup). Each branch has `Retry` (MaxAttempts=2,
BackoffRate=2.0) and `Catch → Pass`, so **a single scanner failure does not
abort the workflow** — the failed branch emits `{"status":"FAILED","scanner":…}`
and the execution still succeeds. The ASL is authored as an HCL object +
`jsonencode()` (validated at plan time). Execution logs go to a CMK-encrypted
`/aws/vendedlogs/states/…` log group; X-Ray tracing is on.

The blueprint's `GenerateReport` task was **removed** from this workflow in
STEP 17.5 — see [report cadence](#report-cadence-redesign-step-175).

### EventBridge (`terraform/modules/eventbridge`)

Three scheduled rules:

| Rule | Schedule | Target | Input |
|---|---|---|---|
| scan_schedule | `rate(6 hours)` | Step Functions | `{auto_remediate: false, …}` |
| daily_report | `cron(30 2 * * ? *)` (08:00 IST) | report Lambda | `{report_window_hours: 24}` |
| weekly_report | `cron(30 2 ? * MON *)` (Mon 08:00 IST) | report Lambda | `{report_window_hours: 168}` |

The SFN target uses an **IAM role** (`states:StartExecution`, scoped to the one
state-machine ARN). The Lambda targets use **resource-based** `aws_lambda_permission`
(scoped by `SourceArn` to each rule + `SourceAccount` against confused-deputy) —
because EventBridge→Lambda direct invocation is authorized by the function's
resource policy, not an IAM role. Each rule can be disabled (not destroyed) via
its `*_rule_enabled` toggle.

### CloudWatch (`terraform/modules/cloudwatch`)

One dashboard (`cloudguard-dev`, 5 widgets: Lambda invocations / errors /
duration avg+p99, SFN executions, DynamoDB consumed capacity) and **9 alarms**,
all → the alerts SNS topic:

- **4 × error-rate** — `(Errors/Invocations)*100 ≥ 5%` via metric math
  (`treat_missing_data = notBreaching` so an idle scanner stays quiet).
- **4 × duration** — `Maximum` duration `> 80%` of each function's timeout
  (per-function thresholds: 240,000 ms for the scanners, 480,000 ms for reports).
- **1 × SFN ExecutionsFailed ≥ 1** — fires only on a *genuine* unhandled failure,
  not a caught scanner-branch failure (which still succeeds the execution).

### GitHub OIDC (`terraform/modules/github_oidc`)

An IAM OIDC provider plus two roles assumed by GitHub Actions via federation —
no long-lived keys in GitHub:

- **plan role** — `ReadOnlyAccess` + state-bucket write; used by CI.
- **deploy role** — `AdministratorAccess`; trust policy pins `sub` to
  `repo:<org>/<repo>:ref:refs/heads/main`, so **only push-to-main runs** can
  assume it. The branch-scoped trust policy *is* the security boundary, not the
  (mutable) workflow file.

---

## 3. Data flow

### Scan flow (every 6 h, silent)

```
EventBridge scan_schedule
  → StartExecution on the state machine, input {auto_remediate:false}
    → ParallelScanners:
        cost_scanner:     Cost Explorer → detect anomalies → cost-data + findings
        security_scanner: EC2/S3/IAM/EBS/Config checks     → findings
        resource_cleanup: EC2 EBS/EIP/snapshot zombies      → findings (+ remediation-log;
                          dry-run unless all gates pass)
    → execution ends; NO email
```

Each scanner stamps findings with a **deterministic `finding_id`**, so a re-scan
of the same real-world issue updates the existing row (`last_seen`,
`occurrence_count`) instead of inserting a duplicate.

### Report flow (daily 24 h / weekly 168 h)

```
EventBridge daily_report | weekly_report
  → InvokeFunction report_generator, input {report_window_hours: 24|168}
    → Scan findings WHERE last_seen ≥ cutoff (OR timestamp ≥ cutoff for legacy rows)
    → Scan remediation-log WHERE timestamp ≥ cutoff
    → Scan cost-data for last 30 days
    → build HTML report (html_builder)
    → S3 put_object (SSE-KMS) → generate_presigned_url (7-day max)
    → SES send_email (summary + link)   ┐ both failures are caught + logged,
    → SNS publish (summary + link)       ┘ not re-raised — the S3 object is durable
```

---

## 4. Design decisions & trade-offs

### Step Functions instead of chaining Lambdas with SNS/SQS

Step Functions gives **declarative orchestration with built-in retry, catch, and
parallelism**, plus a visual execution history that is invaluable for 2-AM
debugging. Chaining Lambdas through SNS/SQS would scatter the control flow across
queues and dead-letter configs, with no single place to see "what ran, what
failed, what retried." STANDARD (not EXPRESS) workflows were chosen: CloudGuard
runs every 6 hours (not high-TPS), needs full execution history, and bills per
state transition (~600/mo, well under the 4,000 free).

### One IAM role per Lambda (not a shared role)

Least privilege and blast-radius isolation. If the cost scanner is compromised,
the attacker gets Cost Explorer read — not the cleanup role's EC2 delete
permissions. A shared role would mean every function carries every other
function's permissions. The cost is four roles to maintain; the benefit is that
each function's exact authority is auditable in one place.

### Single shared CMK vs. per-service CMKs

One CMK at ~$1/mo covers DynamoDB + S3 + SNS + logs. Per-service keys would cost
~$1 each and improve blast-radius isolation (compromise one, the others survive),
but for a personal dev account that isolation isn't worth 3× the cost. In a
regulated production setup, per-service CMKs with tighter key policies are the
better call. **Why a CMK at all over AWS-managed keys:** the CMK lets us write a
key policy restricting Decrypt, audit every Decrypt in CloudTrail, rotate on our
schedule, and revoke by disabling the key — none of which AWS-managed keys offer.

### DynamoDB PAY_PER_REQUEST instead of provisioned

CloudGuard's writes are **spiky and low-volume** — a burst every 6 hours, nothing
in between. Provisioned capacity would mean paying for idle RCUs/WCUs 24/7 or
fiddling with autoscaling. PAY_PER_REQUEST bills per actual request and costs
effectively nothing at this volume. At sustained high throughput, provisioned
becomes cheaper — not the case here.

### Finding de-duplication (STEP 21.5)

Originally each finding got a UUID `finding_id`, so the 6-hourly scanner inserted
a fresh row for the *same* real-world issue every run — a daily report showed ~50
findings for ~14 actual issues (each duplicated ~4×). The fix:
`finding_id = sha256(category|resource_id|check_name)[:32]`, deterministic, and
an **upsert** path (Query by PK → UpdateItem if present, else PutItem). This
mirrors AWS Security Hub's `FirstObservedAt`/`LastObservedAt` model: the SK
(`timestamp`) is the immutable first-seen; `last_seen` and `occurrence_count` are
bumped on re-sight. Trade-off: one Query + one Put/Update per finding instead of
a batched `BatchWriteItem` — a rounding error at ~50 findings/scan. Checkers that
can emit multiple findings per resource (an SG with two open ports, a user with
two old keys) add a discriminator to `check_name` so distinct issues don't
collide on one row.

### Three-gate auto-remediation safety model

Deleting resources is irreversible, so remediation is guarded by **three
independent gates**, all of which must be open:

1. **Env-var gate** — the cleanup Lambda's `AUTO_REMEDIATE` must be `"true"`
   (per-environment hard stop; `false` in dev).
2. **Event-flag gate** — the invocation's `auto_remediate` must be truthy
   (EventBridge scheduled scans send `false`, so cron runs are always dry-run).
3. **IAM tag gate (STEP 18.5)** — even with both above, the IAM policy only
   permits `DeleteVolume`/`ReleaseAddress`/`DeleteSnapshot` on resources tagged
   `AutoCleanup = "true"`.

So real remediation requires a Terraform change *and* a human manually starting
the workflow with the flag *and* the target resource being explicitly tagged.
True async per-resource approval (Approve/Reject email links via
`.waitForTaskToken`) is deferred to the post-DoD STEP 25.

### Report cadence redesign (STEP 17.5)

The blueprint put a `GenerateReport` task at the end of the scan workflow, which
runs every 6 hours. But the report uses a 24-hour findings window — so four runs
a day would email four **content-identical** 24h reports. The redesign: scans
write to DynamoDB silently, and reports run on **separate** EventBridge schedules
— daily (24h window) and weekly (168h window) — producing meaningfully different
content. Typical week = 7 daily + 1 weekly = 8 emails, not ~28 redundant ones.

### OIDC over static keys (STEP 21)

The blueprint stored `AWS_ACCESS_KEY_ID`/`SECRET_ACCESS_KEY` in GitHub secrets.
As built, GitHub Actions federates into AWS via **OIDC**, minting short-lived
(~1h) credentials per run. No long-lived secret exists to leak, and the deploy
role's trust policy pins it to the `main` branch — a PR from a fork or feature
branch cannot assume it even if it edits the workflow file. Account-global gotcha
documented in the module: `aws_iam_openid_connect_provider` is unique per account,
so a same-account prod environment must share or `data`-source it.

### AWS Config check is a graceful no-op (STEP 22.5 deferred)

`security_scanner/config_checker.py` queries AWS Config for non-compliant rules,
but Config is the first real-cost service in the stack and isn't enabled on the
free-tier account. The checker **catches `NoSuchConfigurationRecorder` /
`AccessDenied` and returns an empty list**, so the security scan continues over
the other categories. Enabling Config is a post-DoD feature extension; the code
path is already in place and tested.

### Scan + Filter vs. a 4th GSI (honest scaling note)

The report generator reads findings with `Scan` + `FilterExpression` on
`last_seen`, not a `Query`. At dev volume (tens-to-low-hundreds of findings) this
is correct and simple. The code documents the threshold: above ~10k items per
table, add a `(environment, timestamp)` GSI and flip to `Query` — the function
signatures already anticipate it. Documenting the limit beats pretending it
scales infinitely.
