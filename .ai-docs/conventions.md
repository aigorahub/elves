# Conventions

## Cross-file sync

- `SKILL.md` and `AGENTS.md` must change together when Elves behavior changes.
- Template updates in `references/*` should reflect the same model as the skill files.
- A release version bump is incomplete until the skill metadata, `AGENTS.md`, and
  `CHANGELOG.md` all agree.
- Installed Claude/Codex skill bundles should ship only the installable runtime surface:
  `SKILL.md`, `AGENTS.md` (Codex), `references/`, `scripts/preflight.sh`, and `scripts/notify.sh`.
  Repo-only maintenance helpers stay in the checkout.

## Documentation as part of done

- Treat documentation freshness as part of batch completion, not cleanup theater at the end.
- Explicitly record docs that were impacted, updated, promoted, or deferred.
- Prefer promoting durable knowledge into `learnings` or `.ai-docs/*` instead of burying it in the
  execution log.

## Product direction

- Keep Elves lightweight and operationally realistic.
- Borrow architecture from richer systems when it reduces confusion, but do not import heavy
  hydration or automation machinery without a clear need.
- Preserve the stage-then-launch model and the PR-centric review loop unless a change explicitly
  improves them.
