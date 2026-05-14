# CloudGuard — AWS Cost & Security Governance Engine

> **Source:** Distilled from "AWS Cloud/DevOps 12 LPA Job Blueprint" by Abhith B N (Cognizant), pages 1–25. This is **Project 1** of 2 in that blueprint.
> **Purpose:** A complete, executable spec. Each STEP below is meant to be done as one Claude Code session.

---

## 0. Why This Project Exists (Interview Framing)

12 LPA Cloud/DevOps roles in Bengaluru (2026) do **not** care if you deployed 10 static websites on S3. They care whether you can:

1. Design infrastructure that doesn't fall apart.
2. Automate everything and hate manual work.
3. Secure things properly without being told.
4. Save the company money on cloud bills.
5. Troubleshoot at 2 AM when production is on fire.

CloudGuard is a production-grade serverless system that continuously monitors an AWS account for cost anomalies, security violations, and zombie resources — then auto-remediates and reports. It's a lightweight version of what tools like CloudHealth and Prisma Cloud do. Building it proves you understand the problem space deeply.

---

## 1. Concepts You MUST Cover (Non-negotiable for 12 LPA in 2026)

| Category    | Concepts                                                                                  |
| ----------- | ----------------------------------------------------------------------------------------- |
| IaC         | Terraform (modules, state management, workspaces)                                         |
| Containers  | Docker (multi-stage builds, optimization), EKS/ECS                                        |
| CI/CD       | GitHub Actions (or GitLab CI), multi-environment pipelines                                |
| Networking  | VPC, subnets (public/private), NAT Gateway, ALB/NLB, Route53, Security Groups, NACLs      |
| Security    | IAM (roles, policies, least privilege), Secrets Manager, AWS Config, Security Hub, KMS    |
| Monitoring  | CloudWatch, Prometheus, Grafana, centralized logging                                      |
| Serverless  | Lambda, EventBridge, Step Functions, SNS/SQS                                              |
| Cost        | Cost Explorer API, cost anomaly detection, resource tagging, right-sizing                 |
| GitOps      | ArgoCD or Flux (2026 standard practice)                                                   |
| Scripting   | Python (boto3) — the dominant DevOps language in 2026                                     |
| Linux       | Systemd, networking, troubleshooting, shell scripting                                     |
| Kubernetes  | Deployments, Services, Ingress, HPA, ConfigMaps, Secrets, RBAC, Helm charts               |

---

## 2. Architecture Overview

```
                    EventBridge Scheduler
                    (triggers every 1hr/6hr)
                              │
                              ▼
                    Step Functions Workflow
                    (orchestrates all scanners)
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        Cost Scanner    Security Scanner   Resource Cleanup
        Lambda          Lambda             Lambda
        (Python/boto3)
              │               │               │
              └───────────────┼───────────────┘
                              ▼
                      DynamoDB Tables
                (findings, cost_data, remediation_log)
                              │
                              ▼
                          SNS / SES
                    (alerts via email / Slack)
                              │
                              ▼
                        S3 Bucket
                  (HTML reports + CSV exports)

ALL infrastructure deployed via Terraform
CI/CD via GitHub Actions
Monitoring via CloudWatch Dashboards
```

---

## 3. Complete Tech Stack

