# Execution log — v2.32 open-issue harvest

Branch: `feat/v2.32-open-issue-harvest`
Worktree: `/Users/john/aigora/dev/elves-v2-32-open-issue-harvest`
Start tip: `8d2a350f4f291117be10908c5def6b92211400bb`

---

## Staging (2026-08-20)

Read all ten open issues with comments. Verified against the current `main` tree that merged
PR #241 (merged 2026-08-07) already implements the fixes claimed for #244, #245, #247, and #248:

- `#244` — `.github/workflows/ci.yml` exists and runs `verify_repo --ci` on push/PR across
  macOS py3.12 (authoritative) plus two observational ubuntu cells.
- `#247` — `tests/test_provider_shortcuts.py:37-57` carries the module-level `python3` shim that
  the issue's own follow-up comment identified as the real cure.
- `#248` — `scripts/cobbler_runtime/acceptance.py:503-525` detects legacy `### B# ·` headings and
  names the canonical rewrite inside `plan_batch_required`.
- `#245` — answered empirically on the issue by a green all-cell Linux CI run; the ubuntu cells
  shipped with #244.

Triage verdicts:

| Issue | Verdict | Reason |
|-------|---------|--------|
| #260 | fix (B1) | P1 bug; three live failure modes; costs a full manual re-drive per miss |
| #242 | fix residual (B2) | test flake fixed by #241; upstream one-poll lag kept the issue open |
| #249 | partial (B3) | round-4 `_section_at` closer only; items 1 and 3 are operator-owned |
| #258 | fix (B4) | qualification records the requested route as proof of the effective one |
| #243 | attempt last (B5) | lowest return; additive advisory plumbing |
| #244 | close | shipped in #241 |
| #245 | close | answered empirically; Linux cells green |
| #247 | close | shipped in #241 |
| #248 | close | shipped in #241 |
| #246 | skip | needs a supervised live launchd/systemd trial across a real machine sleep |

Staged the run: dedicated worktree, plan, survival guide, learnings, session JSON.

---

## B0 — Reconcile the issue ledger against merged PR #241 (2026-08-20)

Verified each fix as an ancestor of `main` (`git merge-base --is-ancestor`), then closed with a
comment naming the implementing location:

- #244 → closed. `.github/workflows/ci.yml`, commit `92d939e`.
- #247 → closed. `tests/test_provider_shortcuts.py:37-57` shim, commit `0343fa6`. Re-verified
  standalone on `main`: `python3 -m unittest tests.test_provider_shortcuts` → 57 tests, OK
  (1 skip), Python 3.14.6. No order dependency exists.
- #248 → closed. `scripts/cobbler_runtime/acceptance.py:503-525`, commit `3e0e209`.
- #245 → closed. Linux cells shipped with `92d939e`; the empirical all-green Linux run is
  recorded on the issue.

Issue URLs: https://github.com/aigorahub/elves/issues/244, /245, /247, /248.

B0 acceptance B0-A1..B0-A5 met.

---

## B1 — Prewalk artifact contracts and lenient prose bounds (#260, 2026-08-20)

`guide_prompt()` now states both artifact shapes with a filled example each, plus the rules the
validators actually enforce. The test parses the two JSON blocks straight out of the rendered
prompt and runs them through `validate_todo_artifact` and `validate_checkpoint_artifact`, so the
documented example cannot drift from the contract it documents.

Two bounds normalized rather than enforced:
- `summary` past 500 characters truncates (`_normalized_summary`) instead of raising.
- Absent or null `validation_attempted` becomes `[]`.

Held strict on purpose: identity fields, schema version, `PW-##` ordering, single `in_progress`,
`ready_for_execution_model: true`, RFC3339 with timezone, and every malformed
`validation_attempted` entry. A prose `validation` string is not coerced into a command record —
that would invent an exit code the guide never observed.

Proof: `python3 -m unittest tests.test_native_worker_prewalk` → 55 tests OK. Impact path
(`test_native_worker_hardening`, `test_omp_main_driver`, `test_host_profiles`,
`test_check_repo_consistency`, `test_installed_bundle_smoke`) → 159 tests OK.

B1 acceptance B1-A1..B1-A5 met.
