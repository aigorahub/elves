# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

> This is the Survival Guide for the `v1.7.0` Elves upgrade run. After any compaction or restart,
> read this file first, then `.elves-session.json`, then `docs/elves/learnings.md`, then
> `docs/plans/v1.7.0-ai-friendly-docs.md`, then `docs/elves/execution-log.md`. Trust these files
> over memory.

---

## Mission

Upgrade Elves to `v1.7.0` by adding a durable learnings layer, a lightweight `.ai-docs`
architecture, and docs-in-the-loop workflow rules that make the repo more AI-friendly over time.
The branch is done when the Claude skill, Codex skill, templates, durable docs, README, TODO, and
CHANGELOG all tell the same story and the PR is clean enough for the user to merge on return.

## Run Control

- **Run mode:** open-ended
- **Stop policy:** blocker-only
- **User intent:** "Do not stop. Work all the way until all the work is complete then review
  everything. Read all the PR review comments and make sure we're ready to merge. Don't merge until
  I get back."
- **Final-response policy:** disallowed until explicit user stop
- **Time split target:** implementation 35% / validation 25% / review 25% / docs and orientation 15%
- **Review settle threshold:** resolve or reply to non-actionable repeat findings after 3 cycles
- **Entropy cadence:** run a cross-batch entropy check after Batch 2 and again at the end if needed

## Session Budget

- **Started:** 2026-04-11 22:42 EDT
- **User returns:** never (open-ended until user stops)
- **Time budget:** unlimited
- **Average batch time so far:** n/a
- **Batches remaining:** 3 of 3

## Non-Negotiables

- Update both `SKILL.md` and `AGENTS.md` whenever behavior changes.
- Keep the new architecture lightweight. Durable docs, promotion flow, and disciplined upkeep are
  in scope; hydration/skeleton automation is not.
- Documentation freshness is part of done. If behavior changes, the relevant docs must change too
  or the batch is incomplete.
- You never merge. You never approve a merge. This is always a non-negotiable.
- Never run destructive git commands: `git reset --hard`, `git checkout .`, `git clean -fd`,
  `git push --force`, `git rebase` on shared branches.
- Never modify a test to make it pass. Fix the code, not the test.
- Never introduce regressions. Verify cross-file consistency, version bumps, and referenced paths
  before closing the run.

## Launch Readiness

- [x] Plan cleaned and saved to disk
- [x] Survival guide updated from the current plan
- [x] Learnings file initialized
- [x] Execution log initialized with batch breakdown and preflight notes
- [x] Branch created or confirmed
- [x] PR opened or existing PR recorded
- [x] Preflight run and critical failures reviewed
- [x] Run mode, return time, and non-negotiables recorded
- [x] Launch prompt prepared and recorded in the execution log

## Current Phase

**Status:** In progress

**Active batch:** Batch 1: Durable Memory and Agent Docs Architecture

**What was just finished:** Batch 0 completed: the run-memory docs were committed, the branch was
pushed, and PR #18 was opened for the unattended overnight run.

**Immediate next action:** Create the Batch 1 rollback tag, update the durable docs architecture,
and then align the templates around the new memory stack.

## Next Exact Batch

**Batch:** 1: Durable Memory and Agent Docs Architecture

**Scope:**

- Finalize the learnings layer and its promotion rules.
- Add `.ai-docs/manifest.md`, `.ai-docs/architecture.md`, `.ai-docs/conventions.md`, and
  `.ai-docs/gotchas.md`.
- Update the templates so the new memory stack and docs workflow are natural to use.

**Acceptance criteria:**

- [ ] Learnings is first-class in the read/update order across the repo.
- [ ] `.ai-docs/*` exists with clear, non-overlapping responsibilities.
- [ ] The templates define `execution log -> learnings -> curated durable docs` without ambiguity.

**Risk:** The docs can become redundant if the durable file responsibilities are not crisp.

**Rollback tag:** `elves/pre-batch-1`

## Acceptance Checks

- [ ] All relevant validation commands for this docs-only repo have been run and recorded.
- [ ] PR review performed, all blocking findings resolved or explicitly dismissed with reasoning.
- [ ] Execution log updated with commands run, decisions made, and commit SHA.
- [ ] Survival guide updated with current phase and next exact batch.
- [ ] Changes committed and pushed to the active branch.
- [ ] Rollback tag created before each implementation batch starts.

## Tool Configuration

> This repo is documentation-, template-, and script-focused. There is no package-managed
> lint/typecheck/build/test pipeline to lean on, so use the documented consistency checks and PR
> review loop as the primary proof.

```yaml
lint: ""
typecheck: ""
build: ""
test: ""
smoke: ""
review: github-pr-comments
notification: pr-comment
```

## Rollback and Safety Rules

1. Create a rollback tag before every implementation batch.
2. Never force-push the branch.
3. Never rebase the branch.
4. Never merge. The user merges when they return.
5. If a documentation refactor starts thrashing, stop, document the issue, and take a smaller,
   more explicit pass rather than rewriting the repo in one leap.
