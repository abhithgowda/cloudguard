# CloudGuard - AWS Cost & Security Governance Engine

CloudGuard is a production-grade, fully serverless system that continuously
monitors an AWS account for **cost anomalies**, **security violations**, and
**zombie (idle, billed-but-unused) resources** — then records findings, alerts
a human, and (optionally, behind multiple safety gates) auto-remediates. It is a
lightweight, self-hosted take on what commercial tools like CloudHealth and
Prisma Cloud do.

Three scanner Lambdas (cost / security / cleanup) run in parallel on a schedule,
orchestrated by a Step Functions state machine and triggered by EventBridge.
Every finding is written idempotently to DynamoDB. A separate report-generator
Lambda runs on its own daily and weekly schedules, builds an HTML report, stores
it in an encrypted S3 bucket, and emails a summary with a pre-signed link via
SES — also publishing to SNS. The whole system is deployed by Terraform and
shipped through a GitHub Actions CI/CD pipeline that authenticates to AWS with
short-lived OIDC credentials (no long-lived keys).

The point isn't just "it runs." Every design decision — least-privilege IAM
role per Lambda, a single customer-managed KMS key for envelope encryption,
PAY_PER_REQUEST DynamoDB, deterministic finding de-duplication, a three-gate
auto-remediation safety model — is deliberate and defensible. See
[`docs/architecture.md`](docs/architecture.md) for the reasoning behind each.

---

## Architecture (as-built)

```
                         ┌──────────────────────────────────────────────┐
                         │              EventBridge (3 rules)             │
                         │  scan: rate(6 hours)                           │
                         │  daily report: cron(30 2 * * ? *)   08:00 IST  │
                         │  weekly report: cron(30 2 ? * MON *) Mon 08 IST│
                         └───────────────┬───────────────┬────────────────┘
                  scan {auto_remediate}  │               │ report {window_hours}
                                         ▼               │
                          ┌──────────────────────────┐   │
                          │   Step Functions (STD)    │   │
                          │      ParallelScanners      │   │   (reports run on
                          │  Retry ×2 / Catch → Pass   │   │    their OWN schedule
                          └───────┬──────┬──────┬──────┘   │    — NOT inside the
                                  ▼      ▼      ▼          │    scan workflow;
                            ┌────────┐┌────────┐┌────────┐ │    see STEP 17.5)
                            │  Cost  ││Security││Cleanup │ │
                            │Scanner ││Scanner ││Lambda  │ │
                            └───┬────┘└───┬────┘└───┬────┘ │
                                │         │         │      │
        Cost Explorer ─────────┘         │         └── EC2 (EBS/EIP/Snapshots)
        EC2/S3/IAM/Config ───────────────┘             + optional remediation
                                  │                          │
                                  ▼                          ▼
                  ┌───────────────────────────────────────────────────┐
                  │              DynamoDB (3 tables, SSE-KMS)            │
                  │  findings · cost-data · remediation-log             │
                  └───────────────────────────┬─────────────────────────┘
                                               │
                                               ▼
                                   ┌───────────────────────┐
                                   │   Report Generator     │
                                   │       Lambda           │
                                   └───┬──────────┬─────┬────┘
                                       ▼          ▼     ▼
                                ┌──────────┐  ┌──────┐ ┌──────┐
                                │ S3 (KMS) │  │ SES  │ │ SNS  │
                                │ HTML rpt │  │email │ │email │
                                │ +presign │  │ +link│ │alert │
                                └──────────┘  └──────┘ └──────┘

  Cross-cutting:  KMS (1 shared CMK) encrypts DynamoDB + S3 reports + SNS + log groups
                  CloudWatch dashboard (5 widgets) + 9 alarms → SNS
                  IAM: one least-privilege role per Lambda
                  All infra via Terraform · CI/CD via GitHub Actions (OIDC)
```