| Tool             | Purpose                                  | Why This One                                                                      |
| ---------------- | ---------------------------------------- | --------------------------------------------------------------------------------- |
| Python 3.12      | All Lambda functions, scripting          | #1 language for DevOps/Cloud automation in 2026. boto3 is native.                 |
| Terraform        | All infrastructure provisioning          | Industry standard IaC. Multi-cloud, more demanded than CloudFormation.            |
| AWS Lambda       | Compute for all scanners                 | Serverless = zero idle cost. Perfect for scheduled scanning.                      |
| AWS Step Functions | Orchestration of scanner workflow      | Coordinates multiple Lambdas with error handling, retries, parallel execution.    |
| Amazon EventBridge | Scheduled triggers + event routing     | Replaces CloudWatch Events. 2026 standard.                                        |
| Amazon DynamoDB  | Store findings, cost data, remediation logs | Serverless NoSQL. Pay-per-request.                                              |
| Amazon S3        | Store generated reports (HTML + CSV)     | Report storage with lifecycle policies.                                           |
| AWS Cost Explorer API | Pull cost and usage data            | The only way to programmatically get AWS billing data.                            |
| AWS Config       | Track resource configuration changes     | Detects configuration drift and non-compliant resources.                          |
| AWS Security Hub | Aggregate security findings              | Central place for security posture. Integrates with Config.                       |
| Amazon SNS       | Send alert notifications                 | Fan-out to email, Slack webhooks, SMS.                                            |
| Amazon SES       | Send formatted email reports             | HTML email reports with cost/security summaries.                                  |
| AWS KMS          | Encrypt DynamoDB, S3 data                | Everything encrypted. Non-negotiable in 2026.                                     |
| AWS IAM          | Least-privilege roles for every Lambda   | Each function gets only the permissions it needs. Nothing more.                   |
| AWS Secrets Manager | Store Slack webhook URLs, API keys    | Never hardcode secrets.                                                           |
| Amazon CloudWatch | Lambda monitoring, custom metrics, dashboards | Monitor the monitoring system itself.                                        |
| GitHub Actions   | CI/CD pipeline                           | Lint → Test → Terraform Plan → Terraform Apply. Multi-environment.                |
| Checkov          | Terraform security scanning in CI/CD     | Catches insecure Terraform before it deploys.                                     |
| pytest           | Unit testing Lambda functions            | Test your Python code properly.                                                   |
| Git              | Version control                          | Obviously. But proper branching strategy matters.                                 |

---

## 4. Prerequisite Learning Phases

Work through these **before** writing project code. Phase 1 is non-negotiable.

### Phase 1: Foundations
1. Python fundamentals — variables, functions, classes, error handling, file I/O, JSON
2. boto3 library — initialize clients, make API calls, handle pagination, error handling
3. Git basics — clone, branch, commit, push, pull, merge, resolve conflicts
4. AWS CLI — configure profiles, basic commands for S3, EC2, IAM
5. IAM deep dive — users, roles, policies (identity vs resource), trust relationships, least privilege
6. Linux command line — navigation, file ops, grep, awk, pipes, chmod, systemd basics

### Phase 2: Core AWS Services
7. **S3** — buckets, objects, policies, encryption (SSE-S3, SSE-KMS), lifecycle rules, versioning, access logging
8. **DynamoDB** — tables, items, partition keys, sort keys, GSI, LSI, read/write capacity modes, TTL
9. **Lambda** — handler function, event/context objects, layers, env vars, memory/timeout tuning, cold starts
10. **EventBridge** — rules, schedules, event patterns, targets, custom event buses
11. **Step Functions** — state machine definition (ASL), Task/Choice/Parallel states, error handling with Catch/Retry
12. **SNS** — topics, subscriptions (email, HTTPS, Lambda), message filtering
13. **SES** — email sending, verified identities, templates
14. **CloudWatch** — metrics, alarms, log groups, log insights queries, dashboards
15. **KMS** — key creation, key policies, encryption context, envelope encryption concept
16. **Secrets Manager** — create secret, retrieve secret in Lambda, rotation

### Phase 3: Infrastructure as Code
17. Terraform basics — providers, resources, data sources, variables, outputs
18. Terraform state — local vs remote (S3 + DynamoDB locking), state commands
19. Terraform modules — writing reusable modules, module sources, input/output variables
20. Terraform workspaces — managing dev/staging/prod environments
21. Terraform best practices — file structure, naming conventions, tagging strategy

### Phase 4: CI/CD
22. GitHub Actions — workflow YAML syntax, triggers (push, PR, schedule), jobs, steps
23. GitHub Actions for Terraform — plan on PR, apply on merge to main
24. Secrets in GitHub Actions — repository secrets, environment secrets
25. Checkov integration — running Terraform security scans in pipeline
26. pytest integration — running unit tests in pipeline before deploy

### Phase 5: Security & Compliance
27. AWS Config — rules (managed + custom), conformance packs, remediation actions
28. Security Hub — standards (CIS, AWS Foundational), findings, integrations
29. Cost Explorer API — get_cost_and_usage, grouping by service/tag, filtering

---

## 5. Final Repository Structure (Target)

