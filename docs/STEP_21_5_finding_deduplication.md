# STEP 21.5 — Finding Deduplication via Deterministic ID + Upsert

> **Why this doc exists:** A standalone, study-friendly walkthrough of the
> dedup refactor done on 2026-05-31. Designed so you can return to it
> months later (e.g. for an interview, or before STEP 22) and pick up
> the full story without re-reading PROGRESS.md.
>
> **Commits:** `8cafb89` (code + tests + Terraform + PROGRESS) and `e9cb7d7`
> (the PROGRESS commit-hash record). Branch: `ci-smoke-test`.
>
> **Estimated read time:** 25 minutes if you take it slow.

---

## Table of contents

1. [TL;DR — the one-paragraph summary](#1-tldr--the-one-paragraph-summary)
2. [The bug — what was broken](#2-the-bug--what-was-broken)
3. [Concept primer (read this if you forgot the basics)](#3-concept-primer-read-this-if-you-forgot-the-basics)
4. [The design — why we chose upsert](#4-the-design--why-we-chose-upsert)
5. [Code walk-through, file by file](#5-code-walk-through-file-by-file)
6. [The discriminator hotfix (caught in live verification)](#6-the-discriminator-hotfix-caught-in-live-verification)
7. [Verification trace — proving it worked](#7-verification-trace--proving-it-worked)
8. [Interview prep — likely questions and answers](#8-interview-prep--likely-questions-and-answers)
9. [Open TODOs from this STEP](#9-open-todos-from-this-step)
10. [Glossary of every term I might have to explain](#10-glossary-of-every-term-i-might-have-to-explain)

---

## 1. TL;DR — the one-paragraph summary

The CloudGuard security scanner runs every 6 hours. The old code wrote a
findings row with a brand-new `uuid` ID on every scan, so a single
real-world issue (e.g. "SG sg-xxx has SSH open to the world") appeared
4 times in a 24-hour report. I refactored to a **deterministic** finding ID
(SHA-256 hash of `category|resource_id|check_name`) and an **upsert**
write path (Query first → UpdateItem if exists, PutItem if not). Same
issue → same ID → same row → bumped `last_seen` and `occurrence_count`
instead of a duplicate row. Modelled on AWS Security Hub's
`FirstObservedAt` / `LastObservedAt` fields. Result: **50 noisy findings
→ 12 actionable findings, zero information lost.** Reports now show
`"sg-xxx open on port 22 — Seen 12 times since 2026-05-29"` — actionable.

---

## 2. The bug — what was broken

### What I saw in the report

The daily SES report on 2026-05-31 showed **50 findings**:

| Severity | Count |
|----------|-------|
| CRITICAL | 14    |
| HIGH     | 16    |
| MEDIUM   | 4     |
| LOW      | 16    |
| **Total** | **50** |

But my actual AWS account only had ~14 distinct real-world issues. Every
issue was repeated about 4 times.

### Why 4 times?

Three moving parts collided:

**Part 1 — The scanner runs every 6 hours.**
The EventBridge rule `cloudguard-dev-scan-schedule` uses
`rate(6 hours)` (set up in STEP 17). That means **4 scans per 24h**.

**Part 2 — The DynamoDB table schema** (set up in STEP 5):

```
Table: cloudguard-dev-findings
  PK (partition key) : finding_id
  SK (sort key)      : timestamp
```

In DynamoDB, a row is identified by the **combination** of PK and SK.
If two writes have the same `finding_id` but different `timestamp`,
they create **two separate rows**.

**Part 3 — The old code generated a random ID per scan.**
In `src/security_scanner/handler.py`:

```python
f["finding_id"] = str(uuid.uuid4())   # ← random every single call
```

A new uuid every scan → different PK → different row, even if the same
SG is the offender.

### The math check (verifying the diagnosis)

If every issue gets quadrupled, the report numbers should be 4× the
unique-issue counts:

| Severity | Unique issues | × 4 scans | Report showed | Match? |
|----------|---------------|-----------|---------------|--------|
| CRITICAL | 3 SGs port 22 + 2 cost = 5 (the cost ones came from before MIN_ANOMALY_DOLLARS deploy) | — | 14 | yes-ish |
| HIGH     | 4 (sg 8080, abhithV1 admin, abhithV1 no MFA, EBS unencrypted) | 16 | 16 | ✓ |
| MEDIUM   | 1 (abhithV1 access key 180d old) | 4 | 4 | ✓ |
| LOW      | 4 (4 buckets versioning disabled) | 16 | 16 | ✓ |

The math fits → the diagnosis is correct.

---

## 3. Concept primer (read this if you forgot the basics)

### DynamoDB primary keys: PK and SK

DynamoDB tables have a **primary key** which is either:
- **Just a PK** (e.g. `user_id`) — one row per PK value.
- **PK + SK together** (e.g. `user_id` + `order_date`) — multiple rows per
  PK value, each uniquely identified by the SK.

Findings table has the second form: `PK=finding_id, SK=timestamp`.

A row is identified by **(PK, SK) together**. So:
- Same PK + same SK → **same row** (next write overwrites).
- Same PK + different SK → **two different rows**.

This is exactly why the random-uuid pattern produced duplicates: each
scan produced a new SK (timestamp = now), so the (PK, SK) was always
unique → always a new row.

### Idempotency

"Idempotent" means: **running an operation twice has the same effect as
running it once.** For our scanner:
- **Old behavior (non-idempotent):** scan twice → 2 rows.
- **New behavior (idempotent):** scan twice → 1 row (with `occurrence_count: 2`).

Idempotency is the property we want. The way to get it is to make the
write logic re-runnable without producing duplicates.

### Why a hash for the ID?

A **deterministic** ID means: same inputs → same output, every time.
A hash function (like SHA-256) is the standard way to produce a
deterministic, fixed-length, well-distributed ID from variable inputs.

```
SHA-256("security|sg-0aa84|sg_open_to_world:tcp:22-22")
  → "4f3b9c2a1d8e5f6a9b0c3d4e5f6a7b8c..." (always the same)
```

If the same `(category, resource_id, check_name)` always produces the
same hash, we can use that hash as `finding_id` and have a stable
identity for "this specific real-world issue".

### Why pipe-delimited inputs?

Without a delimiter:

```
hash("foo" + "bar" + "baz") == hash("foobar" + "baz") == hash("foob" + "arbaz")
```

All produce `hash("foobarbaz")`. **Different inputs map to the same hash
— a collision bug.**

With a delimiter:

```
hash("foo|bar|baz") != hash("foobar||baz") != hash("foob|arbaz")
```

Each set of inputs produces a distinct string → distinct hash. The pipe
`|` works because it's illegal in AWS resource IDs.

### Upsert (UPdate-or-inSERT)

"Upsert" is shorthand for **"update the row if it exists, insert it if
it doesn't"**. DynamoDB doesn't have a single primitive called UPSERT.
We build it from two primitives:

1. `Query` — does this PK exist already?
2. `UpdateItem` (if yes) or `PutItem` (if no).

That two-call pattern is what `shared.dynamo_client.upsert_finding` does.

### "First seen" vs "last seen" — Security Hub pattern

AWS Security Hub tracks two timestamps per finding:
- **FirstObservedAt** — when did we first see this issue? **Immutable.**
- **LastObservedAt** — when did we last confirm this issue is still
  active? **Updated on every re-detection.**

Plus an **occurrence count** — how many times has this finding been
re-confirmed? Useful for "this has been broken for 30 scans, it's not
going away on its own".

That's the pattern we adopted.

---

## 4. The design — why we chose upsert

### Two options I considered

| Option | What it means | Why rejected / picked |
|--------|---------------|------------------------|
| **A. Change the DynamoDB schema** — drop the SK so `finding_id` alone identifies a row. | Destroy & recreate the table. | **Rejected.** Loses the two GSIs (`severity-index`, `category-index`) built in STEP 5. Multi-minute Terraform destroy/recreate cycle. Loss of all existing data, and the schema choice from STEP 5 was correct for an append-only model — it's the *write pattern* that needs to change, not the schema. |
| **B. Keep schema, change write pattern** — deterministic finding_id + upsert. | Code-only refactor, no Terraform schema diff. | **Picked.** Works with existing schema by *rewriting the SK semantic*: SK timestamp becomes the immutable `first_seen`; a separate `last_seen` attribute is the mutable "still active" timestamp. |

### Trade-offs of option B

The fix has a real cost, and you should be honest about it in interviews:

- **Cost:** one extra round trip per finding. Old code: 1× batched
  `BatchWriteItem` for all 50 findings. New code: 50× (`Query` + `Put`/`Update`).
- **At our scale:** 50 findings × 4 scans/day = 200 ops/day. Negligible
  in $/month and latency.
- **At 10× the scale:** ~2000 ops/day. Still negligible.
- **At 1000× the scale:** ~200k ops/day. Now worth considering an
  optimization (e.g. batch into a single transaction, or use
  `BatchGetItem` then `BatchWriteItem` for the misses).

The cost is acceptable for CloudGuard's profile.

---

## 5. Code walk-through, file by file

### 5.1 `src/shared/dynamo_client.py` — three new helpers

This file is the shared library that all 4 Lambdas import. I added
three new public functions.

#### `compute_finding_id(category, resource_id, check_name)`

```python
def compute_finding_id(category, resource_id, check_name):
    key = f"{category}|{resource_id}|{check_name}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
```

**What each line does:**
- `key = f"{category}|{resource_id}|{check_name}"` — join inputs with
  the `|` delimiter to prevent concat collisions (see concept primer
  above for why).
- `.encode("utf-8")` — SHA-256 takes bytes, not strings. UTF-8 is the
  standard text encoding.
- `hashlib.sha256(...).hexdigest()` — compute the hash, return as a
  64-character hex string (each hex char is 4 bits, 64×4 = 256 bits).
- `[:32]` — truncate to 32 hex chars (128 bits of entropy). At our
  expected scale (thousands of findings), the collision probability is
  negligible. Short enough to read in the DynamoDB console.

**Property:** same inputs always produce the same output. That's the
foundation of everything else.

#### `upsert_finding(table_name, finding, dynamodb_resource=None)`

This is the heart of the fix. Annotated heavily:

```python
def upsert_finding(table_name, finding, dynamodb_resource=None):
    # Step 0: resolve the DynamoDB resource — production uses the cached
    # module-scope resource (fast, warm); tests inject a MagicMock.
    resource = dynamodb_resource or _get_resource()
    table = resource.Table(table_name)

    finding_id = finding["finding_id"]   # already computed by the caller
    now_iso    = finding["timestamp"]    # "now" — used as SK if first sight
    expires_at = finding["expires_at"]   # TTL epoch seconds

    # Step 1: Query by PK only. Returns 0 or 1 items.
    # Limit=1 because we don't need all rows, just "does any row exist?"
    existing = table.query(
        KeyConditionExpression=Key("finding_id").eq(finding_id),
        Limit=1,
    ).get("Items", [])

    if existing:
        # Step 2a: row exists → UpdateItem on the (PK, EXISTING SK)
        #
        # Why use the existing SK and not `now`?
        # UpdateItem needs the FULL primary key to identify the row.
        # If I passed timestamp=now, DynamoDB would say "row not found"
        # and silently insert a new row → back to the original bug.
        existing_sk = existing[0]["timestamp"]
        prior_count = int(existing[0].get("occurrence_count", 1))
        table.update_item(
            Key={"finding_id": finding_id, "timestamp": existing_sk},
            UpdateExpression=(
                "SET last_seen = :ls, "
                "occurrence_count = :oc, "
                "expires_at = :ea, "
                "severity = :sv, "
                "description = :desc"
            ),
            ExpressionAttributeValues=_coerce_decimals({
                ":ls": now_iso,
                ":oc": prior_count + 1,
                ":ea": expires_at,
                ":sv": finding["severity"],
                ":desc": finding.get("description", ""),
            }),
        )
        return "updated"

    # Step 2b: first sight → PutItem with full row
    item = dict(finding)
    item.setdefault("first_seen", now_iso)
    item.setdefault("last_seen", now_iso)
    item.setdefault("occurrence_count", 1)
    table.put_item(Item=_coerce_decimals(item))
    return "inserted"
```

**Why update `severity` and `description` on re-sight, not just `last_seen`?**

A finding can *reclassify* between scans. Example: today the SG has SSH
open to the world → CRITICAL. Tomorrow you add a tag that AWS Config
uses to reclassify it as MEDIUM → severity changes. The report should
show the *current* severity, not stale CRITICAL from first detection.
Same logic for description (encodes today's specific details).

**Why `existing[0].get("occurrence_count", 1)` with default `1`?**

Pre-STEP-21.5 rows (the legacy uuid ones) don't have an
`occurrence_count` field. Defaulting to 1 + incrementing means the first
re-sight on a legacy row writes `occurrence_count: 2` correctly.

**Why `Limit=1`?**

We don't need to see all matching rows, just know that at least one
exists. `Limit=1` reduces both RCU cost and response size.

#### `batch_upsert_findings(table_name, findings, dynamodb_resource=None)`

```python
def batch_upsert_findings(table_name, findings, dynamodb_resource=None):
    counts = {"inserted": 0, "updated": 0, "total": 0}
    if not findings:
        return counts
    for finding in findings:
        action = upsert_finding(table_name, finding, dynamodb_resource)
        counts[action] += 1
        counts["total"] += 1
    return counts
```

**Why a sequential loop and not `BatchWriteItem`?**

`BatchWriteItem` is a pure-write batch API. It can't do
"read-then-conditional-write". Since `upsert_finding` does a Query
first, the operation can't be batched. The loop is acceptable at our
scale.

---

### 5.2 `terraform/modules/iam/main.tf` — IAM grants for the new ops

The new `upsert_finding` function calls TWO DynamoDB operations the old
roles didn't have:
- `dynamodb:Query` — for the existence check
- `dynamodb:UpdateItem` — for the re-sight bump

I added both to the 3 writer roles (cost_scanner, security_scanner,
resource_cleanup). The report_generator role is unchanged — it only
reads.

```hcl
# Before
Action = ["dynamodb:PutItem", "dynamodb:BatchWriteItem"]

# After
Action = [
  "dynamodb:PutItem",
  "dynamodb:UpdateItem",       # NEW: for the upsert update path
  "dynamodb:BatchWriteItem",   # KEPT: cost-data table still uses it
  "dynamodb:Query"             # NEW: for the existence check
]
```

**Why kept `BatchWriteItem`?**

The `cost-data` table has `PK=date, SK=service_name` — re-writing the
same `(2026-05-31, AmazonEC2)` row twice just overwrites. It's naturally
idempotent and uses `batch_put_findings`. So we keep the grant.

---

### 5.3 `src/cost_scanner/cost_analyzer.py`

The `store_findings` function. Changes:

```python
# BEFORE
"finding_id": str(uuid.uuid4()),     # random per call

# AFTER
"finding_id": compute_finding_id(
    "cost", anomaly["service"], "cost_anomaly_30d_baseline"
),
```

And the write call changed:

```python
# BEFORE
return batch_put_findings(table_name, items)

# AFTER
return batch_upsert_findings(table_name, items)
```

The `import uuid` is removed (no longer used).

**Semantic effect:** if "AWS Lambda cost spiked above baseline" is
detected on Monday, then again Tuesday, it's the SAME row with
`occurrence_count: 2`. Today's `actual_cost` and `ratio` overwrite
yesterday's via the description bump in `upsert_finding`.

---

### 5.4 `src/security_scanner/handler.py`

The `_stamp_findings` function. Changes:

```python
# BEFORE
f["finding_id"] = str(uuid.uuid4())

# AFTER
f["finding_id"] = compute_finding_id(
    f["category"], f["resource_id"], f["check_name"]
)
```

In `lambda_handler`, the call changed:

```python
# BEFORE
written = batch_put_findings(findings_table_name, all_findings)
summary = {"total_findings": written, ...}

# AFTER
upsert_counts = batch_upsert_findings(findings_table_name, all_findings)
summary = {
    "total_findings": upsert_counts["total"],
    "new_findings": upsert_counts["inserted"],      # newly seen this scan
    "updated_findings": upsert_counts["updated"],   # re-confirmed existing
    ...
}
```

The new `new_findings` / `updated_findings` split shows up in CloudWatch
logs — useful for debugging "is the scanner actually detecting new
issues, or just confirming existing ones?"

---

### 5.5 `src/resource_cleanup/handler.py`

Same shape as security_scanner. `_stamp_findings` uses `compute_finding_id`,
the findings write uses `batch_upsert_findings`.

**Important distinction kept:** the `remediation_log` write STILL uses
`batch_put_findings` with uuid. Why?

Each remediation attempt IS a discrete event:

| Time  | Action                              | Status         |
|-------|-------------------------------------|----------------|
| 10:00 | delete vol-X                        | SUCCESS        |
| 10:01 | delete vol-Y                        | FAILED         |
| 14:00 | delete vol-X (a different attempt)  | SKIPPED_DRY_RUN |

These are separate audit rows, not a single recurring observation.
**Different data semantics → different storage strategy.** Don't blindly
apply the same pattern everywhere.

---

### 5.6 `src/report_generator/handler.py`

The findings query filter changed:

```python
# BEFORE
findings = _scan_with_filter(findings_table, Attr("timestamp").gte(cutoff_iso))

# AFTER
findings = _scan_with_filter(
    findings_table,
    Attr("last_seen").gte(cutoff_iso) | Attr("timestamp").gte(cutoff_iso),
)
```

**Why the `|` (OR) clause?**

During the transition, two kinds of rows could exist in the table:
1. **New STEP-21.5 rows** have a `last_seen` attribute.
2. **Old legacy rows** (if any escape the cleanup script) only have
   `timestamp` and no `last_seen`.

DynamoDB's `Scan + FilterExpression` silently excludes rows where the
referenced attribute is missing. The OR clause covers both row shapes
so legacy rows aren't dropped from the report.

After the cleanup script ran (purged 103 legacy rows), this OR clause
is vestigial — can be simplified to plain `Attr("last_seen").gte(...)`
in a future STEP. Left it in for safety.

The `remediation_log` filter stays on `timestamp` — that table is
unchanged.

---

### 5.7 `src/report_generator/html_builder.py`

Added a "Seen N times since DATE" caption to each finding row, only when
`occurrence_count > 1`:

```python
occ = int(f.get("occurrence_count", 1))
occ_note = (
    f'<br><span style="{_MUTED}">Seen {occ} times since '
    f'{html.escape(str(f.get("first_seen", f.get("timestamp", ""))[:10]))}</span>'
    if occ > 1
    else ""
)
```

**Line by line:**
- `f.get("occurrence_count", 1)` — defaults to 1 for legacy rows.
- `occ > 1` guard — first-sight findings don't get a noisy
  "Seen 1 times" caption.
- `f.get("first_seen", f.get("timestamp", ""))` — try `first_seen`
  first (new rows), fall back to `timestamp` (legacy rows).
- `[:10]` — slice the first 10 chars of an ISO timestamp like
  `2026-05-29T10:00:00+00:00` → `2026-05-29`. Just the date.
- `html.escape(...)` — XSS defense. Required because we render
  user-controlled DynamoDB content directly into HTML.

The report now says **"SG sg-xxx open on port 22 → Seen 12 times since
2026-05-29"** — instantly actionable.

---

### 5.8 `scripts/cleanup_old_findings.py` (NEW)

A one-shot script to purge the legacy uuid-keyed rows AFTER deploying
the new code. Without it, you'd have a mix of old uuid rows and new
deterministic rows in the table — duplicates would persist.

**Two safety gates:**
1. **Dry-run by default.** No `--confirm` flag → just prints what would
   be deleted, no API calls.
2. **`--table <name>` is required**, no default. Impossible to
   accidentally purge `cost-data` or `remediation-log`.

This mirrors the same "explicit opt-in for destruction" pattern as the
cleanup Lambda's two-gate auto-remediate from STEP 12. Consistent design.

**Usage:**
```powershell
# Dry-run — shows you the count, no delete
python scripts/cleanup_old_findings.py --table cloudguard-dev-findings

# Actually delete
python scripts/cleanup_old_findings.py --table cloudguard-dev-findings --confirm
```

---

### 5.9 Tests — 12 new tests, 121 total

- **`tests/test_shared.py` (+9 tests)** — covers `compute_finding_id`
  (deterministic, distinct, 32-char hex, delimiter prevents concat
  collision), `upsert_finding` (first sight calls PutItem, re-sight
  calls UpdateItem with the EXISTING SK, missing count defaults to 2),
  `batch_upsert_findings` (empty no-op, mixed insert+update counts).
- **`tests/test_cost_scanner.py` (+2 + edits)** — old uuid length
  assertion (36) updated to hex hash assertion (32 chars, all hex
  digits). New `test_finding_id_is_deterministic_across_runs` proves
  two calls with the same anomaly produce identical IDs.
- **`tests/test_report_generator.py` (+2 tests)** —
  `test_occurrence_count_rendered_when_greater_than_one` verifies the
  "Seen N times since DATE" caption renders;
  `test_occurrence_count_one_not_rendered` verifies no noisy caption
  for first-sight findings.

Final test count: **121 passed** (was 109; +12).

---

## 6. The discriminator hotfix (caught in live verification)

This is the bug that unit tests didn't catch. It only manifested when
real AWS data hit the upsert path.

### What happened

After the first apply + cleanup, I ran the first SFN scan to repopulate
the table. Expected ~12 rows (matching the unique-issue count). Got 11.

I checked the table and noticed: `sg-0f815d19630ec7643` had TWO open
ingress rules — port 22 (CRITICAL) AND port 8080 (HIGH) — but only
ONE row existed. The port 8080 finding was silently overwritten.

### Why

Both findings went through `_stamp_findings` with:
- `category = "security"` (same)
- `resource_id = "sg-0f815d19630ec7643"` (same)
- `check_name = "sg_open_to_world"` (same)

`compute_finding_id` produces the **same hash** → same `finding_id` →
upsert path saw "row already exists" → `UpdateItem` overwrote severity
and description with whichever rule was processed second.

### The fix — promote the discriminator into `check_name`

In `sg_checker.py`:

```python
# BEFORE
"check_name": "sg_open_to_world",

# AFTER
"check_name": f"sg_open_to_world:{proto or '-1'}:{port_label}",
```

Now port 22 produces `check_name = "sg_open_to_world:tcp:22-22"` and
port 8080 produces `check_name = "sg_open_to_world:tcp:8080-8080"`.
Different inputs to `compute_finding_id` → different IDs → two distinct
rows in the table.

### Same pattern applied to iam_checker

Users can have multiple access keys, each with its own age and
last-used date. Without a discriminator, all of a user's old keys would
collapse to one row.

```python
# BEFORE
"iam_access_key_old"

# AFTER
f"iam_access_key_old:{key_id}"
```

### Other checkers — verified naturally unique

| Checker          | Why no discriminator needed |
|------------------|------------------------------|
| `s3_checker`     | 4 sub-checks per bucket, each with a distinct `check_name` (`s3_no_pab`, `s3_versioning_disabled`, etc.) |
| `ebs_checker`    | One check per volume (encryption). One row per volume. |
| `config_checker` | Already uses `f"config_rule:{rule_name}"` which is distinct per rule. |
| `zombie_finder`  | One check_name per zombie type per resource_id. |

### Meta-lesson (interview-grade)

The dedup primary key isn't `(resource, check)` — it's
`(resource, *what specifically went wrong with this resource*)`.
**Unit tests can't catch this class of bug** — each checker passes
its tests in isolation because it emits correct individual findings.
The bug only manifests at the dedup boundary when real data
(multi-rule SGs, multi-key users) flows through.

**Live verification is essential.** I caught this by running
`aws dynamodb scan --select COUNT` immediately after the first
repopulation, noticed the count was lower than expected, and
investigated. That's the loop that catches integration bugs.

---

## 7. Verification trace — proving it worked

This is the part you'd walk an interviewer through. Run-by-run:

| # | Action | Result |
|---|--------|--------|
| 1 | `terraform apply` (deploy #1) | 0 add, 7 change, 0 destroy (3 IAM + 4 Lambdas) |
| 2 | `python scripts/cleanup_old_findings.py --table ... --confirm` | Deleted 103 legacy uuid rows |
| 3 | `aws stepfunctions start-execution ...` | SUCCEEDED in ~13 s |
| 4 | `aws dynamodb scan --select COUNT` | **11 rows** ← off by one, port 8080 missing! |
| 5 | Discriminator hotfix (sg_checker + iam_checker check_name format) | Code fix in-session |
| 6 | `terraform apply` (deploy #2) | 0 add, 1 change (security_scanner Lambda code) |
| 7 | Cleanup 11 stale rows + re-scan | **12 rows** ← port 22 + port 8080 both present |
| 8 | Third scan (idempotency test) | All 12 rows now `occurrence_count: 2` ✓ |
| 9 | Invoked report_generator manually | `{"findings_count": 12, "email_sent": true}` |

**The win:** 50 noisy findings → 12 actionable findings, zero
information lost.

### Final dedup tally

| Severity | Old report (uuid + scan time) | New report (deterministic + upsert) |
|----------|-------------------------------|--------------------------------------|
| CRITICAL | 14                            | 3 (3 SGs port 22 to world)           |
| HIGH     | 16                            | 4 (1 EBS + 2 IAM + 1 SG port 8080)   |
| MEDIUM   | 4                             | 1 (IAM access key 180d old)          |
| LOW      | 16                            | 4 (4 buckets versioning disabled)    |
| **TOTAL**| **50**                        | **12**                               |

**76% reduction in row count, 100% retention of distinct real-world
issues.**

---

## 8. Interview prep — likely questions and answers

These are the answers you'd give. Memorize the *shape*, not the exact
words.

### Q1. "Tell me about a bug you found and fixed yourself, end-to-end."

> "My CloudGuard daily report showed 50 findings against an account I
> knew had ~14 real issues. The scanner runs every 6 hours and was
> generating a new uuid finding_id every run, so a 24-hour report window
> picked up ~4 copies of every active finding. I refactored to a
> deterministic finding_id — SHA-256 of `category|resource_id|check_name`,
> 32-char hex, with a pipe delimiter to avoid concat-ambiguity — and an
> idempotent upsert path: Query by PK → UpdateItem on hit, PutItem on
> miss. Modelled on AWS Security Hub's FirstObservedAt / LastObservedAt
> fields. The SK semantic shifted: `timestamp` is now the immutable
> first_seen value, and `last_seen` is the mutable 'is this still
> active' attribute the report filters on. Reports now show
> 'SG sg-xxx open on port 22 — Seen 12 times since 2026-05-29' —
> actionable instead of noisy."

### Q2. "Why didn't you just change the DynamoDB schema?"

> "Dropping the SK would require destroying and recreating the table,
> which loses the two GSIs we built on `severity` and `category` in
> STEP 5. The upsert pattern works with the existing schema by rewriting
> the SK semantic in code — `timestamp` becomes immutable `first_seen`,
> and a separate `last_seen` attribute is the mutable 'still active'
> timestamp. The trade-off is one extra Query per write instead of a
> batched BatchWriteItem, but at ~50 findings × 4 scans/day = 200 ops/day,
> that cost is a rounding error compared to the multi-minute
> destroy/recreate cycle and the GSI loss."

### Q3. "Did you catch all the edge cases up front?"

> "No, and that's the honest answer. Unit tests passed because each
> checker emits correct individual findings. But the first live
> verification scan after deploy showed only 11 rows when I expected 12.
> The same SG with rules on BOTH port 22 and port 8080 collapsed into
> one row because they shared `(category, resource_id, check_name)` →
> identical finding_ids → the second UpdateItem silently overwrote the
> first's severity. I fixed it by promoting the offending sub-resource
> (port + protocol, or access-key-id for IAM) into check_name itself:
> `sg_open_to_world:tcp:22-22` vs `sg_open_to_world:tcp:8080-8080`. The
> meta-lesson: the dedup primary key isn't `(resource, check)`, it's
> `(resource, what specifically went wrong)`. Live verification — running
> `aws dynamodb scan` against real data — was the only way to catch this.
> Mocks couldn't model it."

### Q4. "How did you safely clean up the existing data?"

> "Two-gate safety on the cleanup script. Dry-run is the default — you
> have to pass `--confirm` to actually delete. And it requires the
> table name explicitly, with no default, so you can't accidentally
> purge cost-data or remediation-log. Same explicit-opt-in pattern as
> the cleanup Lambda's two-gate auto-remediate from STEP 12 —
> consistent design across the codebase."

### Q5. "What's the trade-off of the upsert pattern?"

> "One extra Query per write instead of a batched BatchWriteItem. At our
> scale — ~50 findings × 4 scans/day = 200 ops/day — it's negligible. At
> 1000× the scale (~200k ops/day) it'd be worth considering an
> optimization: maybe batch the existence checks via BatchGetItem, then
> BatchWriteItem for the misses. But that's premature optimization
> right now. The current code is correct and readable."

### Q6. "Why update severity and description on re-sight, not just last_seen?"

> "A finding can reclassify between scans. Imagine an SG with port 22
> open today → CRITICAL. Tomorrow someone adds a tag that AWS Config
> uses to reclassify it as MEDIUM → severity changes. The report should
> show the *current* severity, not stale CRITICAL from first detection.
> Same logic for description, which encodes the actual ratio or count
> at scan time. `first_seen` and SK timestamp stay immutable —
> those are the audit trail. Everything else is current-state."

### Q7. "What's a follow-up you'd want to do next?"

> "Simplify the report's `Attr('last_seen') | Attr('timestamp')` OR
> clause to plain `Attr('last_seen').gte(cutoff_iso)`. The OR is
> backward-compat for pre-21.5 rows that don't have a `last_seen`
> attribute — now that the cleanup script has run and all legacy rows
> are gone, the OR is vestigial. Two-line change; deferred to keep the
> STEP 21.5 diff focused."

---

## 9. Open TODOs from this STEP

| Item | Why |
|------|-----|
| Simplify the OR clause in `report_generator/handler.py` to just `Attr("last_seen").gte(...)` | Once all legacy rows are confirmed gone, the OR is vestigial. |
| Audit `aws dynamodb scan` for any rows missing `first_seen` / `last_seen` / `occurrence_count` | If any escape, re-run the cleanup script. |
| Consider GSI on `last_seen` if findings volume crosses ~10k | Today's Scan+Filter is fine; future scale may justify Query. |
| Carried from STEP 18.5 slot: scope `ses:FromAddress`, scope EC2 destructive actions with tag Condition | Hardening pass before STEP 23 documentation. |

---

## 10. Glossary of every term I might have to explain

| Term | Definition |
|------|------------|
| **PK / Partition Key** | The required primary identifier in DynamoDB. Distributes data across partitions for scale. |
| **SK / Sort Key** | Optional second component of the primary key. Allows multiple rows per PK, ordered by SK. |
| **Composite key** | A PK + SK pair together — the full identity of a row. |
| **GSI / Global Secondary Index** | A separate copy of the table with a different PK/SK, queryable like the main table. Used here for `severity-index` and `category-index`. |
| **TTL (Time To Live)** | DynamoDB feature that auto-deletes rows after `expires_at` (epoch seconds). Used here for the 90-day finding retention. |
| **Idempotency** | Property where running an operation multiple times produces the same result as running it once. |
| **Upsert** | UPdate-or-inSERT — a write that updates if the row exists, inserts if not. |
| **SHA-256** | Cryptographic hash function producing a 256-bit (64 hex char) output. Same inputs → same output, every time. |
| **Hex digest** | The output of a hash function expressed as hexadecimal (chars 0-9, a-f). |
| **Concat collision** | When string concatenation produces the same result for different input tuples. Avoided by using a delimiter. |
| **Scan vs Query** | `Scan` reads every row in the table (expensive); `Query` reads only rows matching a PK condition (cheap). |
| **FilterExpression** | A condition applied AFTER a Scan or Query — filters out non-matching rows in the response. Doesn't reduce RCU cost. |
| **BatchWriteItem** | DynamoDB API that writes up to 25 items in one request. Pure write, no conditional logic. |
| **UpdateExpression** | A DynamoDB syntax like `"SET field = :value"` used to update individual attributes. |
| **ExpressionAttributeValues** | Placeholder substitutions for an UpdateExpression. The `:ls` in the expression maps to a value here. |
| **FirstObservedAt / LastObservedAt** | AWS Security Hub finding fields. The pattern we adopted. |
| **RCU / WCU** | Read Capacity Unit / Write Capacity Unit — DynamoDB's billing units. PAY_PER_REQUEST mode bills per actual op. |
| **`Attr()` / `Key()`** | boto3 expression builders for FilterExpression and KeyConditionExpression respectively. |
| **`html.escape()`** | Python stdlib function that converts `<`, `>`, `&` etc. into HTML entities — prevents XSS. |
| **XSS (Cross-Site Scripting)** | Vulnerability where untrusted content injects executable HTML/JS into a page. Defense is to escape on render. |
| **EventBridge `rate(6 hours)`** | A scheduled rule format: fires every 6 hours from the rule's creation time. Different from `cron(...)` which fires at fixed times. |

---

**End of doc.**

Last updated: 2026-05-31. Commit: `8cafb89` on `ci-smoke-test`.
