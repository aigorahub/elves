# Runtime Helper Paths

Elves runtime helpers belong to the Elves skill, while run state belongs to the target repository.
Keep those two roots distinct.

## Source checkout shorthand

Commands written as `python3 scripts/<helper>.py ...` are source-checkout shorthand. Use that form
only when the current checkout actually contains Elves' `scripts/` directory.

## Installed Claude Code or Codex skill

For an installed skill, set `ELVES_SKILL_ROOT` to the directory containing the active Elves
`SKILL.md`, then invoke the helper by its absolute installed path:

```bash
# Claude Code global install
ELVES_SKILL_ROOT="$HOME/.claude/skills/elves"

# Codex global install (use this instead when Codex is the active host)
ELVES_SKILL_ROOT="$HOME/.codex/skills/elves"

python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" doctor \
  --repo-root "$PWD" --json
```

A project-local install uses its active `.claude/skills/elves` or `.codex/skills/elves` directory
instead. Resolve the path from the skill that was actually loaded; do not assume the global copy
won when a project-local copy may shadow it.

Keep the target repository as the working directory. Do not `cd` into the installed skill merely to
make a relative helper path work. When the working directory is not the target repository, pass the
helper's `--repo-root <target-repository>` option where supported.

## Staging and final-readiness tools

The installed bundle ships `scripts/acceptance_contract.py` for prelaunch plan/session validation
and proof-preserving session scaffolding, `scripts/landing_profile.py` for deterministic project
checks, plus `scripts/elves_landing_check.py` for final readiness.
Invoke both from the active skill root. Generic Elves runs combine final acceptance checking with
the target project's own broad gates: tests, lint, type checking, builds, links, secret scanning,
API checks, or other checks appropriate to that repository.

Repositories may track `.elves/landing-profile.json`; run it directly with
`python3 "$ELVES_SKILL_ROOT/scripts/landing_profile.py" check --repo-root . --base origin/main
--json`. Strict landing runs it automatically and binds any present profile to exact HEAD, resolved
base/merge-base identity, normalized results, and host-owned readiness evidence. Schema v1 accepts
only declarative path checks and post-merge checklist items; it never runs profile-supplied commands.
The same CLI also exposes host-owned learning commands (`observe`, `propose`, `candidates`,
`promote`, `waive`, `clear-waiver`). Only explicit `promote` rewrites the tracked profile; runtime
learning state stays under gitignored `.elves/runtime/landing-profile/`.

## Shipped call-site runtime deps

Installed bundles also ship helpers that other entrypoints exec or load by relative path (not only
CLI entry points themselves):

- `scripts/worktree_gc.py` — used by `scripts/preflight.sh --gc-worktrees`
- `scripts/provider_supervisor.py` — used by `scripts/cobbler_runtime/full_run.py` for provider child
  supervision

If either file is missing from an installed skill root, worktree GC and trusted full-run supervision
fail closed. Bundle smoke requires both paths.

## Source-only archives

`docs/plans/` (historical plan archive) and `docs/elves/` (durable learnings and run memory for this
source repo) are **source-checkout only**. They are not part of the installed Claude Code or Codex
skill surface. Committed examples and templates remain non-identifying.

Repository-maintenance helpers such as `scripts/verify_repo.py`, `scripts/release_checklist.py`,
and `scripts/check_repo_consistency.py` are intentionally not part of an installed bundle. Use one
only when the target source checkout itself provides it. Never make an ordinary installed Elves run
depend on a repo-only helper.
