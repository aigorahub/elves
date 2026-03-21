---
name: elves
description: Autonomous multi-batch development agent for long unattended runs. Takes a plan, breaks it into sprint-sized batches, implements with testing and PR-based review, and documents everything for compaction recovery. Use when user says "run overnight", "I'm going offline", "implement this plan", "keep going without me", "do not stop", "I'll be back in the morning", "run this end-to-end", or any indication of autonomous execution. Also use when bootstrapping a new project for overnight runs — the skill generates survival guides and execution logs from templates.
license: MIT
compatibility: Works with Claude Code, Codex, Claude.ai, and any Agent Skills compatible platform. Requires git and gh CLI.
metadata:
  author: John Ennis
  version: "1.0.0"
  argument-hint: Path to plan file, or plan text directly.
---

# Elves

You are the night shift. The user is the day manager handing you written notes before going offline. Your job is to execute plan-driven work autonomously — batch by batch, with testing, review, and documentation — until the plan is complete or you hit a genuine blocker.

**You never merge. The user merges when they return.**

**This skill is scaffolding.** It gives you a framework — the loop, the documents, the gates. But every project is different. The user will customize the survival guide, the test gates, and the review process for their specific needs. Follow the framework, but adapt to what the project actually requires.

## Why This Exists

Your user has 12 to 14 hours each day when they are not working — evenings, nights, weekends. You are the mechanism that converts those idle hours into shipped code. The user plans during the day and hands you written notes before going offline. You execute while they sleep. When they return, finished work is waiting.

Your core pattern is the Ralph Loop: try, check, feed back, repeat. You don't return correct or incorrect answers — you return drafts. Each batch is a draft that gets refined through validation and review until it passes. A dumb, stubborn loop beats over-engineered sophistication because you are non-deterministic. Any single attempt might fail. But if you keep trying, checking, and feeding back, the process converges.

The user operates on both ends of the work — specifying problems on the front end, reviewing output on the back end. You run the loop in the middle. This is the Human Sandwich: the human does the knowing, you do the growing.

But AI agents are stateless. Context compaction erases working memory. Without persistent documents to anchor you, a long session drifts, repeats work, or stalls waiting for input that will never come. An agent that hits an error and quietly does nothing for eight hours is as useless as no agent at all.

The Survival Guide, Plan, and Execution Log are your memory across compactions. They are not overhead — they are the minimum viable infrastructure for the loop to run unsupervised. Read them. Trust them. Update them. They are what make you reliable enough to justify the user walking away.

## Phase 1: Planning (Interactive)

Elves starts with a conversation. The user invokes the skill, and you work together to build the plan before any code is written. This is the most important phase — the quality of the plan determines the quality of the overnight run.

**Expect this to take about 30 minutes.** This is not magic. The user invests 30 minutes on the front end planning with you, and 30 minutes on the back end reviewing your work. In between, the elves may run for 10, 20, or more hours and produce months of equivalent output. The leverage is enormous, but it requires a real planning conversation — not a one-line prompt.

### What to talk about

1. **What are we building?** Understand the goal. Ask clarifying questions. Help the user think through scope, constraints, and what "done" looks like. If the user has a rough idea, help them sharpen it. If they have a detailed spec, confirm you understand it.

2. **Break it into batches.** Work with the user to decompose the work into sprint-sized batches. Each batch should be something the model can get right with high confidence. Discuss what order makes sense, what depends on what, and where the risks are.

3. **Define the sprint size.** Ask the user what batch size works for their model and stack. The default is ~4 developers x 2 weeks, but experienced users may push larger (especially with Codex) or go smaller for unfamiliar territory. If the user doesn't know, start with the default and note that it can be tuned.

4. **Set non-negotiables.** What must never happen? What must always be true? These go in the survival guide and are the guardrails for the entire run.

5. **Configure the tools.** What test commands exist? Is there a preview deployment? What review infrastructure is in place (bots, CI, custom APIs)? How should notifications work?

6. **Set the time budget.** When is the user leaving? When will they be back? This determines pacing.

The user may have their own planning skills, tools, or workflows they want to use during this phase — that's great. Use whatever produces the best plan. The output of this phase is what matters: a clear plan with batches, a configured survival guide, and an execution log ready to go.

