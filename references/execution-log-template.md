# Execution Log

> This is the running record of everything Elves has done during this session. It is written once
> and never edited. New entries are always added at the **top** (reverse chronological order,
> newest first). Don't delete or modify past entries.
>
> After a context compaction, this file tells you what is already done so you don't repeat work.
> The survival guide tells you what to do next. The learnings file and `.ai-docs/*` hold the
> durable knowledge that should survive beyond a single run. These files live on disk. Context
> compaction can't erase them. That's the entire point.
>
> Each entry records one iteration of the Ralph Loop: what you tried, what the tests said, what
> the review found, what you fixed, and what comes next. The user will read this log when they
> return to understand exactly what happened while they were away.
>
> Keep raw chronology here. Reusable lessons should be promoted to the learnings file. Stable repo
> truths should eventually be curated into `.ai-docs/architecture.md`, `.ai-docs/conventions.md`,
> or `.ai-docs/gotchas.md`.
>
> If this file exceeds ~50 entries, move older completed entries under a `## Completed Archive`
> heading at the bottom.

---

## Run Digest

> Refresh this small summary after every batch so a fresh session can get bearings quickly without
> rereading the full log.

- **Last updated:** [YYYY-MM-DD HH:MM timezone]
- **Current phase:** [Staging / In progress / Scout mode / Blocked / Complete]
- **Active batch:** [Batch N: Name]
- **Last completed batch:** [Batch N: Name / "none yet"]
- **Next exact batch:** [Batch N: Name]
- **Active PR:** [#N / "not created yet"]
- **Docs promoted this run:** [list / "none yet"]

---

<!-- ================================================================
     SESSION SUMMARY: added at the very end of the session (top of log)
     Copy this block, fill it in, and paste it above the first batch entry.
     ================================================================ -->

## Session Summary: [YYYY-MM-DD]

**Duration:** [X]h [X]m (started [HH:MM], ended [HH:MM timezone])
**Batches completed:** [N] of [M] planned
**Scout items completed:** [N] | **Scout items backlogged:** [N]

**Time breakdown:**
- Implementing: [total across all batches]
- Validating (lint/typecheck/build/test): [total]
- Review (PR comments + remediation): [total]
- Documentation & orientation: [total]

**Status:** [All planned work complete / Stopped at batch N (ran out of time) / Blocked on X]

---

<!-- ================================================================
     SESSION SETUP / STAGING ENTRY: copy this block once the run is
     staged and launch-ready. This is the handoff between preparation
     and unattended execution.
     ================================================================ -->

## Session Setup: [YYYY-MM-DD HH:MM timezone]

**Phase:** [Staging complete / Launch started]
**Plan:** `[path/to/plan.md]`
**Survival guide:** `[path/to/survival-guide.md]`
**Learnings:** `[path/to/learnings.md]`
**Execution log:** `[path/to/execution-log.md]`
**Durable docs manifest (optional):** `[.ai-docs/manifest.md]`
**Branch:** `[feat/branch-name]`
**PR:** [#N / "not created yet"]
**Run mode:** [finite / open-ended] | **User returns:** [time / "never"]

**Batch breakdown:**
1. [Batch 1 name] — [one-line scope]
2. [Batch 2 name] — [one-line scope]
3. [Batch 3 name] — [one-line scope]

**Preflight:**
- Git remote / push / `gh` auth: [PASS / WARN / FAIL]
- Validation gate dry run: [PASS / WARN / FAIL]
- Environment / sleep / notification checks: [PASS / WARN / N/A]
- Notes: [anything the next call needs to know before launch]

**Launch readiness:** [READY / BLOCKED]

**Launch prompt:**
> [Paste the short launch prompt handed to the user for the next call.]

---

<!-- ================================================================
     BATCH CONTRACT TEMPLATE: add this before implementation starts.
     It records what "done" means before code or docs change.
     ================================================================ -->

## Batch [N] Contract: [YYYY-MM-DD HH:MM timezone]

**Behaviors:**
- [Specific behavior 1]
- [Specific behavior 2]

**Build on:**
- [Existing pattern, utility, or document structure to extend]
- [Existing convention to follow]

**Acceptance criteria:**
- [ ] [Criterion 1]
- [ ] [Criterion 2]

**Blast radius:**
- `[shared/file/or/doc]` ([N] consumers), [additive / modified / breaking]
- Risk: [low / medium / high], [one-line explanation]

**Pre-implementation survey:**
- `[command]` -> [what you found]
- `[command]` -> [what you found]

---

<!-- ================================================================
     BATCH ENTRY TEMPLATE: copy this block for each completed batch.
     Fill in all fields. Do not leave fields blank. Use "N/A" if not applicable.
     ================================================================ -->

## [YYYY-MM-DD HH:MM timezone]

**Batch:** [N: Batch Name]
**Contract status:** [all criteria met / exceptions: ...]

**Timing:**
- Implement: [Xm] | Validate: [Xm] | Review: [Xm] | Total: [Xm]
- Session elapsed: [X]h [X]m | Budget remaining: ~[X]h [X]m

**What changed:**
- `[file/path.ts]`: [one-line description of change]
- `[file/path.ts]`: [one-line description of change]
- `[file/path.ts]`: [one-line description of change]

**Commands run:**
- `[command]` → [result / exit code / summary]
- `[command]` → [result / exit code / summary]
- `[command]` → [result / exit code / summary]

**Test results:**
- Lint: [PASS / FAIL (N errors)]
- Typecheck: [PASS / FAIL (N errors)]
- Build: [PASS / FAIL]
- Tests: [PASS (N passed, N skipped) / FAIL (N failed: test name)]
- E2E: [PASS / FAIL / N/A]
- Smoke: [PASS (HTTP 200) / FAIL (HTTP NNN) / N/A]

**Review findings:**
- [[Severity]] [Finding title]: [Resolved: description of fix / Dismissed: reason]
- [[Severity]] [Finding title]: [Resolved: description of fix / Dismissed: reason]
- _No findings_ (if review was clean)

**Decisions made:**
- [Decision + reasoning. Document every judgment call made without user input. E.g.,
  "Chose to extract shared validator into /lib/validators.ts rather than duplicating across
  handlers. Reduces future drift, no API surface change."]
- [Decision + reasoning]

**Process adjustments:**
- [Any entropy-check or retro adjustment made to the Elves process itself, e.g., "Added a
  regression-preservation acceptance criterion after repeated review findings" / "none"]

**Docs:**
- Impacted: [list / "none"]
- Updated: [list / "none"]
- Promoted: [learnings or `.ai-docs/*` updates / "none"]
- Deferred: [explicit doc debt left for later / "none"]

**Regression attestation:**
- Cumulative diff: `git diff main...HEAD --stat` shows [N] files changed, [+X/-Y] lines
- Files outside batch scope: [none / list with explanation]
- Shared surfaces modified: [list shared utilities/types/interfaces/configs touched, with consumer count]
- Consumers verified: [for each shared surface, how callers were checked, e.g., "grep shows 12 importers of validation.ts, all unchanged"]
- Test baseline: [X total (A passed, B skipped) at session start; Y total (C passed, D skipped) now; delta: +Z new, 0 removed, 0 newly skipped]
- Confidence: [HIGH / MEDIUM / LOW], [1-2 sentence explanation. Not "all tests pass." Explain what you checked and why existing functionality is preserved. E.g., "HIGH, all changes are additive (new functions, new tests). No existing function signatures, types, or interfaces were modified. 12 consumers of validation.ts verified unchanged."]

**Commit:** `[abc1234]`
**Rollback tag:** `elves/pre-batch-[N]`

**Next:**
1. [Immediate next task. Be specific enough that a fresh session can start without re-reading the plan.]
2. [Task after that]

---
<!-- Add older entries below this line, newest first -->