```
cloudguard/
├── README.md
├── .gitignore
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── deploy.yml
├── terraform/
│   ├── environments/
│   │   ├── dev/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   ├── outputs.tf
│   │   │   ├── terraform.tfvars
│   │   │   └── backend.tf
│   │   └── prod/
│   │       ├── main.tf
│   │       ├── variables.tf
│   │       ├── outputs.tf
│   │       ├── terraform.tfvars
│   │       └── backend.tf
│   └── modules/
│       ├── lambda/
│       │   ├── main.tf
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── dynamodb/
│       │   ├── main.tf
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── step-functions/
│       │   ├── main.tf
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── eventbridge/
│       │   ├── main.tf
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── s3/
│       │   ├── main.tf
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── sns/
│       │   ├── main.tf
│       │   ├── variables.tf
│       │   └── outputs.tf
│       └── iam/
│           ├── main.tf
│           ├── variables.tf
│           └── outputs.tf
├── src/
│   ├── cost_scanner/
│   │   ├── handler.py
│   │   ├── cost_analyzer.py
│   │   └── requirements.txt
│   ├── security_scanner/
│   │   ├── handler.py
│   │   ├── config_checker.py
│   │   ├── sg_checker.py
│   │   ├── s3_checker.py
│   │   ├── iam_checker.py
│   │   └── requirements.txt
│   ├── resource_cleanup/
│   │   ├── handler.py
│   │   ├── zombie_finder.py
│   │   └── requirements.txt
│   ├── report_generator/
│   │   ├── handler.py
│   │   ├── html_builder.py
│   │   └── requirements.txt
│   └── shared/
│       ├── aws_helpers.py
│       ├── dynamo_client.py
│       └── notification.py
├── tests/
│   ├── test_cost_scanner.py
│   ├── test_security_scanner.py
│   ├── test_resource_cleanup.py
│   └── test_report_generator.py
├── scripts/
│   ├── package_lambdas.sh
│   └── setup_backend.sh
└── docs/
    ├── architecture.md
    └── runbook.md
```

---

# EXECUTION PLAN — 23 STEPS

> **Rule for Claude Code:** Do ONE step per session. After each step, stop and let the human review + commit + ask "why did you choose X?". Never run `terraform apply` without explicit human confirmation.

---

## STEP 1 — Set Up Development Environment

1. Install Python 3.12.
2. Install pip and virtualenv.
3. Create a virtual environment: `python -m venv cloudguard-env`
4. Activate it:
   - Linux/Mac: `source cloudguard-env/bin/activate`
   - Windows: `cloudguard-env\Scripts\activate`
5. Install boto3: `pip install boto3`
6. Install pytest: `pip install pytest`
7. Install Terraform (download from hashicorp.com, add to PATH).
8. Verify: `terraform --version`
9. Install AWS CLI v2.
10. Configure AWS CLI: `aws configure` (use an IAM user with admin access **FOR DEVELOPMENT ONLY**).
11. Install Git.
12. Create a GitHub account if you don't have one.
13. Install VS Code with extensions: Python, Terraform, GitLens, YAML.

## STEP 2 — Set Up Repository Structure

1. Create a new GitHub repo called `cloudguard`.
2. Clone it locally: `git clone <url>`
3. Create the full folder structure shown in section 5 above.
4. Create the `.gitignore` file with Python, Terraform, and IDE patterns.
5. Commit and push: `git add . && git commit -m "initial project structure" && git push`

## STEP 3 — Set Up Terraform Remote Backend

1. Create `scripts/setup_backend.sh`.
2. In it, use AWS CLI to create an S3 bucket for Terraform state:
   `aws s3 mb s3://cloudguard-tf-state-<your-unique-id>`
3. Enable versioning:
   `aws s3api put-bucket-versioning --bucket cloudguard-tf-state-<id> --versioning-configuration Status=Enabled`
4. Enable server-side encryption on the bucket.
5. Create DynamoDB table for state locking:
   `aws dynamodb create-table --table-name cloudguard-tf-lock --attribute-definitions AttributeName=LockID,AttributeType=S --key-schema AttributeName=LockID,KeyType=HASH --billing-mode PAY_PER_REQUEST`
6. Write `backend.tf` in `terraform/environments/dev/`:

```hcl
terraform {
  backend "s3" {
    bucket         = "cloudguard-tf-state-<id>"
    key            = "dev/terraform.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "cloudguard-tf-lock"
    encrypt        = true
  }
}
```

7. Run `terraform init` in the dev environment directory.
8. Verify it initializes successfully with remote backend.

## STEP 4 — Build the IAM Terraform Module

Open `terraform/modules/iam/main.tf`. Create an IAM role for each Lambda function with **SEPARATE** policies (least privilege).

