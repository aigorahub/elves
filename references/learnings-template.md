# Project Learnings

> This file is durable memory across Elves runs. Use it for stable, reusable lessons the agent
> should not have to rediscover: repo conventions, tooling quirks, flaky tests, review heuristics,
> domain invariants, and known traps.
>
> Read this after the survival guide and `.elves-session.json`, before the plan and execution log.
> Update it whenever a batch uncovers something that is likely to matter again later tonight or in
> a future run.
>
> Do **not** use this file for batch status, temporary debugging notes, or one-off details that
> are only relevant to the current run. Those belong in the execution log. When a learning matures
> into a stable repo truth, promote it onward into `.ai-docs/architecture.md`,
> `.ai-docs/conventions.md`, or `.ai-docs/gotchas.md`.

---

## Promotion Rules

Promote something into this file only if it is:

- **Reusable:** likely to help a later batch or a future run
- **Stable:** not expected to change again in the next hour
- **Actionable:** changes what the agent should do, avoid, or verify
- **Specific:** concrete enough that another session can apply it without guessing

Good examples:

- "Payments integration tests require `STRIPE_MOCK=true` locally or they fail before app code runs."
- "All API handlers must return `{ error, code }` via `ApiError`; reviewers flag ad hoc error shapes."
- "The Playwright suite is reliable in headed mode but flakes in WebKit on CI; Chromium is the gate."

Bad examples:

- "Batch 3 took a long time."
- "Need to look into auth tomorrow."
- "Tried X first, then switched to Y."

When a learning becomes outdated, do not silently delete it. Move it to `## Retired Learnings`
with a short note about what changed.

---

## Ledger (ids, history, rollback, digest)

Entries may carry stable ids:

```markdown
- [L3] [2026-08-05] Lesson text. (evidence: execution-log 2026-08-05 B2 | commit 7ff97e7) (expect: how a later run validates it)
```

Id-tagged entries are managed by the learnings ledger
(`cobbler_agents.py learnings validate|apply|rollback|digest|migrate`):

- **create** requires a non-empty evidence pointer; `(expect: …)` records how a future run can
  validate the lesson.
- **retire** moves the entry under `## Retired Learnings` (never deletes). If that heading is
  missing on a hand-rolled file, retire creates it at EOF rather than refusing. Every applied
  edit appends a before/after row to the tracked `learnings-history.jsonl` sidecar (bounded caps —
  a full history refuses loudly rather than dropping rows), and **rollback** applies the inverse
  edit with `rollback_of` provenance.
- **Rollback is per history row, not per apply batch.** A multi-edit `learnings apply` writes one
  history row per edit; one `learnings rollback` undoes only the most recent non-rolled-back row.
  Repeat rollback to walk further back.
- **Provenance ordering:** the file is written before its history rows. A process death in that
  narrow gap can leave an applied edit without a rollback row (refuse-don't-destroy still holds;
  re-apply or hand-edit if needed). History is never written before the doc so a crash cannot
  invent phantom applied edits.
- A bounded `## Digest` block (at most 40 one-line entries) is regenerated only between its
  HTML-comment markers. Read the digest first at orient; pull full entries on demand.
- Freehand dated bullets (`- [YYYY-MM-DD] …`) remain fully valid. Ledger edit verbs refuse on an
  id-less file with a `migrate` hint; `migrate` is explicit, idempotent, and never automatic.
  The ledger never reflows, reorders, or rewrites content it did not edit.

## Promotion Destinations

Use this file as the durable promotion inbox, not the final resting place for every lesson:

- Promote to `.ai-docs/architecture.md` when the lesson explains a stable system boundary, flow,
  or dependency map.
- Promote to `.ai-docs/conventions.md` when the lesson is a repeatable rule, pattern, or review
  expectation the next agent should follow by default.
- Promote to `.ai-docs/gotchas.md` when the lesson is a recurring trap, flaky behavior, hidden
  dependency, or confusing failure mode.
- Keep the lesson here if it is reusable and stable but not yet important enough to curate into
  `.ai-docs`.

---

## Repo Conventions

- [YYYY-MM-DD] [Convention the agent should follow next time.]

## Validation and Tooling

- [YYYY-MM-DD] [Command, test, deploy, or environment behavior the agent should remember.]

## Review Heuristics

- [YYYY-MM-DD] [What reviewers/bots reliably care about in this repo.]

## Product and Domain Invariants

- [YYYY-MM-DD] [Behavior that must stay true even if the implementation changes.]

## Known Traps

- [YYYY-MM-DD] [Failure mode, hidden dependency, or misleading path the agent should avoid.]

## Retired Learnings

- [YYYY-MM-DD] [Old learning] -> retired because [what changed].
