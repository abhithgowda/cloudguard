# CloudGuard — Operator Runbook

Day-to-day procedures for running CloudGuard: triggering scans and reports,
investigating findings, tuning thresholds, arming auto-remediation, and
troubleshooting. For *how the system is built*, see
[`architecture.md`](architecture.md); for setup/deploy, see the
[README](../README.md).

**Environment:** dev · region `ap-south-1` · resource prefix `cloudguard-dev-`.
Read-only AWS CLI (`describe`/`list`/`get`) is safe to run anytime; anything
that creates, deletes, or starts execution is flagged ⚠️ below.

---

## Trigger a manual scan

The scan workflow normally fires every 6 hours. To run it on demand:

**Console:** Step Functions → State machines → `cloudguard-dev-workflow` →
**Start execution** → input `{}` → Start. Watch the graph: all three scanner
branches run in parallel, each ending green (or in its `*ScanFailed` Pass state
if it errored — the execution still succeeds).

**CLI** ⚠️ (starts an execution — non-destructive, but it does run the scanners):

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:ap-south-1:810278669055:stateMachine:cloudguard-dev-workflow \
  --input '{}' \
  --region ap-south-1
```

A scan **never emails** — it writes findings to DynamoDB silently. To see
results, query the findings table (below) or wait for the next report.

> To run a scan *with remediation*, you must open all three gates — see
> [Arming auto-remediation](#arming-auto-remediation). A plain `{}` or
> `{"auto_remediate": true}` from the console will **not** delete anything in
> dev, because the Lambda env-var gate is `false`.

## Trigger a manual report

Reports normally fire daily (24h) and weekly Mondays (168h). To generate one now,
invoke the report-generator Lambda directly:

**Console:** Lambda → `cloudguard-dev-report-generator` → Test → event
`{"report_window_hours": 24}` (or `168`) → Test. Check your inbox for the SES
email + SNS notification, and the reports S3 bucket for the HTML object.

**CLI** ⚠️ (invokes the function; sends a real email):

```bash
aws lambda invoke \
  --function-name cloudguard-dev-report-generator \
  --payload '{"report_window_hours": 24}' \
  --cli-binary-format raw-in-base64-out \
  --region ap-south-1 /tmp/out.json
cat /tmp/out.json    # {"findings_count":…, "email_sent": true, "report_s3_key": …}
```

---

## Investigate a finding

Findings live in DynamoDB table `cloudguard-dev-findings`. Each row carries
`finding_id` (deterministic hash), `timestamp` (immutable first-seen, the sort
key), `last_seen`, `occurrence_count`, `severity`, `category`
(security/cost/cleanup), `check_name`, `description`, `recommendation`, and
`metadata`.

**All CRITICAL findings** (uses the `severity-index` GSI — a real Query, not a
scan):

```bash
aws dynamodb query \
  --table-name cloudguard-dev-findings \
  --index-name severity-index \
  --key-condition-expression "severity = :s" \
  --expression-attribute-values '{":s":{"S":"CRITICAL"}}' \
  --region ap-south-1
```

**By category** (`category-index` GSI): swap to `--index-name category-index`
and `category = :c` with `cost` / `security` / `cleanup`.

**Reading a finding:**
- `occurrence_count > 1` and a `last_seen` well after `timestamp` → a persistent
  issue seen across multiple scans (the report renders "Seen N times since …").
- `metadata.monthly_cost_usd` (cleanup findings) → estimated waste.
- `recommendation` → the suggested fix; for cleanup findings, remediation is
  automatable once the gates are open.

**Failed remediations** that need manual follow-up (uses `status-index` on the
remediation-log table):

```bash
aws dynamodb query \
  --table-name cloudguard-dev-remediation-log \
  --index-name status-index \
  --key-condition-expression "#s = :st" \
  --expression-attribute-names '{"#s":"status"}' \
  --expression-attribute-values '{":st":{"S":"FAILED"}}' \
  --region ap-south-1
