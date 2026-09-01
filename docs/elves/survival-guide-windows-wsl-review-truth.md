# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

## Run Control

- **Run mode:** finite
- **Stop policy:** stop only after Master Acceptance or a hard blocker
- **User intent:** plan, obtain a Fugu review, then implement truthful review results and Windows
  support through WSL2
- **Checkpoint due by:** none
- **Checkpoint semantics:** none
- **May continue after checkpoint:** not applicable
- **Actual stop conditions:** M-A1 through M-A4 pass, explicit user stop, or hard blocker
- **Workspace ownership:** branch `fix/windows-wsl-review-truth` in
  `/Users/john/aigora/dev/elves-windows-wsl-review-truth`
- **Branch tip at start:** `a638c6188452e936f366d8d390b1b133d7454a7e`
- **Merge policy:** user-merges, no merge without explicit approval in this session
- **Final-response policy:** only after finite completion or a hard blocker
- **Batch completion rule:** update evidence, execution log, survival guide, commit, and push
- **Re-read rule:** re-read this guide after every host commit and push
- **Checkpoint rule:** no checkpoint changes the stop policy
- **Continuation rule:** continue while planned work remains and the Stop Gate is closed
- **E2E mode:** chat-to-work
- **Work driver:** host-native
- **Implementation lane:** fast
- **Delegation scope:** Fugu reviews the plan only and makes no changes
- **Git mode:** host_only
- **Driver monitor mode:** interactive
- **Driver update policy:** interactive
- **Driver review policy:** completed Fugu plan review, then terminal host review
- **High-risk checkpoints:** sandbox wording and final exact-tip verification
- **Re-drive budget:** 2 substantive attempts per batch
- **Continuation harness:** survival guide plus session JSON
- **Plan path:** `docs/plans/windows-wsl-review-truth.md`
- **Execution log:** `docs/elves/execution-log-windows-wsl-review-truth.md`

## Cobbler Session State

- **Cobbler default:** on
- **Activated by:** Elves implementation request
- **Scope:** this two-batch run
- **Behavior:** host-native implementation with one paid Fugu plan review
- **Persistence:** session JSON and run documents
- **Exit phrases:** explicit user stop or completed Master Acceptance

## Stop Gate

- **Planned batches remaining:** 1
- **Stop allowed right now:** no
- **Why:** the exact-tip terminal verifier and close evidence remain
- **Next required action:** commit and push B2 implementation, then run the terminal verifier
- **continuation_guard.stop_allowed:** false

## Effort Standard

- Work as hard as you can on acceptance and blockers.
- Do not stop at the minimum acceptable change.
- Take the next highest-value action on the accepted plan.

## Forbidden Stop Reasons

- A provider route is optional.
- A test needs diagnosis.
- The work needs another bounded implementation pass.
- A checkpoint, commit, or push completed while plan work remains.

## Launch Readiness

- [x] Plan and session acceptance identities match.
- [x] Dedicated branch and worktree exist.
- [x] Preflight passed with advisory notices only.
- [x] Stop Gate initialized with `Stop allowed right now: no`.
- [x] Fugu plan review has completed and findings are reconciled.

## Current Phase

- **Status:** verifying
- **Active batch:** B2
- **What was just finished:** B2 WSL2 checks, diagnostics, documentation, release metadata, and
  focused verification
- **Single next action:** commit and push B2 implementation, then run exact-tip verification

## Active Compute

- No provider task remains active.

## Next Exact Batch

- **Batch:** B2
- **Scope:** Windows through WSL2 checks, diagnostics, documentation, and release metadata
- **Acceptance criteria:** B2-A1 through B2-A9
- **Risk:** standard

## Post-Checkpoint Control Loop

- Every completed batch must end with a commit and push.
- After each commit and push, re-read this survival guide before doing anything else.
- If the Stop Gate still say `Stop allowed right now: no`, continue to the next required action.

## After Any Compaction

1. Read the Run Control section and Stop Gate.
2. Read `.elves-session.json` and its `continuation_guard`.
3. Read the plan, execution log, learnings, and relevant source.
4. Resume the single next action.

## Decisions made

- Windows support means the host and Elves run inside WSL2.
- Native Win32 execution stays outside this run.
- Optional review unavailability is non-successful but non-blocking.
- Council output has three explicit states: success, unavailable, and blocked.
- Only confirmed WSL2 is supported. WSL1 needs conversion before use.
- Local shortcut filesystem-sandbox readiness and external council process-boundary readiness are
  separate facts.

## Deferred hygiene

- None.

## Hard stops and blockers

- None.