- **Cost Scanner role** needs: `ce:GetCostAndUsage`, `ce:GetCostForecast`, `ec2:DescribeInstances`, `rds:DescribeDBInstances`, `dynamodb:PutItem`, `dynamodb:Query`
- **Security Scanner role** needs: `config:GetComplianceDetailsByConfigRule`, `ec2:DescribeSecurityGroups`, `s3:GetBucketPolicy`, `s3:GetBucketEncryption`, `s3:GetBucketPublicAccessBlock`, `iam:ListUsers`, `iam:ListAccessKeys`, `iam:GetAccessKeyLastUsed`, `dynamodb:PutItem`
- **Resource Cleanup role** needs: `ec2:DescribeVolumes`, `ec2:DeleteVolume`, `ec2:DescribeAddresses`, `ec2:ReleaseAddress`, `ec2:DescribeSnapshots`, `dynamodb:PutItem`, `sns:Publish`
- **Report Generator role** needs: `dynamodb:Query`, `dynamodb:Scan`, `s3:PutObject`, `ses:SendEmail`, `sns:Publish`

For each role:
- Add assume role policy for Lambda service: `lambda.amazonaws.com`
- Add CloudWatch Logs permissions to ALL roles: `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`
- Use variables for environment name so dev/prod get different role names.
- Output the role ARNs.
- Test: `terraform plan` — should show the roles being created.

## STEP 5 — Build the DynamoDB Terraform Module

Open `terraform/modules/dynamodb/main.tf`.

**Table 1: `cloudguard-findings`**
- Partition key: `finding_id` (String)
- Sort key: `timestamp` (String)
- GSI on `severity` (query critical findings fast)
- GSI on `category` (cost / security / cleanup)
- Enable Point-in-Time Recovery
- Enable encryption with KMS
- Billing mode: PAY_PER_REQUEST
- Add TTL attribute `expires_at` (auto-delete old findings after 90 days)

**Table 2: `cloudguard-cost-data`**
- Partition key: `date` (String)
- Sort key: `service_name` (String)
- Enable PITR
- Enable encryption
- PAY_PER_REQUEST

**Table 3: `cloudguard-remediation-log`**
- Partition key: `remediation_id` (String)
- Sort key: `timestamp` (String)
- GSI on `status` (success / failed / pending)
- Enable PITR, encryption
- PAY_PER_REQUEST

Output table names and ARNs. Test: `terraform plan`.

## STEP 6 — Build the S3 Terraform Module

Create the reports bucket with:
- Server-side encryption (SSE-KMS)
- Versioning enabled
- Block ALL public access (all 4 settings = true)
- Lifecycle rule: transition to Glacier after 90 days, delete after 365 days
- Access logging enabled (create a separate logging bucket)
- Bucket policy that only allows your Lambda roles to write to it
- Output bucket name and ARN

## STEP 7 — Build the SNS Terraform Module

1. Create SNS topic `cloudguard-alerts`.
2. Enable encryption on the topic with KMS.
3. Create email subscription (use a variable for the email address).
4. Create a topic policy.
5. Output topic ARN.

## STEP 8 — Build the Lambda Terraform Module (Reusable)

Reusable module that takes these inputs:
- `function_name`
- `handler` (e.g., `handler.lambda_handler`)
- `runtime` (`python3.12`)
- `role_arn`
- `source_dir` (path to function code)
- `environment_variables` (map)
- `timeout` (default 300 seconds)
- `memory_size` (default 256 MB)
- `layers` (optional list of layer ARNs)

Logic:
1. Use `archive_file` data source to zip the source directory.
2. Create the Lambda function.
3. Create CloudWatch Log Group with 30-day retention.
4. Output function ARN and function name.

## STEP 9 — Write the Cost Scanner Lambda

Open `src/cost_scanner/handler.py`.

```
Imports: boto3, json, os, datetime
Init: ce = boto3.client('ce'), dynamodb = boto3.resource('dynamodb')
```

`lambda_handler(event, context)`:
- Get today's date and 30-days-ago date.
- Call `ce.get_cost_and_usage()` with `TimePeriod`, `Granularity='DAILY'`, `Metrics=['UnblendedCost']`, `GroupBy=service`.
- Parse the response → cost per service per day.
- Calculate average daily cost per service over last 30 days.
- Compare today's cost per service against the 30-day average.
- If any service cost is > 150% of its average → flag as anomaly.
- Store all cost data in `cloudguard-cost-data` table.
- Store anomalies as findings in `cloudguard-findings` table with `severity=HIGH`.
- Return summary: `{"anomalies_found": count, "total_daily_cost": total, "services_scanned": count}`

