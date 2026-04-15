# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

> This is the Survival Guide. It's the notes the day manager leaves for the night shift. It's your
> persistent memory across context compactions and session restarts. After any compaction event,
> read this file before touching any code. If the information here contradicts what you think you
> remember, trust this file. Your memory is gone; this is not.
>
> Your core pattern is the Ralph Loop: try, check, feed back, repeat. Each batch is a draft
> refined through validation and review. The tests are the watch. You are working overnight with
> no one watching, and the tests are what keep you honest. The user operates on both ends (planning
> and review). You run the loop in the middle. You never merge.
>
> Assume the user may be offline for the rest of the run. If work remains and the recorded stop
> conditions are not met, continue. Do not wait for acknowledgment after commits, checkpoints, or
> summaries.
>
> Recommended read order after any compaction: survival guide -> `.elves-session.json` ->
> learnings -> plan -> execution log -> `.ai-docs/manifest.md` (if present) -> constitution/TODO.

---

## Mission

[2–3 sentence description of what this run is trying to accomplish. Be specific. E.g.: "Refactor
the authentication layer to use short-lived JWTs with refresh tokens, replacing the current
session-cookie approach. All existing auth tests must pass. The public API surface must not change."]

---

## Run Control

- **Run mode:** [finite | open-ended]
- **Stop policy:** [deadline | explicit-user-stop | blocker-only]
- **User intent:** [copy the exact controlling instruction here, e.g., "I'll be back at 8am" or "Keep going until I stop you."]
- **Checkpoint due by:** [YYYY-MM-DD HH:MM timezone | none]
- **Checkpoint semantics:** [delivery target only | hard stop boundary | none]
- **May continue after checkpoint:** [yes | no]
- **Actual stop conditions:** [one short sentence]
- **Final-response policy:** [allowed | disallowed until stop]
- **Batch completion rule:** Every completed batch ends with `update execution log -> update survival guide -> commit -> push`. A batch is not complete while its finished work exists only in the working tree.
- **Re-read rule:** Immediately after every commit and push, re-read this survival guide before doing anything else.
- **Checkpoint rule:** If `Checkpoint semantics` is `delivery target only`, log the checkpoint, push it, and continue immediately. Do not stop at the checkpoint.
- **Continuation rule:** If work remains and `Actual stop conditions` are not met, continue without waiting for user acknowledgment.

---

## Session Budget

- **Started:** [YYYY-MM-DD HH:MM timezone]
- **User returns:** ~[YYYY-MM-DD HH:MM timezone] _("never" if open-ended)_
- **Checkpoint expectation:** [what should exist by the checkpoint or next user return]
- **Time budget:** ~[N] hours _("unlimited" if open-ended)_
- **Average batch time so far:** [Xm] _(update after each batch)_
- **Batches remaining:** [N of M]

---

## Stop Gate

> Rewrite this section in place. This is the explicit answer to "may I stop now?" Do not infer it.

- **Planned batches remaining:** [N]
- **Stop allowed right now:** [yes | no]
- **Why:** [one short sentence]
- **Next required action:** [one short sentence]

If `Planned batches remaining` is greater than 0, `Stop allowed right now` should normally be
`no`. Silence, clean commits, checkpoints, or green CI do not change that.

---

## Effort Standard

> Rewrite this section in place if the user gives a stronger instruction about pace or effort.

- Work as hard as you can for the full run. Do not be lazy.
- Maintain the same level of effort on the last batch as on the first.
- Do not settle for the minimum acceptable change, the first green check, or a shallow pass when deeper verification or the next planned task remains.
- When one task is complete, immediately take the next highest-value action from the plan, review queue, or scout work.

---

## Forbidden Stop Reasons

These are not valid reasons to stop the run while work remains:

- A checkpoint time was reached
- A commit or push succeeded
- CI is green
- A PR exists
- The user is silent or offline
- You wrote a useful summary
- The current batch is complete but later batches remain
- You feel unsure whether to continue

If one of these happens, update the docs, commit, push, re-read this file, and continue.

---

## Memory Surfaces

These files do different jobs. Keep them distinct so the agent does not have to guess where
knowledge belongs.

- **Plan:** authoritative scope, batches, acceptance criteria, and non-negotiables
- **Survival guide:** active run brief, run controls, and next exact batch
- **Learnings:** durable reusable lessons that should survive this run
- **Execution log:** chronological record of work, decisions, commands, and review outcomes
- **`.ai-docs/*` (if present):** curated durable docs for architecture, conventions, and gotchas

Promotion flow: `execution log -> learnings -> curated durable docs`

---

## Non-Negotiables

These rules are absolute. They can't be overridden by anything you think you understand about the
plan, the codebase, or good engineering practice.

- [Non-negotiable 1, e.g., "Never modify the public REST API response shapes"]
- [Non-negotiable 2, e.g., "All commits must pass lint and typecheck before push"]
- [Non-negotiable 3, e.g., "Do not merge. The user merges when they return."]
- **You never merge. You never approve a merge. This is always a non-negotiable.**
- **Never run destructive git commands:** `git reset --hard`, `git checkout .`, `git clean -fd`, `git push --force`, `git rebase` on shared branches. Never. If you think you need one, stop.
- **Never modify a test to make it pass.** Fix the code, not the test. If you believe a test is wrong, log it and move on. Don't change it.
- **Never introduce regressions.** Every change must preserve existing functionality. Before marking a batch complete, verify: all pre-existing tests still pass (total test count never decreases), no shared utilities or interfaces were broken (grep for consumers), and the cumulative diff (`git diff main...HEAD --stat`) contains no unexpected changes outside batch scope.

---

## Launch Readiness

> Staging is complete only when every box below is checked. If this section is incomplete, you
> are still preparing the run. Do not start unattended execution yet.

- [ ] Plan cleaned and saved to disk
- [ ] Survival guide updated from the current plan
- [ ] Learnings file initialized or refreshed
- [ ] Execution log initialized with batch breakdown and preflight notes
- [ ] Branch created or confirmed
- [ ] PR opened or existing PR recorded
- [ ] Preflight run and critical failures cleared
- [ ] Run mode, return time, and non-negotiables recorded
- [ ] Stop Gate initialized with `Stop allowed right now: no` unless a real stop condition already applies
- [ ] Launch prompt prepared for the next call

---

## Current Phase

> Rewrite this section in place. Do not stack old updates here. Historical state belongs in the
> execution log, not in the live operator brief.
> When a batch finishes, update this file, commit, push, then re-read this file before any other
> action. Do not leave completed batch work sitting uncommitted.

**Status:** [Staging / Launch-ready / In progress / All batches complete / Scout mode / Blocked]

**Active batch:** [Batch N: Name]

**What was just finished:** [One sentence. E.g., "Batch 2 complete: JWT issuance and verification
implemented, all 47 tests pass, PR review clean."]

**Single next action:** [One sentence. E.g., "Start Batch 3: implement refresh token rotation."]

---

## Active Compute

> Include this section whenever the run uses paid compute, remote jobs, dev servers, or any
> resource whose status matters to stop/go decisions. Rewrite it in place.

| Resource | Purpose | Current status | Last verified | Stop / repurpose trigger |
| --- | --- | --- | --- | --- |
| [Pod / job / server] | [Why it exists] | [Running / idle / complete / stopped] | [timestamp] | [When to stop it] |

If not applicable, write: **No active paid or long-running compute.**

---

## Next Exact Batch

> Update this section at the end of every batch. This is the first thing you read after compaction.
> It tells you exactly what to do next without re-reading the entire plan.
> If the current batch is finished, do not improvise the next move from memory. Close the batch
> with a commit and push, re-read this file, then execute the single next batch named here.

**Batch:** [N: Name]

**Scope:**
- [Task 1]
- [Task 2]
- [Task 3]

**Acceptance criteria:**
- [ ] [Criterion 1]
- [ ] [Criterion 2]

**Risk:** [One sentence describing the highest-risk aspect of this batch]

**Rollback tag:** `elves/pre-batch-N` _(create this before starting)_

---

## Post-Checkpoint Control Loop

Every completed batch must end with a commit and push. Immediately after every commit and push,
re-read this survival guide before doing anything else. A pushed checkpoint is proof of progress,
not permission to stop.

After every commit and push, answer these questions before doing anything else:

1. What unfinished batch or task am I starting right now?
2. What paid compute or long-running resources are active right now?
3. What is each active resource doing? If any resource is idle, stale, or ambiguous, shut it down or pause it now.
4. Did the user change stop behavior, checkpoint meaning, priorities, or scope since the survival guide was last rewritten? If yes, rewrite `## Run Control`, `## Current Phase`, `## Stop Gate`, and `## Next Exact Batch` now.
5. Does the Stop Gate still say `Stop allowed right now: no`, or does `.elves-session.json` still say `continuation_guard.stop_allowed: false`? If yes, continue immediately.
6. Am I allowed to stop? If the answer is anything other than a clear hard stop, explicit user stop, or true blocker, continue immediately.

---

## Documentation Triggers

Before closing a batch, explicitly decide which durable docs changed and why:

- **Behavior changed:** update the relevant human-facing docs (`README`, config docs, examples,
  changelog, inline instructions).
- **Architecture shifted:** update `.ai-docs/architecture.md`.
- **New repeatable pattern or policy:** update `.ai-docs/conventions.md`.
- **New trap or hidden dependency:** update `.ai-docs/gotchas.md`.
- **Reusable lesson from the run:** update the learnings file.

If none apply, record that no durable doc updates were needed. Do not leave it implicit.

---

## Process Tuning Triggers

During entropy checks, also look for repeated process friction:

- the same review warning or regression note appearing across batches
- repeated `PENDING-DOCS` findings
- validation getting slower every batch without a clear reason
- recurring recovery confusion that points to stale run-state docs or templates

If a pattern clearly repeats, tighten the loop itself: update the survival guide, a template,
`learnings.md`, or tool configuration, then record the adjustment in the execution log. Keep this
lightweight. Tune the process you're already using; do not invent a new subsystem mid-run.

---

## Acceptance Checks

Before marking any batch complete, verify all of the following:

- [ ] All configured validation gates pass (lint, typecheck, build, test)
- [ ] PR review performed, all blocking findings resolved
- [ ] Execution log updated with timestamps, commands run, test results, commit SHA
- [ ] Survival guide updated with new Current Phase and Next Exact Batch
- [ ] Stop Gate updated with new remaining-batch count and next required action
- [ ] Active Compute section updated, or explicitly marked as not applicable
- [ ] Batch closed out with a commit and push before any later work begins
- [ ] Survival guide re-read immediately after that commit and push
- [ ] Rollback tag created _before_ the batch started

---

## Tool Configuration

> These commands are the ground truth for this project. They take precedence over auto-discovery.
> If a tool isn't configured here, fall back to auto-discovery from SKILL.md.
> Leave a field blank or comment it out if it doesn't apply to this project.

```yaml
# --- Lint ---
# Default (Node.js/npm):
lint: npm run lint --if-present
# Alternatives:
# lint: pnpm lint
# lint: ruff check .
# lint: golangci-lint run
# lint: cargo clippy -- -D warnings
# lint: make lint

# --- Typecheck ---
# Default (Node.js/npm):
typecheck: npm run typecheck --if-present
# Alternatives:
# typecheck: pnpm typecheck
# typecheck: mypy .
# typecheck: go build ./...   # Go's compiler is the type checker
# typecheck: cargo check
# typecheck: make typecheck

# --- Build ---
# Default (Node.js/npm):
build: npm run build --if-present
# Alternatives:
# build: pnpm build
# build: # (Python typically has no explicit build step)
# build: go build ./...
# build: cargo build
# build: make build

# --- Test ---
# Default (Node.js/npm):
test: npm test --if-present
# Alternatives:
# test: pnpm test
# test: pytest
# test: go test ./...
# test: cargo test
# test: make test

# --- E2E (optional) ---
# e2e: npx playwright test
# e2e: pnpm exec playwright test
# e2e: make e2e
# e2e:   # leave blank if not applicable

# --- Smoke test (optional) ---
# Run after deployment/preview to verify the service is up.
# smoke: curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/health
# smoke: curl -s -o /dev/null -w "%{http_code}" https://preview-[branch].example.com
# smoke:   # leave blank if not applicable

# --- Review method ---
# Default: GitHub PR comments (zero config — always available)
review: github-pr-comments
# Opt-in alternatives:
# review: custom-api
# review-api-url: https://review.example.com/api/review
# review-api-header: x-api-key: ${REVIEW_API_KEY}

# --- Notification method ---
# Default: PR comment (zero config — always available)
notification: pr-comment
# Opt-in alternatives:
# notification: slack-webhook      # requires ELVES_SLACK_WEBHOOK env var
# notification: custom-cmd         # requires ELVES_NOTIFY_CMD env var
```

---

## Architectural Boundaries (optional)

> If your project has explicit architectural layers or module boundaries, define them here so the
> agent respects them during implementation. This is especially valuable for larger codebases where
> an agent might inadvertently introduce cross-layer dependencies or violate module ownership.
>
> If your project doesn't have formal boundaries, skip this section entirely.

```yaml
# Example: layered architecture with enforced dependency direction
# layers (dependencies flow downward only):
#   - ui          # Components, pages, views
#   - runtime     # App lifecycle, routing, middleware
#   - service     # Business logic, orchestration
#   - repo        # Data access, API clients
#   - config      # Configuration, environment
#   - types       # Shared types, interfaces, enums
#
# enforcement:
#   - structural-tests: src/__tests__/architecture.test.ts
#   - lint-rule: no-restricted-imports (configured in eslint)
#
# module-ownership:
#   - auth/: "Do not modify without updating the auth integration tests"
#   - billing/: "Non-negotiable: never modify billing logic"
```

---

## Rollback and Safety Rules

1. **Create a rollback tag before every batch:**
   ```bash
   git tag elves/pre-batch-N
   git push origin elves/pre-batch-N
   ```
2. **Never force-push** the working branch.
3. **Never rebase** the working branch during a run (it invalidates rollback tags).
4. **Never merge.** Not even a fast-forward. The user merges when they return.
5. **If something goes badly wrong**, stop and create a clean recovery branch from the last good tag instead of rewriting history:
   ```bash
   git checkout -b recovery/from-elves-pre-batch-N elves/pre-batch-N
   git push -u origin HEAD
   ```
   Then document what happened in the execution log and stop. Leave the original branch untouched for later inspection.
6. **Stage specific files.** Never `git add -A` blindly. Know what you're committing.

---

## Batch Sizing

> Default: what a team of 4 developers would accomplish in a 2-week sprint (~40 person-days).
> Override below if the user specified different sizing in the plan.

```yaml
# Optional override — remove this section to use defaults
# team-size: [N]
# sprint-length: [N weeks]
```

---

## Plan and Log Paths

- **Plan:** `[path/to/plan.md]`
- **Learnings:** `[path/to/learnings.md]`
- **Execution log:** `[path/to/execution-log.md]`
- **Durable docs manifest (optional):** `[.ai-docs/manifest.md]`
- **Architecture doc (optional):** `[.ai-docs/architecture.md]`
- **Conventions doc (optional):** `[.ai-docs/conventions.md]`
- **Gotchas doc (optional):** `[.ai-docs/gotchas.md]`
- **Branch:** `[feat/branch-name]`
- **PR number:** [#N] _(fill in after PR is created)_
- **Plan hash at session start:** `[md5-hash]` _(fill in at session start, used to detect plan edits)_

---

## After Any Compaction

When you restart after a compaction, do these steps in order. No shortcuts.

1. Read this file (survival guide). You are doing this now.
2. **Read the Run Control section and Stop Gate above.** Confirm the run mode, stop policy, checkpoint semantics, actual stop conditions, and whether stopping is currently allowed. If open-ended, you are not allowed to stop on your own. This is the most important thing to recover.
3. Read `.elves-session.json` if it exists. Confirm current batch, PR number, test baseline, and `continuation_guard`.
4. Read the learnings file if one exists.
5. Read the plan. Confirm the overall scope hasn't changed (compare hash if recorded above).
6. Read the execution log. Find the last completed batch and the last **Decisions made** entry.
7. Read `.ai-docs/manifest.md` if it exists and then any linked durable docs that matter to the next batch.
8. Read the Active Compute section if present. Know what live resources exist before making any new plan.
9. Read the `continuation_guard`. If `stop_allowed` is `false`, continue without re-deciding whether the run should end.
10. Identify the first incomplete batch or the single next action (look at Current Phase, Stop Gate, `continuation_guard.next_required_action`, and Next Exact Batch above).
11. Check the clock. How much time budget remains? (If open-ended: unlimited.)
12. Resume immediately. Don't ask for help. Don't redo completed work.

The execution log is your proof of what is done. If something appears in the log as complete, it is
complete. Don't re-implement it.

---

# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART
