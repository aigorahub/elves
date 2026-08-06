# Execution log: v2.24 prime-agent harvest

## Run Digest

- **Status:** executing (launched 2026-08-05 via `/goal complete the elves run`).
- **Tip at staging:** `5b374fdf8cdfe53f11b724fb6c58f7c858210484`; staging commit `83b895e`.
- **Batches:** 0/8 complete — B0 in progress.
- **Blockers:** none. Environmental constraints: aigorahub push denied (cross-fork PR path);
  `claude` CLI absent → host-native execution fallback.

---

## 2026-08-05 · Launch (driver: Claude Fable 5, host-native)

- Controlling instruction changed: `/goal complete the elves run` — supersedes staging-only.
  Stop Gate → `no`; `continuation_guard.stop_allowed=false`; Current Phase → executing.
- Preflight re-run: green, same 3 explained warnings.
- **Work-driver decision:** `which claude` → not found; `native-worker spec` reachable but the
  worker transport binary is absent ⇒ separate native worker lifecycle **unavailable** in this
  harness. Engaged the pre-recorded **host-native fallback** (survival guide Run Control). Per
  contract this consumes no re-drive budget. This session is now driver + implementer running
  the Core Loop per batch.
- Baseline `verify_repo.py --ci` started (result recorded under B0).

---

## 2026-08-05 · B0 · Close (baseline diagnosis + upstream defect record)

- **Interpreter:** default `python3` is 3.9.6 — below the repo floor. All gates run with
  `~/.local/bin/python3.12` (uv cpython 3.12.13). Near-miss recorded: first baseline verdict was
  read through a pipe (`| tail`) and masked the failure — the repo's own pinned lesson holds.
- **Baseline gates at starting tip:** consistency checker exit 0. `verify_repo.py --ci` exit 1
  with exactly 18 failures, all in `tests/test_cobbler_agents_dispatch.py` external-lane tests.
- **Diagnosis (upstream defect, pre-existing):** `prepare_external_launch` routes every
  command-override lane through the recursive-containment gates; `_require_darwin_recursive_
  containment` and `_require_linux_recursive_containment` both fail closed unconditionally
  (`dispatch_external.py:245-279`, "gate currently fails closed"), so external custom-cli lanes
  can never spawn on any platform at tip v2.23.1 — they skip with
  `external_attempt_skipped_fallback_chain_continues` (probe evidence captured). The 18 tests
  still assert pre-gate behavior (external lanes running). Introduced by upstream commits
  `24bef11` / `3549db0` (codex/delegated-worker-v2-1 hardening); the suite was not reconciled.
  Reproduced identically at staging tip `83b895e` in a throwaway worktree and with the harness
  sandbox disabled — machine-independent, deterministic, not this run's regression.
- **Disposition:** plan B0-A1 amended under B0's label (recorded baseline exception; consistency
  green mandatory; any NEW failure is this run's to fix). Upstream defect queued for the
  terminal report and Scout mode. Full-suite comparisons for later batches use this 18-failure
  baseline.
- **B0 evidence:** worktree/branch per preflight (staging entry); prime-agent
  `c98941a2a5cf40faecf9b4648ac3c304abf48fd3` (MIT) recorded, consult-only; acceptance contract
  validate + sync clean at staging and launch. B0 complete.

---

## 2026-08-05 · B1 · Contract

- **Behaviors:** deterministic worktree fingerprint (content-addressed; mtime-independent;
  `.elves/runtime/` excluded; bounded hashing with over-cap marker; errors degrade to `changed`)
  + futile re-drive guard (record substantive failure → evaluate next candidate → classify
  `redrive_futile:workspace_unchanged` on identical tree + same failure class; charge budget;
  forbid identical relaunch; escalate) exposed as `cobbler_agents.py redrive
  record-failure|evaluate|status`; contract wiring in SKILL.md worker-failure recovery +
  e2e-chat-to-land labor completeness + review-subagent delta note + glossary; consistency pins.
- **Where it lives (decision):** the runtime has no code-level re-drive loop (re-drive budget is
  a docs contract; monitor emits `driver_wake_*` only) — so the mechanism is a deterministic
  driver-facing helper + state under `.elves/runtime/redrive/`, mandated by the contracts, not a
  patch into `full_run.py` internals. Serves full-run and legacy bounded routes identically.
- **Build on:** `confidence_sidecar.py` storage idiom (repo-root + `.elves/runtime/`, atomic
  write, bounded JSONL), house subprocess rules (DEVNULL stdin, explicit timeout), argparse hub.
- **Acceptance mapping:** B1-A1 determinism/exclusions tests; B1-A2 error/over-cap ⇒ changed +
  transient-exempt untouched; B1-A3 guard fixture (futile classification, budget charge, no
  identical relaunch, escalation + events + log snippet); B1-A4 gap-packet delta line mandated in
  contracts + evaluate output provides it; B1-A5 existing suites untouched/green.
