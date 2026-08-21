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

---

## B4 — Observed effective route (#258, 2026-08-20)

`checks["route_change"]` no longer starts True. It is derived after the execution phase from
`ObservedRoute`, a new bounded record of what a host published about the route it ran.

Fail-open by design, and stated as such: only Codex publishes an effective-route signal, and only
when the model actually changes, so the common native route (same model, lower effort) is silent by
construction. A missing signal records `route_change_evidence: unobserved`; a signal that
contradicts the requested execution model fails with `prewalk_route_change_unqualified`. Observed
effort is always null — no supported host publishes the reasoning level it used, and copying the
request into that field would recreate the defect.

The Codex notice arrives as `item.completed` with an inner item type of `error`. Parsing reads the
inner item; the top-level type is what `_PROVIDER_ERROR_EVENT_TYPES` reads, so it is still not
classified as a provider failure. Test-pinned.

The Grok qualification artifact required an exact field set, so adding keys would have invalidated
every previously recorded artifact. The check now requires the same required set and admits a
closed optional set, so old artifacts still validate and arbitrary keys are still rejected.

Proof: `tests.test_native_worker_prewalk` → 60 OK. Impact path across eight prewalk-touching
modules → 252 OK.

B4 acceptance B4-A1..B4-A5 met.

---

## B5 — Observed-usage wiring (#243): not attempted (2026-08-20)

Stopped at the feasibility check rather than landing a half wiring, as the plan's B5 caution
anticipated. Two blockers, both design decisions rather than plumbing:

1. No source to aggregate. `usage_ledger` has exactly one consumer today (`cobbler_agents.py`),
   and the full-run `EVENT_TYPES` vocabulary has no usage event. A full run persists
   `events.jsonl` and a redacted follow log; neither carries per-transport token counts. Wiring
   reconcile and close first requires choosing a persistence point — a new event type inside the
   fail-closed event schema, or a separate usage sidecar.
2. Two of the three extractors do not exist. Only the Grok typed-stream parser
   (`_GROK_STREAM_USAGE_KEYS`) reads usage. The claude stream-json and codex `turn.completed`
   shapes named in the issue have no reader here, so their mapping would be invented.

Recorded on the issue: https://github.com/aigorahub/elves/issues/243#issuecomment-5364155864
#246 skip also recorded: https://github.com/aigorahub/elves/issues/246#issuecomment-5364155937

Version bumped to 2.32.0 (`SKILL.md`, `CHANGELOG.md`).

---

## Terminal review (2026-08-20)

**Fugu review.** Route: plain `fugu/high`, `review` mode, read-only, no `--include`,
`--max-wait 540`. Log: `docs/elves/fugu-v2.32-review.log`. Result: no P0, one P1, two P2, one P3.
The first launch died after writing only its context bundle; re-run in the foreground produced the
full report.

Each finding was verified against the code before acting.

- **P1 — stale qualification caches bypass the #258 fix. Confirmed, fixed.**
  `prewalk_qualification_cache_path` keys on host, transport, installed version, build commit, and
  the requested execution route — no Elves contract version. So proof recorded while
  `route_change` was assumed true would be reused forever and the new observation would never run
  for anyone with an existing cache. Added `PREWALK_QUALIFICATION_SCHEMA_VERSION` (2) to the
  recorded artifact and required it on load. The reuse path already catches `ValidationIssue` and
  falls through, so `required` spends one fresh canary and `auto` falls back honestly.
- **P2 — the terminal-boundary re-read fires on every poll. Confirmed, fixed.** A worker can write
  a valid terminal report and stay alive finishing cleanup; each such poll saw the same terminal
  report with an unchanged log and re-read it. Now gated on a persisted
  `terminal_report_reread_signature`, so it fires once per event-log identity. Any later append
  changes the signature and takes the ordinary read path, so the marker cannot mask new events.
- **P2 — malformed digest markers. Confirmed real, confirmed pre-existing, filed not fixed.**
  `git show origin/main:...learnings_ledger.py | grep -n 'in_digest = '` shows four boolean marker
  scanners already on `main` (lines 103, 180, 212, 573). The two added for #249 match that model,
  so unterminated and nested sequences are a file-wide pre-existing property, not a regression.
  The real repair is a shared marker validator across all six scanners plus `_regenerate_digest`,
  which is a refactor rather than a widening of this batch. Filed:
  https://github.com/aigorahub/elves/issues/262
- **P3 — newly admitted Grok evidence fields unvalidated. Confirmed, fixed.** The keys were
  admitted without checking their contents, so an operator artifact could carry forged route proof
  for a host that publishes no signal. `_validate_route_evidence` now checks both loaders: the
  fields travel together, observed effort must be null everywhere, an `unobserved` tier may not
  name a model, an `observed_effective_model` tier must name one and its source, and Grok may not
  record an observed tier at all.

**Independent terminal review** (own pass, beyond Fugu):

- Writer/loader consistency: `native_worker.py:1124` is the only producer of the native
  qualification artifact, and it now writes exactly what `prewalk.py:1161` requires.
- No `_refresh_helpers` collision: neither `_TERMINAL_STATE_STATUSES` nor
  `_TERMINAL_REPORT_STATUSES` exists in `full_run`, so the rebind cannot clobber them.
- `guide_prompt()`'s new literal JSON braces are never re-formatted downstream; the string is used
  as input text and hashed, nothing more.
- `_section_insert_index` placement is equivalent to the previous behavior for balanced digest
  blocks: the marker lines are still counted as section content, and with a balanced block
  `DIGEST_END` follows the interior, so `last_content` is unchanged.
- The `_load_events()` closure reads `state.pid`/`state.pgid` before the exit-record handling
  mutates them, so the boundary re-read uses the same `allow_partial_final` value as the first
  read in that poll.

**Proof at this tip:** `python3 scripts/verify_repo.py --ci --base-ref origin/main` → 1598 tests
and every gate OK.

PR: https://github.com/aigorahub/elves/pull/261 — landable, not landed.
