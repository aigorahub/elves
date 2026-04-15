# Project Learnings

> This file is durable memory across Elves runs. Read it after the survival guide and
> `.elves-session.json`, before the plan and execution log. Keep only stable, reusable, actionable
> lessons here.

---

## Promotion Rules

Promote something into this file only if it is:

- **Reusable:** likely to help a later batch or a future run
- **Stable:** not expected to change again in the next hour
- **Actionable:** changes what the agent should do, avoid, or verify
- **Specific:** concrete enough that another session can apply it without guessing

When a learning becomes outdated, move it to `## Retired Learnings` with a short note instead of
silently deleting it.

## Repo Conventions

- [2026-04-11] This repo has two canonical skill surfaces: `SKILL.md` for Claude-compatible agents
  and `AGENTS.md` for Codex. Any behavior change to Elves must update both in the same release.
- [2026-04-11] Elves works best when staging and launch are treated as separate phases even if the
  user asks for a full unattended run in one session; the plan and run-memory docs should be stable
  before implementation batches begin.
- [2026-04-14] Run control is live metadata, not a planning-time note. If the user changes stop
  behavior, checkpoint meaning, or whether work may continue after a deadline, rewrite `## Run
  Control` immediately and log the change in the execution log.
- [2026-04-14] The survival guide is a live operator brief, not a history log. Rewrite `Run
  Control`, `Current Phase`, `Active Compute`, and `Next Exact Batch` in place; leave chronology to
  the execution log.
- [2026-04-14] Stopping should require positive permission, not inference. The survival guide
  should carry a `Stop Gate`, and `.elves-session.json` should carry a `continuation_guard`, so a
  recovered context can tell whether it must keep going without rereading the whole run.

## Validation and Tooling

- [2026-04-11] `./scripts/preflight.sh` is the repo's best built-in environment check. It is useful
  for git/auth/setup validation even though this repo has no package-managed build/test pipeline.
- [2026-04-14] If a run uses paid compute, remote jobs, or long-lived local servers, track them in
  the survival guide's `Active Compute` section and reconcile them after every push or topology
  change.

## Review Heuristics

- [2026-04-11] For this repo, the most common regression risk is documentation drift across
  `SKILL.md`, `AGENTS.md`, templates, and README. Review should verify conceptual alignment, not
  just prose quality.
- [2026-04-11] Treat stale docs as `PENDING-DOCS`, not as a vague warning. If recovery docs,
  durable docs, or human docs lag behind a behavior change, the batch is not clean yet.

## Product and Domain Invariants

- [2026-04-11] Elves is intentionally lightweight. Borrow architectural ideas from richer systems,
  but avoid pulling in hydration, skeleton generation, or opaque automation unless the repo
  genuinely needs them.
- [2026-04-11] The user always merges. PRs are collaboration and review surfaces, not autonomous
  delivery endpoints.

## Known Traps

- [2026-04-11] Repo-level changes can look complete after updating one skill file, but `SKILL.md`,
  `AGENTS.md`, templates, README, and CHANGELOG often drift unless they are reviewed as a set.
- [2026-04-11] If `.elves-session.json` is intentionally committed during a live Elves run, do not
  also ignore it in `.gitignore`; reviewers will correctly read that as contradictory workflow
  guidance.
- [2026-04-14] A checkpoint, return time, or delivery target is not automatically a stop
  condition. If the survival guide does not explicitly call it a hard stop, the agent should treat
  it as a relaunch point and keep going.
- [2026-04-14] Clean commits, green CI, summaries, and user silence are all false stop signals.
  If work remains and the Stop Gate says `no`, the agent should update docs, push, and continue.

## Retired Learnings

- None yet.
