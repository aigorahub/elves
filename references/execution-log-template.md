# Execution Log

> This is the running record of everything Elves has done during this session. Timestamped
> chronological entries are immutable once recorded; corrections are new entries that cite the old
> one. The `Run Digest` and final `Session Summary` are intentionally mutable summaries. New
> chronological entries are added at the **top** (reverse chronological order, newest first).
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
> If this file exceeds ~50 entries, move older completed entries intact under a `## Completed
> Archive` heading at the bottom. Archiving changes location, not the entry text; update the mutable
> Run Digest after the move.

---

## Run Digest

> Refresh this small summary after every host-native/legacy batch. During a healthy trusted
> `branch_progress` full-run, the parked host does not edit it after worker batches or pushes;
> reconcile it once at terminal/safety wake so a fresh session can get bearings quickly.

- **Last updated:** [YYYY-MM-DD HH:MM timezone]
- **Current phase:** [Staging / In progress / Scout mode / Blocked / Complete]
- **Active batch:** [B#: Batch N: Name]
- **Last completed batch:** [B#: Batch N: Name / "none yet"]
- **Next exact batch:** [B#: Batch N: Name]
- **Active PR:** [#N / "not created yet"]
- **Docs promoted this run:** [list / "none yet"]
- **Deferred hygiene:** [none / count + top items; drain at terminal]
- **Latest Elves Report:** [/tmp/elves-report-...html / "not generated yet"]
- **Progress commits:** host-native/legacy uses
  `[branch · Batch N/total · Contract|Implement|Validate|Review|Close] concrete outcome`; the exact
  registered trusted `branch_progress` worker uses the same schema only on its assigned feature
  branch while the host parks; untrusted workers create audited detached handoff commits only and
  never own refs/remotes/push/PR/run-memory; protected refs, PR actions, canonical memory, final
  review, and merge remain host-owned; forbid vague subjects (`Updates`, `progress`, `WIP`, bare
  `fixes`), and require acceptance evidence for `Close`
- **Handoff standard:** worker packets include intent/why, non-obvious rationale, Build On targets,
  owned surfaces, forbidden surfaces, acceptance evidence, failure modes/pitfalls, and
  HEAD/run-doc paths/route-session identity/output format

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
**Elves Report:** [/tmp/elves-report-...html / "not generated"]
**Master Acceptance:** [M-A1 → evidence; M-A2 → evidence; unresolved ids explicitly listed]

**Problems found:**
- [Major bug, UX gap, review blocker, repeated failure pattern, or "none beyond planned scope"]
- [Major problem found]

**Lessons learned:**
- [Durable learning promoted to learnings.md or `.ai-docs/*`]
- [Process, product, testing, or implementation lesson]

**Human next steps:**
1. [Review/merge/deploy/re-run/plan next action]
2. [Next action]

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
**Checkpoint semantics:** [none / delivery checkpoint / hard stop] | **Actual stop conditions:** [list]
**Coordination:** [Cobbler-first / direct-agent override] | **Material lens decisions:** [summary / "none yet"]
**Active compute at launch:** [none / list]
**Continuation guard:** stop_allowed=[yes / no] | remaining_batches=[N] | checkpoint_is_stop=[yes / no] | next_required_action=[one sentence]

**Batch breakdown:**
1. [B0 or B1: first batch name] — [one-line scope]
2. [next stable batch id: second batch name] — [one-line scope]
3. [next stable batch id: third batch name] — [one-line scope]

**Stable acceptance identity:** [B0-A1 or B1-A1, …; M-A1, M-A2, …]. `B0` and `B1` are equally
valid starts; Elves does not reserve or prefer either convention. Bare
`- [ ] B0-A1: criterion` and bracketed `- [ ] [B0-A1] criterion` rows are equivalent. For a legacy
plan without explicit ids, record deterministic aliases by document order before completion and
never renumber them afterward.

**Preflight:**
- Git remote / push / `gh` auth: [PASS / WARN / FAIL]
- Validation gate dry run: [PASS / WARN / FAIL]
- Acceptance staging validation: [PASS — plan syntax parsed and session/packet id/text mappings
  match / BLOCKED — targeted diagnostic]
- Acceptance staging command: [`acceptance_contract.py validate`; optional explicit
  `sync-session --write` used / not needed]
- Environment / sleep / notification checks: [PASS / WARN / N/A]
- Notes: [single-kickoff continues after launch-ready; legacy two-call only if explicit]

**Launch readiness:** [READY / BLOCKED]

**Launch prompt:**
> [Legacy two-call only: paste short launch prompt. Single-kickoff continues without a second human message.]

---

<!-- ================================================================
     BATCH CONTRACT TEMPLATE: add this before implementation starts.
     It records what "done" means before code or docs change.
     ================================================================ -->

## Batch [N] [B#] Contract: [YYYY-MM-DD HH:MM timezone]

**Behaviors:**
- [Specific behavior 1]
- [Specific behavior 2]

**Build on:**
- [Existing pattern, utility, or document structure to extend]
- [Existing convention to follow]

**Acceptance criteria:**
- [ ] B#-A1: [Criterion 1]
- [ ] [B#-A2] [Criterion 2]

**Blast radius:**
- `[shared/file/or/doc]` ([N] consumers), [additive / modified / breaking]
- Risk: [low / medium / high], [one-line explanation]

**Phase routing (optional):**
- Requested route: [none / phase preference from `model-routing`]
- Actual route: [host-native / native-subagent / direct-analysis / provider-backed / N/A]
- Fallback reason: [none / material reason route changed]

**Pre-implementation survey:**
- `[command]` -> [what you found]
- `[command]` -> [what you found]

---

<!-- ================================================================
     BATCH ENTRY TEMPLATE: copy this block for each completed batch.
     Fill in all fields. Do not leave fields blank. Use "N/A" if not applicable.
     ================================================================ -->

## [YYYY-MM-DD HH:MM timezone]

**Batch:** [B#: N: Batch Name]
**Contract status:** [all criteria met / exceptions: ...]
**Close commit scope:** [single batch N only / multi-batch with per-batch Validate sections below]

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

**Validate:** _(required for stable batch id `B#` before `status: complete`; if closing multiple
batches, repeat a labeled section per id, e.g. `**Validate for B3:**`)_
- Evidence dir: `[scratch/batch-N/ or N/A]`
- Lint: [PASS / FAIL (N errors)] → transcript `[path or inline summary]`
- Typecheck: [PASS / FAIL (N errors)] → transcript `[path or inline summary]`
- Build: [PASS / FAIL] → transcript `[path or inline summary]`
- Tests: [PASS (N passed, N skipped) / FAIL (N failed: test name)] → transcript `[path or inline summary]`
- Plan Acceptance proof: [list stable id `B#-A#` → criterion → evidence; not only "tests green"]
- God-file / split metric (if applicable): [LOC/facade result or "N/A" or hard-stop note]

**Test results:**
- Lint: [PASS / FAIL (N errors)]
- Typecheck: [PASS / FAIL (N errors)]
- Build: [PASS / FAIL]
- Tests: [PASS (N passed, N skipped) / FAIL (N failed: test name)]
- E2E: [PASS / FAIL / N/A]
- Smoke: [PASS (HTTP 200) / FAIL (HTTP NNN) / N/A]
- Session acceptance rows written: [yes — id/criterion/met/evidence / no — not complete yet]

**Review findings:**
- [[Severity]] [Finding title]: [Resolved: description of fix / Dismissed: reason]
- [[Severity]] [Finding title]: [Resolved: description of fix / Dismissed: reason]
- _No findings_ (if review was clean)

**Decisions made:**
- [Decision + reasoning. Document every judgment call made without user input. E.g.,
  "Chose to extract shared validator into /lib/validators.ts rather than duplicating across
  handlers. Reduces future drift, no API surface change."]
- [Decision + reasoning]

**Cobbler synthesis:**
- Recommendation: [material fitted answer or "N/A"]
- Strongest dissent: [objection, uncertainty, or verification gap preserved / "N/A"]
- Next move: [action taken because of the synthesis / "N/A"]

**Route notes:**
- Requested route: [none / phase preference]
- Actual route: [host-native / native-subagent / direct-analysis / provider-backed / N/A]
- Fallback reason: [none / material reason route changed]
- Math ledger status, when relevant: [claim/source/model-call/human-verification ledgers updated / N/A]

**Process adjustments:**
- [Any entropy-check or retro adjustment made to the Elves process itself, e.g., "Added a
  regression-preservation acceptance criterion after repeated review findings" / "none"]

**Docs:**
- Impacted: [list / "none"]
- Updated: [list / "none"]
- Promoted: [learnings or `.ai-docs/*` updates / "none"]
- Deferred: [explicit doc debt left for later / "none"]

**Regression attestation:**
- Cumulative diff: `git diff <default-branch>...HEAD --stat` shows [N] files changed, [+X/-Y] lines
- Files outside batch scope: [none / list with explanation]
- Shared surfaces modified: [list shared utilities/types/interfaces/configs touched, with consumer count]
- Consumers verified: [for each shared surface, how callers were checked, e.g., "grep shows 12 importers of validation.ts, all unchanged"]
- Public API surface snapshot: [N/A / unavailable reason / no delta / additive / planned breaking / unexpected breaking; include baseline/current/diff artifact paths when configured]
- Test baseline: [X total (A passed, B skipped) at session start; Y total (C passed, D skipped) now; delta: +Z new, 0 removed, 0 newly skipped]
- Confidence: [HIGH / MEDIUM / LOW], [1-2 sentence explanation. Not "all tests pass." Explain what you checked and why existing functionality is preserved. E.g., "HIGH, all changes are additive (new functions, new tests). No existing function signatures, types, or interfaces were modified. 12 consumers of validation.ts verified unchanged."]

**Commit:** `[abc1234]`
**Rollback authority:** [host-native/legacy: `refs/elves/rollback/<run>/<session>/bN-<digest>` |
trusted full-run: host-created `b0` launch ref plus worker commit SHA(s)]

**Next:**
1. [Immediate next task. Be specific enough that a fresh session can start without re-reading the plan.]
2. [Task after that]

---
<!-- Add older entries below this line, newest first -->