Helper `get_cost_data(ce_client, start_date, end_date)`:
- Handle pagination.
- Return structured data.

Helper `detect_anomalies(cost_data, threshold=1.5)`:
- Compare each service's latest cost against its historical average.
- Return list of anomalies with service name, expected cost, actual cost, percentage increase.

Helper `store_findings(table, anomalies)`:
- Generate `finding_id` using uuid.
- Set severity: >200% = CRITICAL, >150% = HIGH.
- Set `category = "cost"`.
- Set `expires_at = current_time + 90 days` (for DynamoDB TTL).
- Batch write to DynamoDB.

Create `requirements.txt`: just `boto3`.

## STEP 10 — Write the Security Scanner Lambda

Open `src/security_scanner/handler.py`. This Lambda orchestrates multiple security checks.

`lambda_handler(event, context)`:
- Call `check_security_groups()`
- Call `check_s3_buckets()`
- Call `check_iam_users()`
- Call `check_ebs_encryption()`
- Aggregate all findings.
- Store in DynamoDB.
- Return summary.

`src/security_scanner/sg_checker.py` — `check_security_groups()`:
- Use `ec2.describe_security_groups()`.
- For each SG, check inbound rules.
- Flag rules allowing `0.0.0.0/0` on ports other than 80, 443.
- Flag rules allowing `0.0.0.0/0` on SSH (22) or RDP (3389) → **CRITICAL** severity.
- Flag overly permissive rules (all traffic from `0.0.0.0/0`).
- Return findings with: sg_id, vpc_id, rule details, severity, recommendation.

`src/security_scanner/s3_checker.py` — `check_s3_buckets()`:
- Use `s3.list_buckets()`.
- For each bucket:
  - `get_public_access_block()` — flag if any setting is False.
  - `get_bucket_encryption()` — flag if no encryption.
  - `get_bucket_policy()` — parse JSON, flag if any statement has `Principal = "*"`.
  - `get_bucket_versioning()` — flag if not enabled (warning, not critical).
- Return findings.

`src/security_scanner/iam_checker.py` — `check_iam_users()`:
- Use `iam.list_users()`.
- For each user:
  - `list_access_keys()` — flag keys older than 90 days.
  - `get_access_key_last_used()` — flag keys unused for 90+ days.
  - `list_mfa_devices()` — flag if no MFA.
  - `list_attached_user_policies()` — flag if `AdministratorAccess` is directly attached.
- Return findings.

Each finding must have: `finding_id` (uuid), `resource_id`, `resource_type`, `check_name`, `severity` (CRITICAL/HIGH/MEDIUM/LOW), `description`, `recommendation`, `category="security"`, `timestamp`.

## STEP 11 — Write the Resource Cleanup Lambda

Open `src/resource_cleanup/handler.py`.

`lambda_handler(event, context)`:
- Call `find_zombie_ebs_volumes()`
- Call `find_unused_elastic_ips()`
- Call `find_old_snapshots()`
- For each zombie resource, log it as a finding.
- If `auto_remediate` flag is set in event, actually delete/release the resources.
- Log all remediations in `cloudguard-remediation-log` table.
- Return summary.

`src/resource_cleanup/zombie_finder.py`:

`find_zombie_ebs_volumes()`:
- `ec2.describe_volumes(Filters=[{'Name': 'status', 'Values': ['available']}])`
- These are volumes not attached to any instance = wasting money.
- Calculate monthly cost based on volume size and type.
- Return list with: volume_id, size, type, monthly_cost, create_date.

`find_unused_elastic_ips()`:
- `ec2.describe_addresses()`
- Filter for EIPs with no `AssociationId` (not attached to anything).
- Each unused EIP costs ~$3.65/month.
- Return list with: allocation_id, public_ip.

`find_old_snapshots()`:
- `ec2.describe_snapshots(OwnerIds=['self'])`
- Flag snapshots older than 180 days.
- Calculate storage cost.
- Return list with: snapshot_id, start_time, volume_size, estimated_cost.

## STEP 12 — Write the Report Generator Lambda

Open `src/report_generator/handler.py`.

