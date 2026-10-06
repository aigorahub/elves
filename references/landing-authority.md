# Landing authority (host-owned)

Machine source: `scripts/cobbler_runtime/landing_authority.py`.

## Principles

1. Landing outcome is host control, not worker evidence.
2. Complete-without-merge and complete-and-merge share one implement → review → revise → readiness pipeline.
3. Active-run `/land-pr` (or `\land-pr`) grants `driver_authorized` without setting `ready` or restarting readiness.
4. Merge guard requires: completed acceptance, resolved blockers, clean exact-tip review evidence, computed merge evidence, distinct green project landing checks, clean worktree, not draft, `ready`, `driver_authorized`, `landing_outcome=complete_and_merge`, and `current_head == readiness_head`.
5. Merge method is a regular merge commit only — never squash or rebase for Elves landing.

## Computed merge evidence

`scripts/cobbler_runtime/merge_evidence.py` answers two questions for the exact HEAD from GitHub,
and the strict landing check uses them instead of a typed `required_checks_green`:

- **Can it merge?** Every required check passed or was skipped, the PR is open, not draft,
  `MERGEABLE`, and not `BLOCKED`, `BEHIND`, or `DIRTY`.
- **Was it tested?** Ordinary path (base is the default branch): a PR comment whose first line is
  `Local tests passed on <head SHA>`, followed by one ``- `<command>`: passed`` line per gate,
  posted by the repository owner, a member, or a collaborator. The record holds nothing else:
  every other non-blank line must read exactly ``- `<command>`: passed`` with a non-empty command.
  Counts, notes, and explanations go in a separate comment; a comment with any other line is not
  a record, so a failed or skipped gate cannot hide in it. Release path (base is `main`
  while `main` is not the default branch): the `release` label, the PR's own latest `release-gate`
  and `full-tests` results passed on the head, and `main` up to date. Socket, Vercel, and skipped
  checks never count as tested. Check results belong to the commit, as they do for branch
  protection.
- **Suite inventory.** A repository lists its tests in `.github/ci-suite.json`, read from the PR's
  base branch so a PR cannot change its own list:

  ```json
  {"schema_version": 1,
   "local_gates": ["npm run lint", "npm test"],
   "test_jobs": ["Lint, typecheck, test, build"]}
  ```

  `local_gates` are the commands a local test record must list as passed. `test_jobs` are the PR
  check names that run tests. Other keys are ignored. With an inventory, a failed `test_jobs`
  check means not tested, any other failed check is reported as `failed_checks_to_triage`, and a
  Dependabot PR (which runs the full suite instead of local tests) is tested when every
  `test_jobs` check passed. Without one, Elves stays strict: any failed GitHub Actions job means not
  tested, the record is trusted as written, and Dependabot PRs are not tested here, so a person
  lands them. A failed app check (Socket, a Vercel preview) is always triaged. An invalid or
  unreadable inventory fails closed.

Unreadable GitHub state fails closed. Pass `--pr` when the current branch has no unique PR; the PR
must belong to this checkout's repository, so a fork PR on the same commit cannot stand in for it.

## Hostile worker fields (ignored)

`landing_outcome`, `driver_authorized`, `merge_authority`, `ready`, `readiness_head`,
`readiness_attested_at`, `host_merge_authorized`, `driver_merge_authorized`,
`project_landing_checks_green`, `project_landing_checks_digest`, `required_checks_green`.

## Exact-HEAD readiness

Readiness is attested to an exact commit SHA with an inputs digest. Changing HEAD invalidates
readiness but not authorization. Scoped invalidation can clear only acceptance, review, checks, or
project-landing, or worktree proof. A present `.elves/landing-profile.json` requires live green
results plus a matching host-owned canonical digest; strict landing recomputes those results and
strips any worker-reported project green/digest fields. Same-user worker isolation remains this
protocol's explicit trust model rather than a profile sandbox or signed authority boundary. A
missing profile is neutral. See
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
