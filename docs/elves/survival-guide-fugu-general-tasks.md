# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

## Mission

Ship general Fugu tasks, explicit Fugu review mode, safe task-appropriate context, and isolated
write handoffs as v2.15.0; review, land by regular merge commit, publish the immutable release, and
draft—but never post—the X announcement.

## Run Control

- **Run mode:** finite
- **Stop policy:** blocker-only through post-merge release follow-through
- **User intent:** plan and stage a new Elves run without prewalk; implement the Fugu task/review distinction, review with Fugu, land and merge the PR, and bump the version
- **Checkpoint due by:** none
- **Checkpoint semantics:** none; ordinary progress is not a stopping point
- **May continue after checkpoint:** yes
- **Actual stop conditions:** merged reviewed PR, verified v2.15.0 release, X draft, and worktree cleanup—or a genuine authority/safety blocker
- **Workspace ownership:** branch `codex/fugu-general-tasks` in dedicated worktree `/Users/john/aigora/dev/elves-fugu-general-tasks`
- **Branch tip at start:** `1d90246b97b5e11211525e71b6a9ff5091c6cc10`
- **Merge policy:** user-authorized regular merge commit; never squash or rebase
- **Final-response policy:** disallowed while the Stop Gate says no
- **Coordination mode:** Cobbler-first staging, one native implementation worker, Fugu terminal review, independent cumulative review
- **Batch completion rule:** meaningful Implement progress precedes the single acceptance-backed Close commit
- **Progress visibility rule:** concrete `[codex/fugu-general-tasks · Batch N/1 · Phase] outcome` subjects
- **Coordinator-to-implementer handoff:** one complete packet at `.elves/runtime/fugu-general-tasks-worker.md`
- **Re-read rule:** after every host-owned commit and push, re-read this survival guide before doing anything else
- **Checkpoint rule:** no checkpoint is configured; commits, pushes, PR creation, and green CI do not permit stopping
- **Continuation rule:** continue automatically while `continuation_guard.stop_allowed` is false
- **E2E mode:** chat-to-land
- **Work driver:** host-native Codex collaboration worker
- **Implementation lane:** fast
- **Delegation scope:** full_run
- **Git mode:** branch_progress
- **Driver monitor mode:** parked-monitor
- **Driver update policy:** sanitized worker status and commits; material wakes only
- **Driver review policy:** one cumulative terminal review plus Fugu review; delta-only re-review after fixes
- **Follow mode:** collaboration worker status and Git history
- **Risk posture:** high
- **Trust mode:** trusted implementation worker; Fugu output remains external evidence
- **Landing outcome:** authorized regular merge
- **Driver merge authorized:** yes, explicitly by the user
- **Worker merge authority:** false
- **High-risk checkpoints:** sandbox widening, host-write evidence export, credential/context policy, exact-tip readiness
- **Re-drive budget:** one substantive re-drive before driver-owned completion
- **Continuation harness:** supervised collaboration worker; prewalk requested and actual mode are off
- **Staging acceptance validation:** complete
- **Staging acceptance command:** `python3 scripts/acceptance_contract.py validate --repo-root . --session .elves-session.json`
- **Terminal landing command:** `python3 scripts/elves_landing_check.py --session .elves-session.json --repo-root .`

## Cobbler Session State

- **Cobbler default:** active for this Elves run
- **Activated by:** the user's Elves chat-to-land request
- **Scope:** planning, routing, evidence synthesis, review, and landing coordination
- **Behavior:** advisory routing and synthesis; host retains canonical memory and authority
- **Persistence:** survival guide, session, plan, execution log, and worker packet
- **Exit phrases:** “Cobbler Mode: off” or natural equivalent

## Stop Gate

- **Planned batches remaining:** 1
- **Stop allowed right now:** no
- **Why:** staging, implementation, review, landing, release, and cleanup remain.
- **Next required action:** validate and commit the staged contract, create the PR, then launch the implementation worker.

## Effort Standard

- Work as hard as you can for the full run.
- Do not be lazy.
- Do not settle for the minimum acceptable change.
- Take the next highest-value action until exact-tip acceptance and post-merge follow-through are complete.

## Forbidden Stop Reasons

- Completing a checkpoint, commit, or push is not a stop reason.
- Creating the PR or obtaining green CI is not a stop reason.
- Receiving a useful worker or Fugu answer is not a stop reason while acceptance remains.
- Reaching a clean batch boundary is not a stop reason before landing and release follow-through.

## Current Phase

- **Status:** staging
- **Active batch:** B1
- **What was just finished:** exact plan/session acceptance validation, preflight, and green baseline proof
- **Single next action:** commit and push the Contract slice, create the draft PR, then launch the implementation worker.

## Active Compute

- No implementation worker or Fugu process is active.

## Next Exact Batch

- **Batch:** B1 — separate general tasks from review and safely widen Fugu capability
- **Scope:** runner grammar/prompts, context selection, isolated write handoff, sandbox proof, docs, and v2.15.0
- **Acceptance criteria:** B1-A1 through B1-A7 in `docs/plans/fugu-general-tasks.md`
- **Risk:** high because optional isolated writes and broader context must not weaken the provider boundary

## Post-Checkpoint Control Loop

- Every completed batch must end with a commit and push.
- After every host-owned commit/push, re-read this survival guide before doing anything else.
- If the Stop Gate still say `Stop allowed right now: no`, continue with the next required action.

## After Any Compaction

- Read the Run Control section and Stop Gate first.
- Then read `.elves-session.json` and honor `continuation_guard`, followed by learnings, plan,
  execution log, `.ai-docs/manifest.md`, and the constitution if present.

## Launch Readiness

- [x] Dedicated branch/worktree and collision tripwire recorded.
- [x] Stop Gate initialized with `Stop allowed right now: no`.
- [x] User merge and release authority recorded; worker/Fugu authority denied.
- [x] Prewalk recorded as off.
- [x] Plan/session/packet acceptance mappings validated.
- [x] Baseline proof green.
- [ ] Contract commit pushed and draft PR created.