`lambda_handler(event, context)`:
- Query DynamoDB `cloudguard-findings` for last 24 hours (or 7 days for weekly).
- Query `cloudguard-cost-data` for trends.
- Query `cloudguard-remediation-log` for actions taken.
- Generate HTML report using string templates.
- Upload HTML to S3.
- Generate pre-signed URL (valid for 7 days).
- Send email via SES with summary + link to full report.
- Send SNS notification.

`src/report_generator/html_builder.py` — `build_report(findings, cost_data, remediations)`:
- Create HTML with inline CSS (no external dependencies).
- Executive summary section: total findings, critical count, estimated savings.
- Cost section: daily cost trend (simple HTML table), anomalies highlighted in red.
- Security section: findings grouped by severity, each with recommendation.
- Remediation section: what was auto-fixed, what needs manual attention.
- Return HTML string.

## STEP 13 — Write the Shared Utilities

`src/shared/aws_helpers.py`:
- `paginate(client, method, key, **kwargs)` — generic paginator for any boto3 paginated API.
- `get_account_id()` — returns current AWS account ID using STS.
- `get_all_regions()` — returns list of enabled regions (for multi-region scanning later).

`src/shared/dynamo_client.py`:
- `put_finding(table_name, finding)` — writes a single finding.
- `batch_put_findings(table_name, findings)` — batch writes up to 25 findings.
- `query_findings_by_date(table_name, start_date, end_date)` — queries findings in date range.
- `query_findings_by_severity(table_name, severity)` — uses GSI to query by severity.

`src/shared/notification.py`:
- `send_sns_alert(topic_arn, subject, message)` — sends SNS notification.
- `send_slack_webhook(webhook_url, message_payload)` — sends Slack notification via webhook (get URL from Secrets Manager).

## STEP 14 — Write Unit Tests

`tests/test_cost_scanner.py`:
- Use `unittest.mock` to mock boto3 clients.
- Test `detect_anomalies()` with known data where anomaly exists.
- Test `detect_anomalies()` with known data where no anomaly exists.
- Test `get_cost_data()` with mocked Cost Explorer response.
- Test that findings are stored correctly with proper severity.

`tests/test_security_scanner.py`:
- Mock `describe_security_groups` response with an open SSH rule. Verify it gets flagged as CRITICAL.
- Mock S3 bucket with public access — verify flagged.
- Mock IAM user with old access keys — verify flagged.
- Test clean resources don't generate false positives.

`tests/test_resource_cleanup.py`:
- Mock EBS volumes in 'available' state — verify detected.
- Mock EIPs with no association — verify detected.
- Mock old snapshots — verify detected.
- Test remediation logging.

Run all tests: `pytest tests/ -v`.

## STEP 15 — Build the Step Functions Workflow

Open `terraform/modules/step-functions/main.tf`. Define the state machine in Amazon States Language (ASL):

```json
{
  "StartAt": "ParallelScanners",
  "States": {
    "ParallelScanners": {
      "Type": "Parallel",
      "Branches": [
        {
          "StartAt": "CostScanner",
          "States": {
            "CostScanner": {
              "Type": "Task",
              "Resource": "${cost_scanner_arn}",
              "Retry": [{"ErrorEquals": ["States.ALL"], "MaxAttempts": 2, "BackoffRate": 2.0}],
              "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "CostScanFailed"}],
              "End": true
            },
            "CostScanFailed": {
              "Type": "Pass",
              "Result": {"status": "FAILED", "scanner": "cost"},
              "End": true
            }
          }
        },
        {
          "StartAt": "SecurityScanner",
          "States": {
            "SecurityScanner": {
              "Type": "Task",
              "Resource": "${security_scanner_arn}",
              "Retry": [{"ErrorEquals": ["States.ALL"], "MaxAttempts": 2, "BackoffRate": 2.0}],
              "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "SecurityScanFailed"}],
              "End": true
            },
            "SecurityScanFailed": {
              "Type": "Pass",
              "Result": {"status": "FAILED", "scanner": "security"},
              "End": true
            }
          }
        },
        {
          "StartAt": "ResourceCleanup",
          "States": {
            "ResourceCleanup": {
              "Type": "Task",
              "Resource": "${resource_cleanup_arn}",
              "Retry": [{"ErrorEquals": ["States.ALL"], "MaxAttempts": 2, "BackoffRate": 2.0}],
              "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "CleanupFailed"}],
              "End": true
            },
            "CleanupFailed": {
              "Type": "Pass",
              "Result": {"status": "FAILED", "scanner": "cleanup"},
              "End": true
            }
          }
        }
      ],
      "Next": "GenerateReport"
    },
    "GenerateReport": {
      "Type": "Task",
      "Resource": "${report_generator_arn}",
      "Retry": [{"ErrorEquals": ["States.ALL"], "MaxAttempts": 2}],
      "End": true
    }
  }
}
```

