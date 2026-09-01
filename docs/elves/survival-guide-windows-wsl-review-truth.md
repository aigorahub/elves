# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

## Run Control

- **Run mode:** finite
- **Stop policy:** stop only after Master Acceptance or a hard blocker
- **User intent:** review PR 270 with Fugu and the host, fix all actionable findings, update docs,
  release version 2.35.0, merge, and publish the matching GitHub release
- **Checkpoint due by:** none
- **Checkpoint semantics:** none
- **May continue after checkpoint:** not applicable
- **Actual stop conditions:** PR 270 is merged, GitHub release v2.35.0 is published, explicit user
  stop, or hard blocker
- **Workspace ownership:** branch `fix/windows-wsl-review-truth` in
  `/Users/john/aigora/dev/elves-windows-wsl-review-truth`
- **Branch tip at start:** `a638c6188452e936f366d8d390b1b133d7454a7e`
- **Merge policy:** driver merge is authorized in this session; use a pinned regular merge commit
- **Final-response policy:** only after finite completion or a hard blocker
- **Batch completion rule:** update evidence, execution log, survival guide, commit, and push
- **Re-read rule:** re-read this guide after every host commit and push
- **Checkpoint rule:** no checkpoint changes the stop policy
- **Continuation rule:** continue while planned work remains and the Stop Gate is closed
- **E2E mode:** chat-to-land
- **Work driver:** host-native
- **Implementation lane:** fast
- **Delegation scope:** Fugu reviewed the plan and the exact PR diff. It made no changes.
- **Git mode:** host_only
- **Driver monitor mode:** interactive
- **Driver update policy:** interactive
- **Driver review policy:** completed Fugu PR review, host verification, revision, and exact-tip
  delta review
- **High-risk checkpoints:** sandbox wording and final exact-tip verification
- **Re-drive budget:** 2 substantive attempts per batch
- **Continuation harness:** survival guide plus session JSON
- **Plan path:** `docs/plans/windows-wsl-review-truth.md`
- **Execution log:** `docs/elves/execution-log-windows-wsl-review-truth.md`

## Cobbler Session State

- **Cobbler default:** on
- **Activated by:** Elves implementation request
- **Scope:** this two-batch run
- **Behavior:** host-native implementation with paid Fugu plan and PR reviews
- **Persistence:** session JSON and run documents
- **Exit phrases:** explicit user stop or completed Master Acceptance

## Stop Gate

- **Planned batches remaining:** 0
- **Stop allowed right now:** no
- **Why:** review fixes, exact-tip proof, merge, and GitHub release remain
- **Next required action:** commit review-tip evidence, attest the evidence tip, then remove
  operational run files
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

- **Status:** validating
- **Active batch:** terminal review
- **What was just finished:** full final-readiness verification passed at `889d353` with 1,653 tests
- **Single next action:** commit this evidence, run the landing check, and attest the evidence tip

## Active Compute

- No provider task remains active.

## Next Exact Batch

- **Batch:** none
- **Scope:** all planned work is complete
- **Acceptance criteria:** B1-A1 through B2-A9 and M-A1 through M-A4 are met
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
- Every required council phase has an implicit minimum of one valid report.
- Docker Desktop utility distributions are not usable Elves hosts.
- A failed WSL query is unknown evidence. It is not proof that no distribution exists.
- The release version remains 2.35.0 because main is 2.34.1 and no 2.35.0 release exists.

## Deferred hygiene

- None.

## Hard stops and blockers

- None.
