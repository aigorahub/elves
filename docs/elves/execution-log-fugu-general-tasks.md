# Fugu general tasks execution log

## Run digest

- **Last updated:** 2026-07-23 EDT
- **Current phase:** exact-tip landing readiness
- **Active batch:** B1
- **Last completed batch:** B1
- **Next exact action:** commit acceptance evidence, attest the committed exact HEAD, and run the strict landing check
- **Active PR:** #193
- **Elves Report:** `/tmp/elves-report-elves-2026-07-23.html`

## Session setup — 2026-07-23 EDT

- Plan: `docs/plans/fugu-general-tasks.md`
- Survival guide: `docs/elves/survival-guide-fugu-general-tasks.md`
- Learnings: `docs/elves/learnings.md`
- Execution log: `docs/elves/execution-log-fugu-general-tasks.md`
- Worker packet: `.elves/runtime/fugu-general-tasks-worker.md`
- Branch/worktree: `codex/fugu-general-tasks` at
  `/Users/john/aigora/dev/elves-fugu-general-tasks`
- Start/base: `1d90246b97b5e11211525e71b6a9ff5091c6cc10` (`v2.14.1`, `origin/main`)
- Run mode: finite chat-to-land; regular merge and appropriate v2.15.0 GitHub release are
  authorized; X drafting is authorized and posting is not.
- Prewalk: requested `off`, actual `off`.

## Decisions made

- Split provider selection from task type: general Fugu is no longer implicitly review.
- Preserve an explicit opinionated review route.
- Allow general implementation only through a writable disposable workspace and audited handoff;
  Fugu never mutates the real checkout.
- Prefer safe non-ignored worktree context over tracked-only context; immutable exclusions and
  bounded auditing remain kernel/safety responsibilities.
- Use v2.15.0 because this is new public functionality.

## Staging validation — 2026-07-23 EDT

- `acceptance_contract.py sync-session --write` derived exact B1-A1 through B1-A7 and M-A1
  through M-A4 rows; `validate` passed with no issues.
- The survival guide validator passed with every required stop-control field populated.
- Dedicated-worktree preflight passed remote, GitHub auth, push dry-run, branch staleness,
  ownership, acceptance, and sleep-prevention checks; only the expected generic project-detection
  and shell-environment advisories remain.
- Baseline `tests.test_provider_shortcuts` plus `tests.test_dispatch_isolation` passed 96 tests
  with eight expected platform/capability skips.
- Repository consistency and the v2.14.1 release checklist passed at immutable start head
  `1d90246b97b5e11211525e71b6a9ff5091c6cc10`.
- Contract commit `8631491` was pushed and draft PR #193 was created against `main`.

## Batch B1 — implementation and review — 2026-07-23 EDT

- `46b36d3` admitted bounded safe worktree context and `c89bc73` completed the first general-task,
  review-mode, isolated-handoff, documentation, and v2.15.0 implementation.
- Terminal review rejected that Close tip. Review commits `9172470` and `c4d9e27` closed dotenv,
  mode-only handoff, reserved-namespace, exact-include, runtime-bound, parser-bound, macOS
  containment, and portability defects.
- A second exact-tip review found two race categories: the runtime monitor lacked a final
  post-settlement audit, and Ultra reopened provider-controlled output leaves by pathname.
- `4868e35` closes both categories with a descriptor-relative final audit, a bounded host-owned
  Ultra event pipe, and a pinned `O_EXCL`/`O_NOFOLLOW` final-output descriptor.

## Exact-tip proof — `4868e35ce928a3bfeed5db4ce086efffe2c82e02`

- Focused provider/isolation/release proof: 180 tests passed; 9 platform/capability skips.
- Canonical repository verifier: 1,396 tests passed with compile, shell, JSON,
  security/isolation, consistency, public API, release, and installed-bundle proof green.
- GitHub checks: Ubuntu Python 3.10/3.12/3.14, macOS Python 3.12, and both Socket checks green.
- Independent terminal review: no actionable findings; 54 provider tests and 11 adversarial
  security/isolation tests green. The qualified Linux writable route remains CI-covered because
  bwrap is unavailable on this macOS host.
- Fugu final review: `No actionable findings`.
- Real Fugu Ultra compatibility smoke: `ultra-pinned-output-ok`, confirming the shipped launcher
  accepts the pinned final-output transport.
- Project landing profile advisory evaluation: green at the reviewed product tip; public guide,
  release metadata, Codex adapter, and canonical-skill parity checks passed.

## Problems found and lessons learned

- Polling cannot prove recursive descendant absence on macOS. Writable external work now refuses
  before provider launch unless a qualified kernel boundary supplies recursive containment.
- Resource monitors need a final post-settlement audit; periodic polling alone always leaves a
  last-interval race.
- Validating a provider-controlled pathname before reopening it is not sufficient. Host transport
  now pins descriptors and validates the same inode it reads or truncates.
- Safe context breadth and prompt-token economy are separate concerns: Elves can make eligible
  source available while the host and provider decide what is relevant.