3. Create the state machine resource in Terraform.
4. Create IAM role for Step Functions with permission to invoke all Lambda functions.

## STEP 16 — Build the EventBridge Terraform Module

1. Create a scheduled rule that triggers every 6 hours:
   - `schedule_expression = "rate(6 hours)"`
   - Target = Step Functions state machine.
2. Create a second rule for daily report at 8 AM IST:
   - `schedule_expression = "cron(30 2 * * ? *)"` (2:30 UTC = 8:00 AM IST)
   - Target = Report Generator Lambda directly.
3. Create IAM role for EventBridge to invoke Step Functions and Lambda.

## STEP 17 — Wire Everything Together in Dev Environment

Open `terraform/environments/dev/main.tf`. Call each module:

```hcl
module "iam" {
  source      = "../../modules/iam"
  environment = "dev"
  project     = "cloudguard"
}

module "dynamodb" {
  source      = "../../modules/dynamodb"
  environment = "dev"
  project     = "cloudguard"
}

module "s3" {
  source      = "../../modules/s3"
  environment = "dev"
  project     = "cloudguard"
}

module "sns" {
  source      = "../../modules/sns"
  environment = "dev"
  alert_email = var.alert_email
}

module "cost_scanner" {
  source        = "../../modules/lambda"
  function_name = "cloudguard-cost-scanner-dev"
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  role_arn      = module.iam.cost_scanner_role_arn
  source_dir    = "${path.root}/../../../src/cost_scanner"
  timeout       = 300
  memory_size   = 256
  environment_variables = {
    FINDINGS_TABLE  = module.dynamodb.findings_table_name
    COST_DATA_TABLE = module.dynamodb.cost_data_table_name
    SNS_TOPIC_ARN   = module.sns.topic_arn
    ENVIRONMENT     = "dev"
  }
}

# ... repeat for security_scanner, resource_cleanup, report_generator

module "step_functions" {
  source              = "../../modules/step-functions"
  environment         = "dev"
  cost_scanner_arn    = module.cost_scanner.function_arn
  security_scanner_arn = module.security_scanner.function_arn
  resource_cleanup_arn = module.resource_cleanup.function_arn
  report_generator_arn = module.report_generator.function_arn
}

module "eventbridge" {
  source            = "../../modules/eventbridge"
  environment       = "dev"
  state_machine_arn = module.step_functions.state_machine_arn
  report_lambda_arn = module.report_generator.function_arn
}
```

3. Define variables in `variables.tf`: region, alert_email, environment, project name.
4. Set values in `terraform.tfvars`.
5. `terraform init`
6. `terraform plan` — **review the plan carefully**.
7. `terraform apply` — type yes.
8. Verify all resources are created in AWS Console.

## STEP 18 — Create the Lambda Packaging Script

`scripts/package_lambdas.sh`:

```bash
#!/bin/bash
set -e

FUNCTIONS=("cost_scanner" "security_scanner" "resource_cleanup" "report_generator")

for func in "${FUNCTIONS[@]}"; do
    echo "Packaging ${func}..."
    cd src/${func}
    pip install -r requirements.txt -t ./package/
    cp *.py ./package/
    cp -r ../shared ./package/
    cd package
    zip -r9 ../../../terraform/environments/dev/${func}.zip .
    cd ..
    rm -rf package
    cd ../..
    echo "${func} packaged successfully"
done
```

- Make it executable: `chmod +x scripts/package_lambdas.sh`
- Run it: `./scripts/package_lambdas.sh`
- Verify zip files are created.

## STEP 19 — Test the System End-to-End

1. AWS Console → Step Functions.
2. Find the `cloudguard-workflow-dev` state machine.
3. Click "Start execution".
4. Empty JSON input: `{}`
5. Watch the execution graph — all 3 scanners should run in parallel, then the report generator.
6. Check CloudWatch Logs for each Lambda — look for errors.
7. Check DynamoDB tables — findings should be populated.
8. Check S3 bucket — HTML report should be there.
9. Check email — you should receive a notification.
10. If anything fails, debug using CloudWatch Logs, fix the code, re-package, re-deploy.

