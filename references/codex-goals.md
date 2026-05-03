# Using Elves With Codex Goals

Codex Goals can make Elves runs more reliable by providing a native continuation backend for
Codex. Treat Goals as the engine that keeps Codex moving, and Elves as the operating protocol that
defines what the agent must do before the branch is review-ready.

Goals should not replace the Elves loop. The plan, survival guide, execution log,
`.elves-session.json`, learnings file, PR feedback, and Readiness Gate remain the source of truth.

## When To Use Goals

Use Codex Goals when:

- You are launching from Codex and your installed version supports `/goal`.
- The work is long enough that normal chat continuation may drift, pause, or hit memory pressure.
- You want Codex to keep looping until an objective is complete or its configured budget is
  exhausted.

Use the normal Elves launch prompt when:

- You are running in Claude Code, Claude.ai, or another non-Codex environment.
- `/goal` is unavailable or disabled in your Codex install.
- The task is short enough that the normal launch prompt is simpler.

## Setup

Follow the current Codex documentation for enabling Goals, feature flags, and any token or runtime
budgets. Elves should not hard-code Codex configuration details because Goals is platform-specific
and may change across Codex releases.

Useful references:

- [Codex release notes](https://github.com/openai/codex/releases)
- [Codex changelog](https://developers.openai.com/codex/changelog)
- [Codex best practices](https://developers.openai.com/codex/learn/best-practices)

## Launch Pattern

Stage the Elves run first. The branch, PR, plan, survival guide, learnings file, execution log,
preflight, run mode, Stop Gate, and launch prompt should already exist.

Then start the run with `/goal`:

```text
/goal The run is staged. Start now.
Read docs/elves/survival-guide.md first, then `.elves-session.json` if it exists, then
docs/elves/learnings.md if it exists, then docs/plans/my-plan.md, then the execution log at
docs/elves/execution-log.md, then `.ai-docs/manifest.md` if it exists.

Use the survival guide Stop Gate and Elves Readiness Gate as the definition of completion.
Do not stop unless the Stop Gate allows it, I explicitly stop you, or you hit a genuine blocker.
Run the full Elves loop: verify green, contract, implement, validate, review PR feedback, document,
update memory, commit, push, reread the survival guide, and continue.

If the goal budget is exhausted before the Readiness Gate is clean, do not claim completion.
Write a reactivation handoff, update the execution log and survival guide, commit, push, and leave
the exact prompt needed to resume in a fresh goal or normal launch.
```

## Completion Rules

Codex may decide a goal is complete when the objective appears satisfied. Elves should use a
stricter definition. The goal is complete only when the Elves Readiness Gate is clean:

- All planned batches are complete or explicitly deferred.
- Local and preview proof are green on the current tip.
- PR comments, review threads, issue comments, and checks are handled.
- The final cumulative review is clean.
- Strategic forgetting is complete and a reactivation handoff exists if any work remains.
- Git status is clean and the branch is pushed.

Progress is not completion. A checkpoint is not completion. A clean goal turn is not completion.

## Budget Exhaustion

If Codex Goals stops because its token, time, or continuation budget is exhausted, treat that as a
checkpoint:

1. Update the execution log with the current state and remaining work.
2. Update the survival guide's `Current Phase`, `Stop Gate`, and `Next Exact Batch`.
3. Update `.elves-session.json` so the next session can recover quickly.
4. Write a concise reactivation handoff with branch, PR, validation state, unresolved risks, and
   the next prompt.
5. Commit and push.
6. Do not say the run is complete unless the Readiness Gate is actually clean.

## Why This Split Works

Codex Goals provides persistence and continuation. Elves provides:

- staged plans and launch prompts
- batch contracts and rollback tags
- validation and review discipline
- PR feedback handling
- documentation and durable memory
- strategic forgetting and resource hygiene
- final merge-readiness checks

Together, Goals keeps the engine running and Elves keeps the work pointed at a review-ready branch.