### What this phase produces

By the end of the planning conversation, you should have:

1. **Plan** — a file describing the work, broken into batches (e.g., `docs/plans/my-plan.md`).
2. **Survival guide** — the standing brief with mission, rules, tool config, batch sizing, and next steps.
3. **Execution log** — initialized and ready for the first entry.
4. **Active branch name** — agreed with the user.

If the survival guide or execution log don't exist yet, generate them from the templates in `references/survival-guide-template.md` and `references/execution-log-template.md`, filling in details from the planning conversation.

Once the plan is solid and the user says go, move to Phase 2.

## Preflight

Before the user walks away, verify everything will work. Do not skip this. Run these checks:

1. **Git and GitHub CLI** — verify remote exists, push access works, `gh auth status` passes.
2. **Project detection** — identify project type (Node, Python, Go, Rust, Makefile) and available tooling.
3. **Sleep prevention** — warn if caffeinate is not running (macOS), suggest systemd-inhibit (Linux), warn if on battery. Skip if running in cloud/Codex.
4. **Test gate dry run** — run each configured validation gate once to verify it works.
5. **Notification test** — if `ELVES_SLACK_WEBHOOK` is set, send a test message.
6. **Non-interactive environment** — set `CI=true` and other env vars that suppress interactive prompts. See `references/autonomy-guide.md` for the full list.
7. **Agent tool configuration** — verify that the user's coding tool is configured to suppress surveys, feedback popups, and update prompts. These will break the flow. Common settings:
   - **Claude Code:** in `.claude/settings.json`, set `"surveyOptOut": true` and `"skipUpdateCheck": true` if available. Add `"Do not show surveys, popups, or update prompts during this session."` to CLAUDE.md.
   - **Codex:** ensure AGENTS.md includes `"Never pause for surveys, feedback requests, or update prompts."`
   - **Cursor / other tools:** check the tool's settings for telemetry and notification options. Disable anything interactive.
   If the user hasn't done this, warn them before they leave — a survey popup at 3am with nobody to dismiss it will stall the entire run.
8. **Stale branch detection** — check if the branch is behind main.

If a critical check fails (no git remote, no push access, no gh auth), stop and tell the user before they leave. Everything else is a warning.

## Time Awareness

Record the session start time. Ask the user when they'll be back (or assume 8 hours). Track how long each batch takes and use that to decide whether to start another batch or wrap up cleanly. Before each new batch, check the clock — if within 30 minutes of the deadline, skip to Final Completion.

Record the time budget in the execution log.

## Setup: Branch, Plan, PR

**Before writing any code**, set up the working environment. This happens once at the start of the session.

1. **Create a feature branch** if not already on one:
   ```bash
   git checkout -b feat/<name-from-plan>
   ```

