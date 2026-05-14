# First Prompt for Claude Code (Session 1)

> Once Claude Code is installed and you're in the `cloudguard/` repo, paste this **exact** message as your first prompt.

---

I'm starting a new project called CloudGuard — Project 1 from the AWS Cloud/DevOps 12 LPA Job Blueprint by Abhith B N. The complete spec is in `PROJECT_BLUEPRINT.md` at the root of this repo. The rules for how you should help me are in `CLAUDE.md` at the root.

Before we do anything:

1. Read `CLAUDE.md` end to end. Confirm you'll follow it.
2. Read `PROJECT_BLUEPRINT.md` end to end. Tell me back, in 5 bullet points, what the project is, what it's optimizing for, and what the 23 STEPs cover at a high level.
3. Tell me what's currently in this repo so I know my starting state (run `ls -la` and report back).
4. Then ask me which STEP we're starting with. Don't write any code or run any commands beyond `ls`/`cat` until I answer.

I'm a learner. I want to internalize the concepts deeply enough to defend them in a 12 LPA interview. Bias your help toward me understanding, not toward speed.

---

# Subsequent Sessions

For every session after the first, just say something like:

> "Let's do STEP 4 today. Read the STEP 4 section in `PROJECT_BLUEPRINT.md`, quote it back to me, then walk me through what you'll create and why. Don't write any code until I say go."

Or, when you want to debug:

> "STEP 17 `terraform apply` failed with `<paste error>`. Read the relevant module files, diagnose, propose a fix, and explain what went wrong. Don't apply the fix until I say go."

Or, for the deep interview-prep questions:

> "We finished STEP 5. Before we move on, quiz me: ask me three questions a 12 LPA interviewer would ask about what we built in this STEP. I'll answer; you tell me where my reasoning is weak."
