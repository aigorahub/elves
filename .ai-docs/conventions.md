# Conventions

## Cross-file sync

- `SKILL.md` and `AGENTS.md` must change together when Elves behavior changes.
- Template updates in `references/*` should reflect the same model as the skill files.
- A release version bump is incomplete until the skill metadata, `AGENTS.md`, and
  `CHANGELOG.md` all agree.
- Run control is live metadata. If stop behavior, checkpoint meaning, or continuation policy
  changes mid-run, rewrite the survival guide's `Run Control` block immediately and log the change
  in the execution log.
- The live survival-guide sections are `Run Control`, `Current Phase`, `Active Compute`, and
  `Next Exact Batch`. Rewrite them in place; do not stack old updates there.
- If a run uses paid compute, remote jobs, or long-lived local services, keep `Active Compute`
  current after every push and after every resource-topology change.
- Installed Claude/Codex skill bundles should ship only the installable runtime surface:
  `SKILL.md`, `AGENTS.md` (Codex), `references/`, `scripts/preflight.sh`,
  `scripts/notify.sh`, and `scripts/install_doctor.py`. Repo-only maintenance helpers stay in the
  checkout.
- Startup installation/update checks must stay advisory-only. They may alert the user, but they
  must never block a run or auto-update the installed skill.

## Documentation as part of done

- Treat documentation freshness as part of batch completion, not cleanup theater at the end.
- Explicitly record docs that were impacted, updated, promoted, or deferred.
- Prefer promoting durable knowledge into `learnings` or `.ai-docs/*` instead of burying it in the
  execution log.
- Kickoff prompts, report templates, and other operator-facing forms should mirror the same
  run-control model as the core skill files.

## Product direction

- Keep Elves lightweight and operationally realistic.
- Borrow architecture from richer systems when it reduces confusion, but do not import heavy
  hydration or automation machinery without a clear need.
- Preserve the stage-then-launch model and the PR-centric review loop unless a change explicitly
  improves them.
