# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

> Survival guide for the omp first-class harness run. Trust this file over chat memory.

---

## Mission

Ship Oh My Pi (`omp`) as an optional Elves parked full-run worker plus a thin provider shortcut,
without making omp a main driver and without weakening Grok/Devin/host-native paths.

## Run Control

- **Run mode:** finite
- **Stop policy:** plan Master Acceptance met or explicit user stop
- **User intent:** use Fugu + host plan/stage an Elves run to make omp a first-class harness citizen
- **Checkpoint due by:** none
- **Checkpoint semantics:** none
- **May continue after checkpoint:** n/a
- **Actual stop conditions:** M-A1..M-A4 green with tests/docs, or user stop / hard blocker
- **Workspace ownership:** dedicated worktree created with
  `./scripts/preflight.sh --create-worktree feat/omp-first-class-harness --base origin/main`
  path: `/Users/john/aigora/dev/elves-omp-first-class-harness`
- **Branch tip at start (collision tripwire):** `f53966679751819993dcb271f6343e3a656f0009`
- **Merge policy:** user-merges (default — never merge without explicit session approval)
- **Final-response policy:** allowed when staged or when finite run completes
- **Coordination mode:** Cobbler-first
- **Batch completion rule:** host-native batches end with update execution log → survival guide → commit → push
- **Progress visibility rule:** concrete commit subjects with batch phase labels
- **Coordinator-to-implementer handoff:** required for any delegated batch; this run implements
  host-native by default (building the adapter is not yet delegated to omp)
- **Worker packet:** `docs/elves/worker-packet-omp-first-class-harness.md` (also `worker_packet_path`)
- **Handoff validation:** v2.8 advisory path
- **Re-read rule:** after every host commit/push, re-read this guide
- **E2E mode:** chat-to-work
- **Work driver:** host-native
- **Implementation lane:** fast
- **Delegation scope:** none (product adds omp as a future work driver for *other* repos)
- **Git mode:** host_only
- **Driver monitor mode:** interactive
- **Driver update policy:** interactive
- **Driver poll policy:** interactive
- **Driver review policy:** final independent review only
- **Follow mode:** n/a (not parked full-run for this implementation)
- **Risk posture:** standard
- **Trust mode:** trusted
- **Landing outcome:** landable_pr
- **Driver merge authorized:** no
- **Worker merge authority:** false
- **CLI naming:** always `omp` / Oh My Pi — never ship user-facing `opm` spelling
- **Fugu planning log (main checkout):**
  `/Users/john/aigora/dev/elves/.elves/runtime/fugu-omp-harness-plan-live-20260809T031111Z.log`
- **Plan path:** `docs/plans/omp-first-class-harness.md`
- **Learnings path:** `docs/elves/learnings-omp-first-class-harness.md`
- **Execution log:** `docs/elves/execution-log-omp-first-class-harness.md`

## Stop Gate

- **Stop allowed right now:** no (implementation incomplete; staging docs committed)
- **continuation_guard.stop_allowed:** false until Master Acceptance or user stop

## Next action

1. Staging is complete (plan Fugu-aligned, acceptance_contract OK).
2. Push staging commit on `feat/omp-first-class-harness` if not yet remote.
3. On user go: implement B1 (adapter) → B2 (full-run) → B3 (auth/isolation) → B4 (docs);
   optional B0 shortcut if included; never start deferred B5/B6.
4. Keep work driver host-native while building the omp adapter.

## Decisions made

- MVP = Phase 1 optional parked full-run worker + Phase 0 thin shortcut in same run.
- Phase 2 host-profile/prewalk and Phase 3 main-driver skill install are follow-on only.
- Session identity = capture from JSON `session.id` (no caller `--session-id`).
- Forbid `--continue` and all `AMBIGUOUS_SESSION_TOKENS`.
- Isolate with `--profile elves-omp-<run>` to avoid `~/.claude/tools` binary import collision.
- Fugu ultra synthesis folded into plan (B0 shortcut optional; B1–B4 ship; B5/B6 deferred).
- Building the adapter itself is **host-native** (do not recurse into “omp implements omp adapter”
  for the first ship unless the user later opts in).

## Deferred hygiene

- (empty)

## Hard stops / blockers

- None yet.
