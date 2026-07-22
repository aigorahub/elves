# Landing authority (host-owned)

Machine source: `scripts/cobbler_runtime/landing_authority.py`.

## Principles

1. Landing outcome is host control, not worker evidence.
2. Complete-without-merge and complete-and-merge share one implement → review → revise → readiness pipeline.
3. Active-run `/land-pr` (or `\land-pr`) grants `driver_authorized` without setting `ready` or restarting readiness.
4. Merge guard requires: completed acceptance, resolved blockers, clean exact-tip review evidence, required checks, distinct green project landing checks, clean worktree, not draft, `ready`, `driver_authorized`, `landing_outcome=complete_and_merge`, and `current_head == readiness_head`.
5. Merge method is a regular merge commit only — never squash or rebase for Elves landing.

## Hostile worker fields (ignored)

`landing_outcome`, `driver_authorized`, `merge_authority`, `ready`, `readiness_head`,
`readiness_attested_at`, `host_merge_authorized`, `driver_merge_authorized`,
`project_landing_checks_green`, `project_landing_checks_digest`.

## Exact-HEAD readiness

Readiness is attested to an exact commit SHA with an inputs digest. Changing HEAD invalidates
readiness but not authorization. Scoped invalidation can clear only acceptance, review, checks, or
project-landing, or worktree proof. A present `.elves/landing-profile.json` requires live green
results plus a matching host-owned canonical digest; a missing profile is neutral. See
[`project-landing-profiles.md`](project-landing-profiles.md).

## Chat-to-work vs chat-to-land

| Mode | Landing outcome | Merge |
|------|-----------------|-------|
| chat-to-work | `landable_pr` | User merges later |
| chat-to-land | `complete_and_merge` after readiness | Driver merges only when authorized + ready |

## Landing check

Installed helper (never bare source-checkout path as the install contract):

```bash
python3 "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py" \
  --session <session-path> --repo-root .
```

`plan_path` in the session is authoritative; an explicit `--plan` is only an equality assertion.
Landable means plan Acceptance with proof — not green CI alone.
