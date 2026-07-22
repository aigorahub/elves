# Project landing profile execution log

## Run Digest

- **Last updated:** 2026-07-22 EDT
- **Current phase:** Staging
- **Active batch:** B1 — ship and dogfood exact-HEAD project landing profiles
- **Last completed batch:** none
- **Next exact batch:** B1
- **Active PR:** #189 (draft)
- **Docs promoted this run:** none yet
- **Latest Elves Report:** not generated yet

## Session Setup: 2026-07-22 EDT

**Plan:** `docs/plans/project-landing-profile.md`

**Survival guide:** `docs/elves/survival-guide-project-landing-profile.md`

**Learnings:** `docs/elves/learnings.md`

**Execution log:** `docs/elves/execution-log-project-landing-profile.md`

**Worker packet:** `.elves/runtime/project-landing-profile-worker.md`

**Branch/worktree:** `codex/project-landing-profile` at
`/Users/john/aigora/dev/elves-project-landing-profile`

**Start head:** `35449718c173f737a7b0dad209accfe86b55b5a9` (`v2.12.0`, `origin/main`)

**Run mode:** finite chat-to-land; regular merge commit and appropriate GitHub release are
user-authorized; X drafting is authorized but posting is not.

**Inventory evidence:**

- Main has Grok's untracked `docs/plans/project-landing-profile.md` and an active Grok process; it
  remains untouched in the shared checkout.
- GitHub has no open PR and latest release `v2.12.0` points to the merged release PR #103.
- The installed Codex CLI advertises resume/route flags but lacks version-bound behavioral prewalk
  qualification. The run will use the same GPT-5.6-high collaboration worker for a packet-once
  guide checkpoint and `Continue.` execution, without claiming native-worker qualification.
- Two independent planning lenses selected a one-batch exact-HEAD MVP and a v2.13.0 release.

**Next:** validate stable acceptance parity, staging preflight, baseline proof, Contract commit,
push, and PR creation.

## Contract validation: 2026-07-22 EDT

- `acceptance_contract.py sync-session --write` derived exact B1/Master criteria with no issues.
- `acceptance_contract.py validate` passed with no warnings.
- The worker packet repeats B1-A1 through B1-A7 exactly and keeps M-A1 through M-A4 host-owned.
- Dedicated-worktree preflight passed branch staleness, ownership, GitHub auth/push dry-run, and
  plan/session staging gates; only expected project-detection/environment advisories remain.
- Baseline focused landing/authority/release/install suite passed 91 tests.
- Baseline repository consistency and v2.12.0 release checklist passed.
- Next: commit/push Contract staging, create the PR, then launch the guide checkpoint.

## Contract push and PR: 2026-07-22 EDT

- Commit `4787b75` staged the plan, session, recovery guide, execution log, and worker packet.
- Branch `codex/project-landing-profile` is pushed and clean.
- Draft PR #189 is the early review surface.
- Next: GPT-5.6-high guide checkpoint, then same-worker `Continue.` execution.

## Independent security review and replan: 2026-07-22 EDT

- The exact-session worker pushed implementation/validation commits through `9a80bf8`; its final
  exact-head verifier passed 1,350 tests.
- Two independent reviews found arbitrary argv execution is not contained by environment
  scrubbing, direct-client blacklists, process groups, or post-hoc repository snapshots.
- A reviewer reproduced a detached child writing after the profile had returned green.
- The authoritative B1 contract is amended to declarative `path_touched` plus
  `post_merge_checklist` checks only. Executable gates are deferred until Elves can require a
  qualified recursive kernel boundary.
- GitHub's Ubuntu Python 3.12 failure is an unrelated 50 ms Manus timeout-test race; profile tests
  passed on Linux 3.10/3.14 and macOS 3.12.
- Next: commit/push the contract amendment, re-drive the same worker for the bounded correction,
  then repeat focused, broad, and independent exact-head review.

## Terminal review correction: 2026-07-22 EDT

- The bounded worker correction removed executable profile gates and passed the exact-head
  canonical verifier at `18a4336` with 1,352 tests.
- Fresh cumulative and security review confirmed the command, detached-descendant, secure-open,
  and live-digest blockers were closed, then found three adapter/evaluator edge cases: a stale
  `outcome.output` access on failed declarative checks, exponential repeated-globstar regex
  backtracking, and an uncaught NUL-bearing base ref.
- Driver reconciliation removes the stale field, uses a bounded dynamic-programming glob matcher
  with an explicit total-work budget, catches invalid fixed-Git launch arguments, and adds blocking,
  advisory, adversarial-glob, and bad-base regressions.
- B1-A4 wording now matches the documented same-user trust boundary: strict landing recomputes
  live project state and ignores worker-report overrides; it does not claim a new OS privilege
  boundary.
- Next: focused and broad validation, a Review commit/push, then fresh exact-tip cumulative and
  security review.

## Required-check timing-envelope correction: 2026-07-22 EDT

- Exact-tip local verification passed 1,355 tests, and cumulative plus security review were clean
  at `6d9acbc`.
- GitHub Linux 3.10/3.12/3.14 and Socket checks passed. macOS failed twice only in the pre-existing
  Fugu Ultra timeout test: its whole-wrapper elapsed assertion exceeded three seconds by 40.6 ms
  and 7.7 ms while all other 1,354 tests passed.
- Independent diagnosis confirmed production shares one absolute two-second provider process-group
  deadline through synthesis and reaping. The test also times snapshot copying, sandbox setup,
  dependency qualification, startup, and teardown outside that documented deadline.
- The isolated correction gives the whole-wrapper test a four-second loaded-runner envelope, still
  below the fake process's five-second ignored-signal sleep, so failure to SIGKILL/reap remains
  detectable. Production timeout behavior is unchanged.
- Five consecutive focused timeout regressions passed in 10.753 seconds, and the complete
  39-test provider-shortcut module passed in 29.563 seconds.
- The isolated test stabilization is pushed as `3452e72`. Its implementation review is clean;
  review caught only stale recovery wording, corrected by the following run-control refresh.
- Next: complete exact-delta review and required checks at the refreshed tip, then resume
  acceptance close.