- **Blast radius:** new module + new CLI verb + 4 reference docs + SKILL.md paragraph + glossary
  + consistency pins + new test file. No changes to monitor/full_run code paths.
- **Risk:** standard. **Caution:** read-only git plumbing only; no temp files inside the repo.

---

## 2026-08-05 · B1 · Validate + Close

- **Implement slice:** `6a92f0f` (module + `redrive` CLI verbs + 13 tests, all green first run).
- **Docs:** SKILL.md worker-failure-recovery guard paragraph; e2e-chat-to-land labor-completeness
  steps re-ordered around the guard (gap-packet delta line mandatory); review-subagent
  fingerprint-delta triage note; glossary "Futile re-drive" entry; consistency pin group
  `FUTILE_REDRIVE_GUARD_PHRASES` + engine loop.
- **Validation (impact path, py3.12):** consistency checker exit 0 with new pins enforced;
  focused suites `test_check_repo_consistency` + `test_cobbler_agents_cli_storage` +
  `test_worktree_fingerprint` = 103 tests OK; `test_joyful_runs_contract` 9/9 OK (B1-A4:
  behavior policy deliberately unchanged — the guard is driver-side, no new wake triggers).
- **Regression baseline:** dispatch-suite 18 = recorded pre-existing upstream defect (B0 entry);
  no new failures introduced.
- B1 complete.

---

## 2026-08-05 · B2 · Contract

- **Behaviors:** learnings ledger for id-tagged `[L#]` entries in `learnings.md` — typed
  create/update/retire edits (evidence required on create; retire moves under
  `## Retired Learnings` per template semantics), tracked `learnings-history.jsonl` sidecar
  (rows with before/after + reason/evidence/expect/run_id; caps 500 records / 256 KiB; flock +
  atomic writes; cap-full refuses loudly rather than silently dropping), inverse-edit rollback
  with `rollback_of` provenance, marker-fenced bounded digest (≤40 lines × ≤120 chars, id
  order) regenerated only between its markers, optional idempotent `migrate` assigning ids to
  freehand dated bullets under active category headings. Freehand/legacy content byte-preserved;
  edit verbs refuse on id-less files with a migrate hint; re-parse under lock before apply;
  unparseable input refuses without modifying the file.
- **Design source:** prime-agent `/refine` edit-proposal shape (CRUD + before/after snapshots +
  append-only history + inverse rollback), adapted with attribution; Elves keeps markdown as the
  authoritative human-readable surface (project scope prime-agent lacks).
- **Build on:** confidence-store idiom (caps, flock, atomic replace), redrive state idiom (B1),
  argparse hub pattern.
- **Blast radius:** new module + `learnings` CLI verbs + `references/learnings-template.md` +
  SKILL.md orient/document deltas + review-subagent audit rule + glossary + pins + tests. The
  live `docs/elves/learnings.md` is NOT migrated in this batch (legacy mode stays valid).
- **Acceptance mapping:** B2-A1 round-trip; B2-A2 digest bounds/markers/byte-preservation;
  B2-A3 legacy tolerance + migrate hint; B2-A4 re-parse + refuse-don't-destroy; B2-A5 history
  caps/flock parity.
- **Risk:** standard. **Caution:** the ledger never reflows or reorders content it did not edit.

---

## 2026-08-05 · B2 · Validate + Close

- **Implement slice:** `7ff97e7` (module + `learnings` CLI verbs + 12 tests). Tests caught two
  real bugs pre-commit (digest lines re-parsing as duplicate entries; rollback removing the
  digest copy instead of the real entry) and one byte-preservation nuance (empty-section insert
  position) — all fixed root-cause in the module, no test weakening.
- **Docs:** learnings-template §Ledger; SKILL §Skill Memory ledger paragraph; review-subagent
  learnings-audit rule; glossary "Learnings ledger"; `LEARNINGS_LEDGER_PHRASES` pins + engine
  loop.
- **Validation (impact path, py3.12):** consistency exit 0; focused suites
  `test_check_repo_consistency` + `test_learnings_ledger` = 99 tests OK; earlier combined run
  with fingerprint + CLI-storage suites also green.
- **Deliberate scope hold:** the live `docs/elves/learnings.md` stays in legacy mode this batch
  (per contract); migration is the operator's explicit choice later.
- B2 complete.

---

## 2026-08-05 · B3 · Contract + Validate + Close

- **Behaviors:** observed-usage ledger (`usage_ledger.py` + `cobbler_agents.py usage
  aggregate|status|panel`): strict aggregation through `parse_usage_payload` (unknown stays
  literal `unobserved`, never zero), advisory ceiling with observed input+output basis
  (cache-read counters structurally excluded), `usage_ceiling_checkpoint` classification (never
  a stop, never routing input), additive `usage_observed` session block, Session Budget lines,
  escaped bounded report panel. `HostProfile.reports_usage` capability metadata on all four
  rows. Calibration rows gain bounded optional `usage` (old rows tolerated). Docs:
  survival-guide-template Session Budget + Forbidden Stop Reasons line;
  schema-and-acceptance §Observed usage; `USAGE_OBSERVED_PHRASES` pins + engine loop.