```

**Lambda logs** (per scanner) are in CloudWatch under
`/aws/lambda/cloudguard-dev-<function>`; the Step Functions execution graph and
X-Ray trace show which branch produced what.

---

## Adjusting thresholds

Thresholds live in two places: **Lambda env vars** (change in
`terraform/environments/dev/main.tf`, then deploy) and **Python constants**
(change in `src/…`, then deploy). All changes ship via PR → merge to `main`.

| Threshold | Where | Default |
|---|---|---|
| Cost anomaly ratio (HIGH / CRITICAL) | `src/cost_scanner/cost_analyzer.py` → `SEVERITY_HIGH_RATIO` (1.5) / `SEVERITY_CRITICAL_RATIO` (2.0) | 1.5× / 2.0× |
| Cost absolute-dollar floor | `MIN_ANOMALY_DOLLARS` env var (cost_scanner, `dev/main.tf`) | `1.0` |
| Snapshot age | `SNAPSHOT_AGE_DAYS` env var (resource_cleanup) | `180` |
| Zombie severity by cost | `src/resource_cleanup/zombie_finder.py` → `SEVERITY_HIGH_THRESHOLD_USD` (50) / `SEVERITY_MEDIUM_THRESHOLD_USD` (10) | $50 / $10 |
| EBS / EIP / snapshot pricing | `zombie_finder.py` price constants (ap-south-1) | per AWS pricing |
| IAM key age / unused window | `src/security_scanner/iam_checker.py` → `ACCESS_KEY_MAX_AGE_DAYS` / `ACCESS_KEY_UNUSED_DAYS` | 90 / 90 days |
| SG allowed public ports / critical ports | `src/security_scanner/sg_checker.py` → `ALLOWED_PUBLIC_PORTS` ({80,443}) / `CRITICAL_PORTS` ({22,3389}) | — |
| Finding TTL | `FINDING_TTL_DAYS` in each scanner (90) | 90 days |
| Scan / report schedules | `terraform/modules/eventbridge/variables.tf` (`scan_schedule_expression`, `daily_/weekly_report_schedule_expression`) | 6h / daily / weekly |
| Report window per rule | `daily_/weekly_report_window_hours` (eventbridge vars) | 24 / 168 |
| Alarm thresholds | `terraform/modules/cloudwatch/variables.tf` (`error_rate_threshold_percent` 5, `duration_threshold_ratio` 0.8) | 5% / 80% |

**Pause a schedule without destroying it:** set `scan_rule_enabled = false` (or
`daily_/weekly_report_rule_enabled`) in the eventbridge module call and deploy —
a DISABLED rule bills nothing and keeps its config.

---

## Arming auto-remediation

⚠️ **Destructive.** Auto-remediation deletes EBS volumes, releases EIPs, and
deletes snapshots. It is guarded by **three independent gates — all must be
open**:

1. **Env-var gate.** Set `AUTO_REMEDIATE = "true"` on the `resource_cleanup`
   module in `terraform/environments/dev/main.tf`, via PR + merge to `main`.
2. **Event-flag gate.** The invocation must carry `auto_remediate: true`.
   Scheduled EventBridge scans send `false` — so you must **manually** start the
   Step Functions execution with `{"auto_remediate": true}`.
3. **Resource-tag gate (IAM).** The target resource must be tagged
   `AutoCleanup = "true"`; the cleanup role's IAM policy denies the delete
   otherwise.

Until all three are satisfied, the cleanup Lambda runs in **dry-run** — it writes
`SKIPPED_DRY_RUN` rows to the remediation-log so you can preview exactly what
*would* be deleted. To preview safely, just run a normal manual scan and inspect
the remediation-log.

---

## Common troubleshooting

**No report email arrived.**
- SNS subscription not confirmed → check `aws sns get-subscription-attributes
  --subscription-arn <full-uuid-arn>` and look at `PendingConfirmation`. The
  authoritative source is `get-subscription-attributes` on the specific ARN —
  the aggregate counters (`get-topic-attributes`, `list-subscriptions-by-topic`)
  are eventually-consistent and can wrongly report 0/Deleted while the sub is
  live. Re-confirm via the link AWS emailed.
- SES identity not verified → in sandbox SES both sender *and* recipient must be
  verified identities. Check SES → Verified identities (ap-south-1). The Lambda
  catches SES `MessageRejected`, logs it, and returns `email_sent: false` rather
  than crashing — so the report is still in S3 even if email failed.

**A CloudWatch alarm didn't fire / can't publish.** Alarms publish to the
KMS-encrypted SNS topic; this requires the `cloudwatch.amazonaws.com` grants on
both the topic policy and the CMK key policy (`cloudwatch_alarms_enabled = true`
on the sns + kms modules). If you cloned the module without those, the alarm
trips but the SNS publish silently fails.

**`terraform plan` shows `source_code_hash` drift with no code change.** Lambda
zips built on Windows differ byte-for-byte from Linux-built zips, so `archive_file`
reports phantom drift. This is expected — the authoritative build is the
Linux GitHub Actions runner. Run `bash scripts/package_lambdas.sh` before a local
plan to minimize noise; let CI be the source of truth for applies.

**Cost scanner flagged a microscopic spike.** A 90× ratio on $0.0009 is
mathematically a spike but operational noise. `MIN_ANOMALY_DOLLARS` (default
`1.0`) floors this — raise it if micro-spend on a near-idle account still leaks
through.

**Security scan shows no Config findings.** Expected — AWS Config is not enabled
(STEP 22.5 deferred). `config_checker.py` catches `NoSuchConfigurationRecorder`
and returns empty; the other security categories still run. Enabling Config will
light this up with no code change.

**CI/deploy fails at assume-role (`Not authorized to perform
sts:AssumeRoleWithWebIdentity`).** The OIDC role ARNs in GitHub repo *variables*
(`AWS_PLAN_ROLE_ARN`, `AWS_DEPLOY_ROLE_ARN`) are missing/wrong, or the trust
policy's `sub` condition doesn't match the repo/branch. Deploy can only assume
its role from `main`; a PR/feature branch will (correctly) get AccessDenied.

**A scanner branch failed but the workflow went green.** By design — each branch
has `Catch → Pass`, so one scanner failing doesn't abort the others. Look at the
branch's `*ScanFailed` Pass output and the Lambda's CloudWatch logs. The
`cloudguard-dev-sfn-execution-failed` alarm only fires on a *genuine* unhandled
workflow failure, not a caught branch failure.