> **Note vs. the original blueprint diagram:** the blueprint drew the report
> generator *inside* the scan workflow, fired by the same EventBridge schedule.
> As built, the report generator is **decoupled** — the 6-hourly scan writes
> findings to DynamoDB silently, and reports are produced on independent daily
> (24h) and weekly (168h) EventBridge schedules. This avoids four content-
> identical 24h-window emails per day. See the STEP 17.5 decision in
> [`docs/architecture.md`](docs/architecture.md#report-cadence-redesign-step-175).

---

## Repository layout

```
cloudguard/
├── README.md                  ← you are here
├── docs/
│   ├── architecture.md        ← component deep-dive + design decisions
│   └── runbook.md             ← operator playbook
├── terraform/
│   ├── environments/dev/      ← the deployable root module (wires everything)
│   └── modules/               ← iam, kms, dynamodb, s3, sns, lambda,
│                                step-functions, eventbridge, cloudwatch,
│                                github_oidc
├── src/
│   ├── cost_scanner/          ← handler.py + cost_analyzer.py
│   ├── security_scanner/      ← handler.py + sg/s3/iam/ebs/config checkers
│   ├── resource_cleanup/      ← handler.py + zombie_finder.py
│   ├── report_generator/      ← handler.py + html_builder.py
│   └── shared/                ← aws_helpers, dynamo_client, notification
├── tests/                     ← pytest unit tests (mocks-only, no AWS)
├── scripts/                   ← package_lambdas.{sh,ps1}, setup_backend.sh,
│                                cleanup_old_findings.py
└── .github/workflows/         ← ci.yml, deploy.yml
```

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12 | Lambda runtime. Local 3.13 works for tests. |
| Terraform | ≥ 1.14 | Uses native S3 state locking (`use_lockfile`), no DynamoDB lock table. |
| AWS CLI | v2 (≥ 2.32) | Configured with a profile that can deploy (admin in dev). |
| Git | any recent | |
| An AWS account | — | Personal/free-tier is fine; CloudGuard idles at ~$1/mo. |

You also need, one-time:

- An **SES verified identity** for the sender/recipient email (sandbox SES
  requires both ends verified — in dev one address covers both).
- A confirmed **SNS email subscription** (AWS emails a confirmation link on first apply).
- A **GitHub repo** with two repository *variables* set for CI/CD:
  `AWS_PLAN_ROLE_ARN`, `AWS_DEPLOY_ROLE_ARN` (plus `BUCKET_SUFFIX`, `ALERT_EMAIL`).
  These come from `terraform output` after the first apply.

---

## Setup

```powershell
# 1. Clone
git clone https://github.com/abhithcogni/cloudguard.git
cd cloudguard

# 2. Python env (for running tests locally)
python -m venv cloudguard-env
cloudguard-env\Scripts\activate        # Windows
pip install boto3 pytest

# 3. Configure the dev environment's variables
cd terraform\environments\dev
copy terraform.tfvars.example terraform.tfvars
#   then edit terraform.tfvars and set:
#     alert_email   = "you@example.com"
#     bucket_suffix = "your-unique-handle"   # S3 names are globally unique
```

The Terraform **remote backend** (S3 bucket `cloudguard-tf-state-abhithcogni`
with native state locking) is already provisioned — you do **not** need to
re-run `scripts/setup_backend.sh`. Just `terraform init`.

---

## Deploy

CloudGuard is designed to deploy through CI/CD, not from a laptop. The Lambda
zips are content-hashed, and zips built on Windows vs. Linux differ — so the
authoritative build path is the Linux-based GitHub Actions runner.

**Production path (recommended):**

```
git checkout -b my-change
# ... make changes ...
git push origin my-change
# open a PR → CI runs lint + tests + Checkov + terraform plan (posted to the PR)
# merge to main → deploy.yml runs tests, packages Lambdas, terraform apply
```

CI/CD authenticates to AWS via **GitHub OIDC** — no static AWS keys are stored
in GitHub. The deploy role is assumable *only* from the `main` branch (enforced
in its IAM trust policy's `sub` condition).

**Local inspection (plan only):**

```powershell
cd terraform\environments\dev
terraform init
bash ../../../scripts/package_lambdas.sh   # populate src/*/build/ first
terraform plan
# terraform apply  ← only with explicit intent; CI is the normal apply path
```

After the first apply, wire CI/CD by copying the role ARNs into GitHub:

```powershell
terraform output github_plan_role_arn      # → GitHub var AWS_PLAN_ROLE_ARN
terraform output github_deploy_role_arn    # → GitHub var AWS_DEPLOY_ROLE_ARN
```

---

## Test

```powershell
pytest tests/ -v          # 121 tests, mocks-only (no moto, no live AWS)
```

CI runs the same suite on every PR and again inside the deploy job before any
AWS API call.

---

## Configuration options

Set in `terraform/environments/dev/terraform.tfvars` (or via `TF_VAR_*`):

| Variable | Default | Purpose |
|---|---|---|
| `alert_email` | *(required)* | SNS/SES recipient for alerts and reports. |
| `bucket_suffix` | *(required)* | Globally-unique suffix for S3 bucket names. |
| `aws_region` | `ap-south-1` | Deployment region. |
| `ses_sender_email` | `""` → `alert_email` | Verified SES sender; defaults to the recipient. |
| `report_window_hours` | `24` | Default report window; EventBridge inputs override per-rule. |
| `owner` / `cost_center` | `abhith-bn` / `devops` | Cost-allocation tags (`default_tags`). |
| `github_org` / `github_repo` | `abhithcogni` / `cloudguard` | Scopes the OIDC trust policy. |

Tunable Lambda env vars (set in the module calls in `dev/main.tf`):

| Env var | Where | Default | Effect |
|---|---|---|---|
| `MIN_ANOMALY_DOLLARS` | cost_scanner | `1.0` | Absolute floor so micro-spend isn't flagged. |
| `AUTO_REMEDIATE` | resource_cleanup | `false` | Gate #1 of the three-gate remediation model. |
| `SNAPSHOT_AGE_DAYS` | resource_cleanup | `180` | Age above which snapshots are flagged. |
| `LOG_LEVEL` | all | `INFO` | CloudWatch log verbosity. |

Schedule/threshold tuning is documented in
[`docs/runbook.md`](docs/runbook.md#adjusting-thresholds).

---

## Cost estimation

CloudGuard is **near-zero-cost at rest** on a low-traffic account. Steady-state
monthly cost in `ap-south-1` for the dev deployment (~73 resources):

| Service | Usage at dev volume | ~Monthly |
|---|---|---|
| **KMS** | 1 customer-managed CMK + annual rotation | **~$1.00** |
| Lambda | ~4 scans/day × 4 functions + reports; well under 1M-req free tier | ~$0.00 |
| Step Functions | STANDARD, ~120 executions/mo × ~5 transitions = ~600; 4,000 free | ~$0.00 |
| DynamoDB | PAY_PER_REQUEST, tiny item counts; PITR on 3 small tables | ~$0.00–0.05 |
| EventBridge | Scheduled rules are free | $0.00 |
| CloudWatch | 1 dashboard (≤3 free), 9 alarms (10 free), logs (30d retention) | ~$0.00 |
| S3 | A few KB of HTML reports + access logs, lifecycle-tiered | <$0.05 |
| SNS / SES | Email; within free tier (SES sandbox) | ~$0.00 |
| X-Ray | Trace segments at this volume | ~$0.00 |

**Total: ~$1/month**, effectively all of it the KMS CMK. The single biggest
cost lever is the CMK — switching to AWS-managed keys would zero it out but lose
the audit/rotation/key-policy controls (see the KMS trade-off in
[`docs/architecture.md`](docs/architecture.md#kms--encryption)). Cost scales
with finding volume (DynamoDB writes) and report frequency, both negligible here.

---

## Documentation

- **[`docs/architecture.md`](docs/architecture.md)** — every component explained,
  end-to-end data flow, and the design decisions + trade-offs behind them.
- **[`docs/runbook.md`](docs/runbook.md)** — how to trigger a scan, investigate a
  finding, adjust thresholds, arm auto-remediation, and troubleshoot.
