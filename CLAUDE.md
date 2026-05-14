# CLAUDE.md — Instructions for Claude Code

> This file is auto-loaded by Claude Code every session. It sets the rules.
> Lives at the **root** of the `cloudguard/` repo.

## Project Context

You are helping a learner build **CloudGuard** — Project 1 from the AWS Cloud/DevOps 12 LPA Job Blueprint by Abhith B N. The goal is to land a 12 LPA DevOps role in Bengaluru, 2026.

**Three files at the repo root work together:**

| File | Role | Modify? |
|---|---|---|
| `PROJECT_BLUEPRINT.md` | The spec — recipe for all 23 STEPs. | **Never.** Static. |
| `CLAUDE.md` | This file — operational rules for Claude Code. | Only when rules change. |
| `PROGRESS.md` | Running log — what's done, decisions, problems. | **At the end of every session.** |

## Operating Rules

1. **One STEP per session.** Do not get ahead. Tight scope = real learning.
2. **At the start of every session, read all three root files** before doing anything else. Tell the user which STEP they're on per `PROGRESS.md` and ask whether to proceed with the next one.
3. **Before writing code, quote the relevant STEP from `PROJECT_BLUEPRINT.md`** so the user can confirm alignment. Wait for "go" before generating files.
4. **At the end of every STEP, update `PROGRESS.md`:**
   - Mark the STEP ✅, fill in the completed date.
   - List key decisions and the alternatives you considered.
   - List files added or modified, and the commit hash.
   - Note any surprises, deviations from the blueprint, or lessons.
   - Update the "Current Status" header at the top (last completed STEP, next up).
   - Add a row to the Decision Log if a cross-cutting choice was made.
   - Add an Interview Prep Note for the STEP — what would I say in an interview about this work?
5. **Explain your choices, briefly.** For each meaningful file you create, 2–3 sentences: what it is, what concept it demonstrates, one alternative you considered.
6. **Never run `terraform apply` without explicit confirmation.** `terraform init` and `terraform plan` are fine. `apply` is one-shot — always ask: *"Ready to apply? This will create AWS resources that may cost money."*
7. **Never run state-mutating `aws` CLI commands without explicit confirmation.** Read-only `describe` / `list` / `get` is fine. Anything creating, modifying, or deleting needs explicit go.
8. **Never commit secrets.** If you spot AWS access keys, account IDs, email addresses, Slack webhook URLs in code — stop and flag. Move them to `terraform.tfvars` (gitignored) or AWS Secrets Manager.
9. **Default region: `ap-south-1`** (Mumbai). User is in Chennai.
10. **Be honest about gaps.** If the blueprint is vague and you have to make a judgment call, say so and explain the call. Don't fake confidence.
11. **Test before declaring done.** A STEP isn't ✅ until `terraform plan` succeeds (for IaC) or `pytest -v` passes (for Python).
12. **For "why X over Y" questions, give the actual engineering trade-off**, not generic praise. Example: "ALB does Layer 7 routing with host/path-based rules and WebSocket support. NLB is Layer 4, has static IPs, handles millions of req/s with lower latency. Pick ALB for HTTP/HTTPS; NLB for raw TCP/UDP or extreme throughput."

## Special Instruction — First Session That Reads This Updated CLAUDE.md

If `PROGRESS.md` exists and its STEP 1 and STEP 2 entries contain "Retro-fill needed" warnings, **your first task this session is to retroactively populate those entries** before doing anything else:

1. Inspect the repo: `ls -la`, `git log --oneline`, `cat .gitignore`.
2. From what's on disk, determine what you can (folder structure created, gitignore patterns, etc.).
3. Ask the user for what you can't determine from the repo:
   - Versions of Python, AWS CLI, Git, VS Code extensions
   - AWS account type (personal vs Cognizant)
   - Repo URL and local path
   - Any decisions or surprises they remember from STEPs 1–2
4. Update `PROGRESS.md` with real values, removing the "Retro-fill needed" warnings.
5. Commit: `git add PROGRESS.md && git commit -m "STEP 1-2: retroactive progress log entries"`
6. **Then** ask the user whether to start STEP 3.

## End-of-Session Protocol

When the user says they're done for the session, or when a STEP is complete, run through this checklist:

- [ ] All new files staged and committed with a `STEP N: <description>` message.
- [ ] `PROGRESS.md` updated and committed (can be the same commit as the code, or a separate one).
- [ ] If `terraform apply` was run, confirm the resources match the plan output.
- [ ] If unit tests exist for this STEP, confirm `pytest -v` passes.
- [ ] Remind the user: close the session and start a fresh one for the next STEP (to reset the context window).

## Repository Conventions

- All Terraform under `terraform/`. Two environments: `dev/` and `prod/`. Modules shared under `terraform/modules/`.
- All Python Lambda source under `src/<function_name>/`. Shared utilities under `src/shared/`.
- All tests under `tests/`. Use `pytest` + `moto` (or `unittest.mock`) for AWS mocks.
- Scripts under `scripts/`. Docs under `docs/`.
- Branch strategy: feature branches off `main`. PRs trigger CI. Merge to `main` triggers deploy.
- Commit style: `STEP N: <short description>` (e.g., `STEP 4: Build IAM Terraform module`).

## Stack (Pinned)

- Python 3.12
- Terraform >= 1.14
- AWS provider `~> 5.0`
- boto3 latest
- AWS CLI v2 (>= 2.32)

## What Done Looks Like

The "Definition of Done" checklist at the bottom of `PROJECT_BLUEPRINT.md` is the final exam. Pay especially close attention to the interview questions listed there — the user must be able to answer them without reading from the code.