## STEP 20 — Build the CI/CD Pipeline

`.github/workflows/ci.yml`:

```yaml
name: CI
on:
  pull_request:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: pip install boto3 pytest moto
      - name: Run tests
        run: pytest tests/ -v
  terraform-plan:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - name: Terraform Init
        working-directory: terraform/environments/dev
        run: terraform init
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
      - name: Terraform Plan
        working-directory: terraform/environments/dev
        run: terraform plan -no-color
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
  security-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Checkov
        uses: bridgecrewio/checkov-action@master
        with:
          directory: terraform/
          framework: terraform
```

`.github/workflows/deploy.yml`:

```yaml
name: Deploy
on:
  push:
    branches: [main]
jobs:
  deploy-dev:
    runs-on: ubuntu-latest
    environment: dev
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Run tests
        run: |
          pip install boto3 pytest moto
          pytest tests/ -v
      - name: Package Lambdas
        run: bash scripts/package_lambdas.sh
      - uses: hashicorp/setup-terraform@v3
      - name: Terraform Apply
        working-directory: terraform/environments/dev
        run: |
          terraform init
          terraform apply -auto-approve
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

- Add AWS credentials to GitHub repository secrets.
- Create a branch, make a change, open a PR — verify CI runs.
- Merge the PR — verify deploy runs.

## STEP 21 — Add CloudWatch Dashboard

1. In Terraform, create a CloudWatch Dashboard resource.
2. Include widgets for:
   - Lambda invocation counts (all 4 functions)
   - Lambda error counts
   - Lambda duration
   - Step Functions execution count and status
   - DynamoDB read/write capacity consumed
3. Add CloudWatch Alarms:
   - Lambda error rate > 5% → SNS notification
   - Lambda duration > 80% of timeout → SNS notification
   - Step Functions execution failed → SNS notification

## STEP 22 — Write Documentation

1. `README.md` — comprehensive, including:
   - Project description (2–3 paragraphs explaining what and why)
   - Architecture diagram (the ASCII from section 2 above or a PNG)
   - Prerequisites section
   - Setup instructions (step by step)
   - How to deploy
   - How to test
   - Configuration options
   - Cost estimation (how much this system costs to run per month)
2. `docs/architecture.md`:
   - Detailed explanation of each component
   - Data flow description
   - Design decisions and trade-offs
3. `docs/runbook.md`:
   - How to trigger a manual scan
   - How to investigate a finding
   - How to adjust thresholds
   - Common troubleshooting scenarios

## STEP 23 — Add Resource Tagging Strategy

1. Add a `tags` variable to **EVERY** Terraform module.
2. Apply consistent tags to ALL resources:

```hcl
tags = {
  Project     = "cloudguard"
  Environment = var.environment
  ManagedBy   = "terraform"
  Owner       = "your-name"
  CostCenter  = "devops"
}
```

3. This is specifically so you can demonstrate in interviews that you understand tagging for cost allocation and resource management.

---

# Definition of Done

The project is complete when:

- [ ] All 23 steps executed.
- [ ] `terraform apply` succeeds end-to-end in `dev`.
- [ ] Step Functions execution completes successfully with all 4 Lambdas running.
- [ ] Findings appear in all 3 DynamoDB tables.
- [ ] HTML report is generated in S3.
- [ ] Email notification arrives.
- [ ] All `pytest` tests pass.
- [ ] GitHub Actions CI runs green on PR, deploy runs green on merge to main.
- [ ] Checkov finds zero CRITICAL issues.
- [ ] CloudWatch dashboard shows live metrics.
- [ ] README + architecture.md + runbook.md exist and explain the system.
- [ ] All resources are tagged.
- [ ] You can answer in an interview, **without reading from the code**, the following:
  - Why ALB over NLB (or vice versa) for any HTTP service?
  - Why Step Functions instead of chaining Lambdas with SNS/SQS?
  - Why DynamoDB PAY_PER_REQUEST instead of provisioned?
  - Why a separate IAM role per Lambda?
  - Why S3 + DynamoDB for Terraform remote state?
  - What happens if `cost_scanner` Lambda fails mid-execution?
  - How envelope encryption works in KMS?
  - The difference between an identity policy and a resource policy.