- **Implement slice:** `d022d94` (38 tests OK incl. confidence + host-profile regressions).
- **Validation:** consistency exit 0; focused suites incl. `test_native_worker_hardening`
  (launch specs unaffected by the new field) = 125 tests OK. Routing non-influence proven by
  CLI fixture (identical route-worker output with and without a populated usage block).
- **Honesty boundary held:** no quota inference anywhere; #199's `route_on_usage_pressure`
  untouched.
- B3 complete.

---

## 2026-08-05 · Staging (driver: Claude Fable 5, staging-only session)

**What happened:** Plan authored from the 2026-08-05 prime-agent deep-comparison analysis and
staged as a legacy two-call run (user instruction: stage, do not launch).

**Work performed:**

- Plan written and placed at `docs/plans/v2.24-prime-agent-harvest.md` (8 batches B0–B7,
  M-A1–M-A6, locked product decisions 1–7, Non-Negotiables, Test Strategy).
- Dedicated worktree created: `/Users/ruthbrown-ennis/research/dev/elves-v2-24-prime-agent-harvest`,
  branch `feat/v2.24-prime-agent-harvest`, base `upstream/main` =
  `5b374fdf8cdfe53f11b724fb6c58f7c858210484` (v2.23.1). START_TIP recorded as collision tripwire.
- **Base correction (decision):** first worktree was created on `origin/main` per the standard
  recipe and immediately found to be a stale fork tip (`81eb1a1`, "Merge fork main history into
  v2.17.1") — `origin` is `RBrownHOPE/elves`, canonical repo is remote `upstream`
  (`aigorahub/elves`). Wrong-base worktree removed; unpushed empty branch deleted; recreated on
  `upstream/main`. No commits were lost (none existed).
- **Auth/push evidence:** `gh auth status` = `RBrownHOPE`;
  `git push --dry-run upstream …` → **403 denied**;
  `git push --dry-run origin …` → ok (`* [new branch] feat/v2.24-prime-agent-harvest`).
  Recorded consequence: branch pushes to `origin`; PR is cross-fork into `aigorahub/elves`;
  merge requires aigorahub-write auth not present in this session.
- **B0-A2 evidence (upstream reference):** `PrimeIntellect-ai/prime-agent` HEAD at analysis and
  staging time = `c98941a2a5cf40faecf9b4648ac3c304abf48fd3` (shallow clone; consult-only; no
  files copied). The launching worker must re-clone shallow at or pin to this SHA (session
  scratch clones do not persist).
- **Worker route:** `cobbler_agents.py route-worker --host claude --execution-reasoning high
  --review-risk standard --provider auto --prewalk auto` →
  `provider=native transport=claude_code effort=high model=inherit_live_driver_model`
  (recorded in `.elves-session.json` `model_routes`).
- Consolidated coordinator→implementer packet written:
  `docs/elves/worker-packet-v2.24-prime-agent-harvest.md`; path recorded in Run Control and as
  `worker_packet_path`.
- New `.elves-session.json` written (supersedes stale terminal v2.23 session on this branch);
  `acceptance_contract.py validate` + `sync-session --write` run at staging (results appended
  below in this entry).
- `./scripts/preflight.sh` run in the worktree (results appended below).

**Staging gate results (final):**

- `acceptance_contract.py sync-session --write` + `validate` — **OK** after conforming the plan
  to the current parser (canonical `### Batch N [BN]:` headings; explicit
  `**Acceptance criteria:**` sections for B0/B7) and the session to array-shaped
  `batches`/`master_acceptance`.
- `./scripts/preflight.sh` — green; 3 warnings, all explained: (1) no project manifest — true for
  this repo (markdown + stdlib scripts); (2) recommended non-interactive env vars unset — a
  launch-session concern; (3) "6 commits behind origin/main" — `origin` is the stale RBrownHOPE
  fork main; branch is deliberately based on the newer `upstream/main`, so the lag is expected
  and benign (base-choice decision recorded above).
- `validate_survival_guide.py` — **OK** after filling the full current template section/field
  set.
- **Meta-finding for the run (candidate learning):** the staged v2.23 plan
  (`docs/plans/v2.23-remaining-open-issues.md`, `### B# ·` headings) and its session
  (`batches: {}` object) would **fail today's** acceptance validator — the contract tightened
  after that run staged. The v2.24 docs conform to the current machine contract.

**Decisions made:** see survival guide §Decisions made (base correction; cross-fork path; plan
relocation; stale-session supersession + Scout note; route-worker inputs).

**Next:** launch per survival guide §Next action. B0 rows remaining at launch: baseline
`verify_repo.py --ci` green (B0-A1) and staged-session validation already green re-confirmed
(B0-A3); B0-A2 satisfied by the SHA evidence above once the worker re-pins it.
