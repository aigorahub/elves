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

---

## B2 — Terminal-flip events re-read (#242 residual, 2026-08-20)

The residual question on #242 was whether `monitor_full_run` should force one events re-read when
a validated report first flips the run terminal. It should, and the window is real: the monitor
captures the event-log signature at the top of a poll and reads the report after it, and a worker
(the fixture included) writes its complete report *before* appending `run_complete`. An append
landing inside that window leaves the signature matching the cache while the cached summary
predates the final event.

Fix: one re-read at that boundary, behind the same `grant_context_verified` guard as the ordinary
read. `_read_events` is now called through a local `_load_events()` so both call sites cannot
drift. The two inline terminal-status sets are now named constants
(`_TERMINAL_REPORT_STATUSES`, `_TERMINAL_STATE_STATUSES`) because the report and state vocabularies
differ (`stopped`/`stale` are state-only).

Proof: three new tests (re-read, cache still reused on a healthy poll, no re-read without
credential context). Negative control run: with the re-read disabled the first test fails on
`events_reused` (`True is not false`). Full `tests.test_full_run_supervisor` → 184 tests OK.

Observation banked as deferred hygiene: one run of the supervisor suite errored in
`_run_supervision_canary` ("Trusted recursive supervisor could not observe its marker canary")
and the identical suite passed on immediate re-run. Same timing-sensitive family as #242, and not
caused by this change.

B2 acceptance B2-A1..B2-A3 met.

---

## B3 — Learnings-ledger digest-interior guard (#249 closer, 2026-08-20)

The issue named `_section_at`. Fixing only that is not enough: `_section_insert_index` — the path a
*declined* positional restore falls back to — reads headings the same way, so the drift guard would
correctly refuse a drifted candidate and then place the entry under the forged in-digest heading
anyway. Found while building the reproduction; both are fixed together.

Reproduction (now a test): a forged `## Repo Conventions` between the digest markers plus
cooperating drift restored an active learning into `## Retired Learnings`, silently retiring it.
Both new tests fail with the guards removed; `tests.test_learnings_ledger` → 24 tests OK with them.

Operator-owned items 1 and 3 recorded on the issue and left alone:
https://github.com/aigorahub/elves/issues/249#issuecomment-5364103921

B3 acceptance B3-A1..B3-A3 met. The issue stays open for item 1.
