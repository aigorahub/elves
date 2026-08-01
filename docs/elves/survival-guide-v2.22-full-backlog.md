# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

## Mission

Resolve every remaining open Linear project **elves** issue in one finite host-native Grok 4.5
high run. Ship **v2.22.0** with Claude/Codex parity, dual review (Fugu + independent agent),
regular merge commit, post-merge version bump, and an X announcement draft in chat only.

## Run Control

- **Run mode:** finite
- **Stop policy:** blocker-only until all in-scope Linear issues resolved
- **User intent:** "plan and stage the run" then execute the full backlog as one long Elves run; stop when all issues are resolved; merge after Fugu and agent review; ensure codex/claude parity, docs/guide/changelog up to date; bump version after merge; write X announcement in chat (same account as last, do not auto-post); Grok 4.5 heavy drives and builds; AIG-238 broaden any-model worker with prewalk/caching; AIG-280 both P3 and P4; AIG-282 build runtime lane supervision; version 2.22.0
- **Checkpoint due by:** none
- **Checkpoint semantics:** none
- **May continue after checkpoint:** yes
- **Actual stop conditions:** All staged Linear issues resolved and Master Acceptance met, or a true Hard Stop blocker recorded here
- **Workspace ownership:** dedicated worktree `/Users/john/aigora/dev/elves-v2-22-full-backlog-resolution` on branch `feat/v2.22-full-backlog-resolution`
- **Branch tip at start (collision tripwire):** 397b9b1c623e96a01d552291211650922f9e2c31
- **Merge policy:** merge-commit-on-green after Fugu review and independent agent review clean (never squash); user authorized in kickoff
- **Final-response policy:** disallowed until stop
- **Coordination mode:** Cobbler-first
- **Batch completion rule:** Host-native batches end with update execution log -> update survival guide -> commit -> push
- **Progress visibility rule:** Meaningful mid-batch slices with concrete subjects; Close requires acceptance evidence
- **Coordinator-to-implementer handoff:** n/a — host-native (driver implements)
- **Worker packet:** n/a — host-native
- **Handoff validation:** n/a — host-native
- **Re-read rule:** Immediately after every host-owned commit and push, re-read this survival guide before anything else
- **Checkpoint rule:** n/a
- **E2E mode:** chat-to-land
- **Work driver:** host-native
- **Implementation lane:** fast
- **Delegation scope:** none
- **Git mode:** host_only
- **Driver monitor mode:** interactive
- **Driver update policy:** material wakes only
- **Driver poll policy:** interactive
- **Driver review policy:** final independent review only (plus Fugu at terminal)
- **Follow mode:** n/a
- **Risk posture:** high
- **Trust mode:** trusted
- **Landing outcome:** complete_and_merge
- **Driver merge authorized:** yes — after Fugu review and independent agent review clean at exact HEAD
- **Worker merge authority:** false
- **Stable plan IDs:** B0–B15; Master M-A1–M-A5
- ****Staging acceptance validation:** PASS — plan parsed; session synced
- **Staging acceptance command:** `python3 scripts/acceptance_contract.py validate --repo-root . --session .elves-session.json`
- **High-risk checkpoints:** after B1, B3, B5–B6; terminal B15
- **GitHub push auth route:** host gh projection
- **Re-drive budget:** n/a
- **Continuation harness:** none
- **Continuation rule:** If work remains and stop conditions are not met, continue without waiting for user acknowledgment

## Cobbler Session State

- **Cobbler default:** on
- **Activated by:** Elves invocation
- **Scope:** current Elves run
- **Behavior:** treat non-trivial decisions as Cobbler-mediated by default
- **Persistence:** survival guide and `.elves-session.json`
- **Exit phrases:** "Cobbler Mode: off"

## Session Budget

- **Started:** 2026-08-01 (local)
- **User returns:** when all issues resolved (finite)
- **Checkpoint expectation:** continuous progress on B0→B15
- **Time budget:** multi-day acceptable; do not stop early for time alone
- **Average batch time so far:** n/a
- **Batches remaining:** 16 of 16 (B0–B15)

## Stop Gate

- **Stop allowed right now:** no
- **Reason:** Staging complete only when validate passes and first implement batch not finished; thereafter stop only when Master Acceptance and all Linear issues are resolved
- **Work remaining:** Full B0–B15 plan
- **continuation_guard.stop_allowed:** false

## Next exact action

1. Finish staging: write session JSON, sync-session, validate acceptance, push branch, open or update PR.
2. Begin B0 acceptance evidence (branch pushed, validate PASS).
3. Continue B1 (AIG-238 any-model handoffs).

## Active plan

- **Path:** `docs/plans/v2.22.0-full-backlog-resolution.md`
- **Active batch:** B0
- **Linear project:** elves (Aigora)
- **Version target:** 2.22.0

## Decisions made

- Finite run; stop when all in-scope Linear issues resolved
- Merge after Fugu + independent agent review
- Claude/Codex parity required; docs/guide/changelog current
- Version 2.22.0 post-merge; X draft in chat only (same account as last)
- Grok 4.5 high host-native drive + implement
- AIG-238 broaden any catalog model + prewalk/caching
- AIG-280 ship P3 and P4
- AIG-282 build runtime lane supervision
- Fugu economy baseline merged into this branch from `feat/fugu-economy-preflight`

## Deferred hygiene

- none yet

## Blockers

- none
