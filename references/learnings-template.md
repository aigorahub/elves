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
