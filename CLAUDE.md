# CLAUDE.md — Instructions for Claude Code

> This file is auto-loaded by Claude Code every session. It sets the rules.
> Drop this at the **root** of the `cloudguard/` repo.

## Project Context

You are helping a learner build **CloudGuard** — Project 1 from the AWS Cloud/DevOps 12 LPA Job Blueprint by Abhith B N. The goal is to land a 12 LPA DevOps role in Bengaluru, 2026.

The full spec is in `PROJECT_BLUEPRINT.md` at the repo root. **Read it before doing anything in any session.** It has 23 numbered STEPs. Each session executes one STEP unless the human explicitly asks for more.

## Your Operating Rules

1. **One STEP per session.** Do not "get ahead" by doing STEP 5 when asked for STEP 4. Tight scope = real learning.
2. **Read the relevant STEP section from `PROJECT_BLUEPRINT.md` first.** Quote the exact step text back at me before writing code, so we're aligned.
3. **Explain your choices, briefly.** After generating each meaningful file, write 2–3 sentences in chat: what you wrote, what AWS/Terraform concept it demonstrates, and one alternative you considered. The interviewer will ask "why did you do it this way?" — I need to hear the reasoning, not just see the code.
4. **Never run `terraform apply` without explicit confirmation.** `terraform init` and `terraform plan` are fine. `apply` is a one-shot bullet — always ask "ready to apply? this will create AWS resources that may cost money."
5. **Never run `aws` CLI commands that mutate state without explicit confirmation.** Read-only `describe`, `list`, `get` is fine. Anything creating/deleting needs my "go".
6. **Never commit secrets.** If you see AWS access keys, account IDs, email addresses, Slack webhook URLs in code, stop and flag. Put them in `terraform.tfvars` (gitignored) or AWS Secrets Manager.
7. **Default region: `ap-south-1` (Mumbai).** I'm in India.
8. **Be honest about gaps.** If the blueprint is vague on something (e.g., exact KMS key policy JSON) and you have to make a judgment call, say so and explain the call. Don't fake confidence.
9. **Test before declaring done.** A STEP isn't "complete" until `terraform plan` succeeds for IaC steps, or `pytest -v` passes for Python steps.
10. **When I ask "why X over Y", give the actual engineering trade-off**, not generic praise. Example: "ALB does Layer 7 routing and host/path-based rules, NLB does Layer 4 with static IPs and millions of req/s. Pick ALB for HTTP, NLB for TCP/UDP or extreme throughput."

## Repository Conventions

- All Terraform in `terraform/`. Two environments: `dev/` and `prod/`. Modules shared under `terraform/modules/`.
- All Python Lambda source in `src/<function_name>/`. Shared utilities in `src/shared/`.
- All tests in `tests/`. Use `pytest` and `moto` (or `unittest.mock`) for AWS mocks.
- Scripts in `scripts/`. Docs in `docs/`.
- Branch strategy: feature branches off `main`. PRs trigger CI. Merge to `main` triggers deploy.
- Commit style: `STEP N: <short description>` (e.g., `STEP 4: Build IAM Terraform module`).

## Stack (Pinned)

- Python 3.12
- Terraform >= 1.5
- AWS provider ~> 5.0
- boto3 latest
- Node.js (only for any Lambda layer tooling — Python is primary)

## What to Do at the Start of Each Session

1. Run `ls` and `cat PROJECT_BLUEPRINT.md | head -50` to remind yourself of the project.
2. Ask me: "Which STEP are we doing today?"
3. After I answer, locate that STEP in `PROJECT_BLUEPRINT.md`, quote it, and confirm you understand before writing any code.

## What Done Looks Like for the Whole Project

The "Definition of Done" checklist at the bottom of `PROJECT_BLUEPRINT.md` is the final exam. Do not declare the project complete until every box is checked, especially the interview questions at the end.