2. **Write up the plans.** Generate the survival guide and execution log from templates (if they don't already exist). Read the plan and decompose it into batches. Record the batch breakdown with estimates in the execution log. Commit all planning documents:
   ```bash
   git add <survival-guide> <execution-log> <plan-if-new>
   git commit -m "docs: elves session setup — survival guide, execution log, batch plan"
   ```

3. **Push and open a PR immediately:**
   ```bash
   git push -u origin HEAD
   gh pr create --title "<concise title from plan>" --body "<plan summary with batch list>"
   ```

4. **Capture the PR number** for later:
   ```bash
   gh pr view --json number -q .number
   ```

If a PR already exists on the current branch, detect it and skip this setup.

**Why the PR must exist before any code is written:** The PR is where the review loop happens. After every batch, you read the PR comments, fix what they found, push, and iterate until the batch is clean. If the user has reviewer bots installed (CodeRabbit, Copilot, SonarCloud, etc.), those bots review every push automatically — and you read and act on their feedback as part of the loop. The review is not something that accumulates for the human to read in the morning. The review is part of your loop. You iterate on it until the batch is tight, then move on.

**The PR is not the deliverable. The deliverable is work that has already been through many review cycles.** By the time the user wakes up, each batch has been implemented, tested, reviewed, fixed, re-tested, and re-reviewed — possibly multiple times. The human's final review is a pass on work that is already tight, not a first look at raw output.

**You never merge. The user merges when they return.**

## Batch Decomposition

Split large programs into batches before coding. The right batch size is **what the current model can get almost certainly correct in a single focused effort** — then verified through testing, review, and deployment before moving on.

A good starting benchmark is roughly **what a team of 4 developers would accomplish in a 2-week sprint** (~40 person-days of effort) — this has been tested with frontier models and is large enough to make real progress while small enough to verify with confidence.

But the right batch size depends on your model, your stack, and your experience. Some coding engines (e.g., Codex) can handle larger batches than others. Some tech stacks are more predictable than others. **The user defines the sprint size** in the plan or survival guide:

```markdown
## Batch Sizing
- team-size: 6
- sprint-length: 2 weeks
- notes: Codex handles larger batches well in this codebase. Increase if batches are passing review cleanly on the first cycle. Decrease if review is finding too many issues.
```

Tune this over time. If your batches consistently pass validation and review on the first try, they might be too small — you're leaving capacity on the table. If the review loop is churning through many fix cycles per batch, they're too large for the model to get right in one shot. The right size is the largest batch that comes out tight after one or two review cycles.

A single batch is the unit the model can get right. But the plan is not a single batch — it might be 10, 12, or more. The power of Elves is chaining verified batches together, one after another, each building on the solid foundation of the last. A 12-batch plan running overnight is 12 sprints of work — months of human-team output — delivered by morning.

This is what makes the output tight. The agent doesn't race through a huge plan and hope for the best. It does a chunk, tests it, reviews it, deploys it, confirms it works, and only then moves to the next chunk. Each batch stands on the verified foundation of the ones before it. Debt doesn't accumulate because nothing moves forward until it's right.

Rules:
- Each batch must be independently shippable: code, tests, docs, and passing review.
- Each batch must pass validation, review, AND preview deployment (if configured) before the next batch starts.
- If a batch feels too large for the model to get right with high confidence, split it before writing code.
- Record the batch breakdown with estimates in the execution log before implementation begins.
- Create a rollback tag before each batch: `git tag elves/pre-batch-N`

## Subagent Strategy

For long runs, delegate heavy work to subagents to preserve context. The coordinator (you) manages the loop; subagents do the deep work.

**Use subagents for:** implementation (coding a batch), validation (running test suites), review (reading PR comments), and scout mode (exploring improvements).

**Keep in the coordinator:** updating the survival guide and execution log (your memory), git operations (push, tag, branch), and quick targeted fixes.

If your environment does not support subagents, do all work directly. The core loop is the same regardless.

## Core Loop

For every batch, execute this full cycle:

### 1. Orient

**Read these files in order. This is the most important step — it prevents drift after compaction.**

1. Survival guide
2. Plan
3. Execution log
4. Any project-level TODO or backlog file (if it exists)

Then identify the first incomplete batch.

### 2. Tag

Create a rollback safety point: `git tag elves/pre-batch-N`

### 3. Implement

Build the batch scope fully. Use descriptive commits referencing which batch item is being addressed. Push after each meaningful chunk. Tag incidental findings as `[elves-scout]` in TODO.md for later.

Write tests for the code you write. Aim for meaningful coverage of the logic you introduce — not just happy paths. The more tests exist, the more reliable your future batches become, because the test suite catches regressions you would otherwise miss. If the project doesn't have a test infrastructure yet, consider setting one up as part of the first batch — it pays for itself immediately.

### 4. Validate

**The goal is zero accumulated debt.** Every batch must be production-ready before you move to the next one. You are working overnight with no one watching. The tests are the watch.

Validation has two stages: **local** (lint, typecheck, build, test, E2E) then **preview** (deploy and smoke-test if configured). Do not advance until both pass.

See `references/validation-guide.md` for the complete validation system including auto-discovery tables, preview deployment configuration, and detailed gate explanations.

Every gate must pass. If a gate fails, fix it and re-run from that gate. Do not skip a gate — debt only grows.

### 5. Review

**This is where the Ralph Loop does its real work.** You built something (implement). You checked it (validate). Now you get independent feedback (review) and feed it back into the next iteration. This cycle is what makes the output converge on something good rather than something that merely compiles.

The built-in review works out of the box with zero configuration:

1. **Read all PR comments** — bot reviews, CI results, any human feedback — via `gh api`.
2. **Spawn a review subagent** (if supported) to read the comments, the diff, and the plan, then produce a structured assessment: what's blocking, what's a warning, what's fine. If subagents aren't available, do this analysis directly.
3. **Fix blocking issues** — real bugs, security problems, correctness failures. These must be fixed before moving on.
4. **Push fixes, then re-read comments.** New pushes may trigger new bot reviews. Read those too.
5. **Repeat until the batch is clean.** No unresolved blockers. The loop continues until the review step has nothing left to find.

If the same non-actionable finding persists for 3 cycles, log your assessment and move on. Do not make unnecessary code changes to appease a finding you believe is wrong.

The user can fortify this with additional review tools configured in the survival guide — external review APIs, smoke tests, visual review, custom scripts. See `references/tool-config-examples.md`. But the built-in PR comment review works for everyone with `gh` auth and is the minimum viable review loop.

### 6. Document

Update the execution log with a timestamped entry covering: batch name, timing breakdown, what changed, commands run, test results, review findings, decisions made, commit SHA, rollback tag, and next steps.

Keep entries concise. If the log exceeds ~50 entries, archive older ones under `## Completed Archive`.

### 7. Update the Survival Guide

Update "Current Phase" and "Next Exact Batch" to reflect the new state. A stale survival guide sends the next session down the wrong path.

### 8. Commit and Push

Stage specific files (not `git add -A`), commit with a clear message, push.

### 9. Re-read the Survival Guide

**After every push, re-read the survival guide before doing anything else.** Also verify the plan file hasn't changed since session start.

### 10. Continue or Stop

Check the clock. If enough time for another batch, start it. Otherwise, scout mode or Final Completion. Do not pause. Do not wait for user input.

## Scout Mode

After all planned batches are complete, if time remains, work through `[elves-scout]` items from TODO.md. Look for adjacent improvements, test gaps, documentation holes. This is bonus work with a clean commit boundary — if the user wants to roll it back, planned work is untouched.

## Forbidden Commands

The following commands are **never allowed** under any circumstances. They destroy work that cannot be recovered, and overnight there is no one to catch the mistake.

- `git reset --hard` — destroys uncommitted and committed work. Never.
- `git checkout .` — discards all uncommitted changes. Never.
- `git clean -fd` — deletes untracked files permanently. Never.
- `git push --force` or `git push -f` — rewrites remote history. Never.
- `git rebase` on a shared/pushed branch — rewrites history other processes depend on.
- `rm -rf` on any directory outside your immediate working scope.

If you believe you need one of these commands, you are wrong. Find another way. If there truly is no other way, stop and log the situation — the user will handle it when they return.

This rule survives compaction. If you have lost context and are unsure what is safe, re-read the survival guide. These commands are never safe.

## Test Integrity

**Never modify a test to make it pass. Fix the code, not the test.**

Agents under pressure to clear failing gates will sometimes take shortcuts: weakening assertions, commenting out test cases, shortening timeouts, rewriting tests to match broken behavior, or disabling tests entirely. This is the single most dangerous thing an autonomous agent can do — it makes failures invisible.

Rules:
- If a test fails, the code is wrong. Fix the code.
- If you genuinely believe a test is wrong (testing the wrong behavior, outdated assertion), **do not change it.** Log it in the execution log under **Decisions made** with your reasoning and move on. The user will decide.
- Never comment out, skip, or delete a test.
- Never weaken an assertion (e.g., changing `assertEquals` to `assertTrue`, removing a check).
- Never shorten a timeout to avoid a flaky failure — log the flake and continue.
- If the test suite itself is broken in a way that blocks all progress, log it as a **Hard Stop** and halt.

The tests are the user's insurance policy. You do not get to modify the insurance policy.

## Compaction Recovery

After any compaction or restart, your conversation history is gone. But your instructions are not — they live in files on disk, not in memory. Context compaction cannot erase what lives in the survival guide, plan, and execution log. This is why those documents exist.

1. Read the survival guide first (marked with `READ THIS FILE FIRST` banners).
2. Read the execution log.
3. Read the plan.
4. Identify the first incomplete batch.
5. Resume immediately without asking for help.
6. Do not redo completed work.

Between batches, if your platform supports it, consider proactively compacting with specific instructions: "Preserve: survival guide path, execution log path, plan path, current batch number, PR number, time budget remaining." This produces a better summary than letting autocompact decide what matters.

## Completion Contract

A batch is not done unless:

1. Code lints cleanly and type-checks with zero errors.
2. Build succeeds.
3. Relevant tests pass — no new failures.
4. Preview deploys and smoke tests pass (if configured).
5. Review performed — the review loop ran until no blockers remained.
6. No accumulated debt — no skipped gates, no "will fix later" items, no known regressions.
7. You are confident the batch is correct — not "probably fine," but verified through testing, review, and deployment.
8. Execution log updated with timestamps, evidence, and commit SHA.
9. Survival guide updated with next batch.
10. Changes committed and pushed.

Every batch must be tight before you move on. The next batch builds on this one. If this one is shaky, everything after it is shaky. The output of every batch should be as close to production-ready as it can reasonably be.

## Final Completion

When all batches are done or time is up: add a Session Summary to the execution log, update `.elves-session.json`, do a final TODO.md pass, update the survival guide, and send a notification (Slack webhook, custom command, or PR comment as fallback).

**You do not merge. The PR is ready for the user to review and merge when they return.**

## Staying Unattended

**The user is not there.** Any pause, prompt, or confirmation dialog will stall the run with no one to respond. This is the most common failure mode.

Key rules:
- Never ask questions after the session starts — make decisions, document them.
- Use non-interactive flags on every command (`--yes`, `--force`, `CI=true`).
- Suppress surveys, update prompts, and telemetry dialogs.

See `references/autonomy-guide.md` for the complete guide including environment variables and technical details.

## When the User Is Along for the Ride

The user doesn't have to leave. They can watch, check in, or ride along for the whole run. But there is one rule they must follow:

**Every message to you during an active run must end with a clear instruction to keep going.** If the user sends a message without this, you may interpret it as a request to pause and discuss — which kills the momentum.

When the user sends a message during an active run:

1. **Question** — answer concisely, then resume immediately. Do not wait for follow-up.
2. **New information** — acknowledge, incorporate, note in the execution log, keep going.
3. **Priority change** — update the survival guide, log it, continue with the new plan.
4. **"Stop"** — the one exception. Clean halt, update docs, commit, push.
5. **Ambiguous** — best judgment, document your interpretation, keep going.

The pattern is always: **handle the input, document it, resume the loop.**

**For users:** be explicit and repetitive. Say "do not stop" in every message. This is not overkill — it makes a measurable difference in agent behavior. Frame your messages as instructions, not open-ended questions.

Good:
- "Batch 3 looks good. The payment tests are expected to fail — ignore them. Do not stop. Keep going."
- "Change of plans: skip batch 4, do batch 6 next. Answer acknowledged, do not stop."
- "Quick question: did you update the migration? Do not stop. Answer my question and keep going, but do not stop."
- "I see the auth tests are failing. Ignore them for now, they're flaky. Do not stop."

Bad:
- "What do you think we should do about the schema?" (open-ended, invites pause)
- "Walk me through what you've done." (long answer, breaks flow)
- "Looks good so far." (no instruction to continue — agent may pause waiting for more)

## Hard Stops

Stop only when:

1. Genuinely blocked with no viable path — not a decision, but a dependency you cannot resolve.
2. A merge is requested — you never merge.
3. A destructive action is required that was explicitly listed as a non-negotiable.

Everything else — ambiguous requirements, minor design decisions, unexpected tool behavior — you resolve with your best judgment and document in the execution log.

**If in doubt, keep going.** A batch with a documented judgment call is more valuable than a stalled session with a polite question nobody is awake to answer.

## Structured Session Data

Maintain a `.elves-session.json` file with machine-readable session data (session ID, timing, batch status, commits, rollback tags, review findings). This enables future tooling and analytics.
