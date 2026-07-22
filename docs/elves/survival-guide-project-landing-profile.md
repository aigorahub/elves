# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

## Mission

Ship and dogfood exact-HEAD project landing profiles as v2.13.0, land the reviewed PR by regular
merge commit, publish the matching GitHub release when appropriate, and return a short X draft
without posting it.

## Run Control

- **Run mode:** finite
- **Stop policy:** blocker-only through post-merge follow-through
- **User intent:** plan with Elves, prewalk, stage, hand Batch 1 to GPT-5.6 high, review, land the PR, and add/execute appropriate GitHub-release plus X-draft rules
- **Checkpoint due by:** the worker's exact-session guide checkpoint before full implementation
- **Checkpoint semantics:** delivery-only; coordinator immediately resumes the same worker with `Continue.`
- **May continue after checkpoint:** yes
- **Actual stop conditions:** merged reviewed PR plus applicable release verification and X draft, or a genuine blocker requiring new authority
- **Workspace ownership:** dedicated worktree `/Users/john/aigora/dev/elves-project-landing-profile`
- **Branch tip at start:** `35449718c173f737a7b0dad209accfe86b55b5a9`
- **Merge policy:** user-authorized regular merge commit; never squash or rebase
- **Final-response policy:** disallowed while the Stop Gate is closed
- **Coordination mode:** Cobbler-first planning; one GPT-5.6-high implementation worker; fresh terminal reviewer
- **Batch completion rule:** update evidence, commit/push meaningful slices, and close only with acceptance proof
- **Progress visibility rule:** `[codex/project-landing-profile · Batch N/1 · Phase] concrete outcome`
- **Coordinator-to-implementer handoff:** packet at `.elves/runtime/project-landing-profile-worker.md`
- **Re-read rule:** immediately after every coordinator-owned commit/push and after compaction
- **E2E mode:** chat-to-land
- **Work driver:** GPT-5.6 high
- **Implementation lane:** standard/high-risk
- **Delegation scope:** full Batch 1 implementation; host retains run memory and landing
- **Git mode:** trusted `branch_progress` on this feature branch only
- **Driver monitor mode:** interactive exact-agent guide then continuation
- **Driver update policy:** concise milestone updates; no hidden authority expansion
- **Driver review policy:** independent cumulative review plus exact final-delta review
- **Risk posture:** high
- **Trust mode:** trusted branch worker, host-owned readiness
- **Landing outcome:** authorized merge plus conditional release follow-through
- **Driver merge authorized:** yes, host only
- **Worker merge authority:** false
- **Staging acceptance validation:** PASS — plan/session validation and staging preflight green
- **High-risk checkpoints:** first meaningful profile edit; authority integration; terminal review
- **Re-drive budget:** consumed by the bounded declarative-only worker correction
- **Continuation harness:** same collaboration worker identity
- **Continuation rule:** send the packet once for the guide phase; after a valid checkpoint send only `Continue.`
- **Checkpoint rule:** the checkpoint is delivery-only; log it and continue while the Stop Gate is closed
- **Prewalk honesty:** the installed Codex native-worker transport is not behaviorally qualified; this run uses an exact same-agent guide-to-execution trajectory without claiming repository transport qualification

## Stop Gate

- **Planned batches remaining:** 1
- **Stop allowed right now:** no
- **Why:** fresh exact-tip review, final acceptance/readiness proof, PR landing, release verification, and X draft remain
- **Next required action:** complete clean exact-delta review and required checks after pushed timing-stabilization commit `3452e72`

## Effort Standard

Do not be lazy. Work as hard as you can through the terminal reviewed tip; do not settle for the
minimum acceptable change. After every proof or review step, take the next highest-value action.
Treat this as a high-risk merge-gate change: prefer small pure functions, exact identities, bounded
I/O, hermetic tests, and explicit authority boundaries. Focused green tests are not enough when the
cumulative landing and installed-bundle contracts remain unproved.

## Forbidden Stop Reasons

- The guide checkpoint was reached while execution remains authorized.
- A commit or push completed while the Stop Gate remains closed.
- Focused tests pass but broad verification or review remains.
- A PR exists but exact-head checks, feedback, or mergeability is unresolved.
- The feature PR merged but the applicable GitHub release check or X draft remains.

## Current Phase

- **Status:** timing-envelope stabilization validated and pushed; exact-delta review/CI in progress
- **Active batch:** B1
- **What was just finished:** five consecutive focused tests and the full 39-test provider-shortcut module passed; test-only stabilization commit `3452e72` is pushed and its implementation review is clean
- **Single next action:** finish review of the run-control-only refresh and wait for required checks, then record acceptance evidence

## Active Compute

No implementation worker is active. The read-only timing reviewer confirmed the production
deadline is unchanged and the pushed test stabilization is correct; only this run-control refresh
remains to attest.

## Next Exact Batch

- **Batch:** B1 — ship and dogfood exact-HEAD project landing profiles
- **Scope:** criteria B1-A1 through B1-A7 in the authoritative plan/session/packet
- **Acceptance criteria:** exact criteria B1-A1 through B1-A7, with host-owned M-A1 through M-A4
- **Risk:** high — exact merge readiness; executable profile checks were removed after adversarial review proved they cannot be safely contained by policy checks

## Post-Checkpoint Control Loop

Validate the worker checkpoint, record it in the execution log, and send exactly `Continue.` to the
same worker. Every completed batch must end with a commit and push. After each host-owned commit and
push, re-read this survival guide before doing anything else. If the Stop Gate still say `Stop allowed right now: no`, take the next required action. After worker handback, reconcile, run
focused/broad proof, perform fresh cumulative review, resolve every actionable item, update exact
evidence, and land only the reviewed exact head. Then execute the declarative post-merge covenant
with host authority.

## After Any Compaction

Read the Run Control section and Stop Gate here first, then `.elves-session.json` and its
`continuation_guard`, `docs/elves/learnings.md`, the plan, execution log, worker packet,
`.ai-docs/manifest.md`, and repository instructions. Resume the single Next Exact Action without
restaging completed work.

## Launch Readiness

- [x] Stop Gate initialized with `Stop allowed right now: no`.
- [x] Dedicated worktree and immutable start head recorded.
- [x] Main checkout's untracked Grok draft preserved.
- [x] User merge/release authority and no-post boundary recorded.
- [x] Plan/session/packet stable identity validates.
- [x] Contract commit pushed and PR #189 created.

## Cobbler Session State

- **Cobbler default:** on
- **Activated by:** the user's explicit Elves run request
- **Scope:** this project-landing-profile run only
- **Behavior:** consolidate plan and packet, delegate the implementation slice, then perform
  independent host review and landing
- **Persistence:** this guide, `.elves-session.json`, the plan, execution log, and packet
- **Exit phrases:** “Cobbler Mode: off”, “leave Cobbler Mode”, or “stop using Cobbler by default”

## Current State

Draft PR #189 contains the declarative-only v2.13.0 implementation on a branch that started exactly
at released `v2.12.0`. Product/security review and the local 1,355-test verifier are clean at
`6d9acbc`. Linux and Socket checks are green. macOS exposed a pre-existing Fugu whole-wrapper timing
assertion that failed twice by at most 40.6 ms even though the production two-second provider
deadline is correctly enforced. The isolated test-only four-second envelope is validated and pushed
as `3452e72`; its new GitHub matrix and the run-control-only delta review are in progress.
Observation, promotion, executable gates, and posting remain future work.

## Next Exact Action

Complete exact-delta review of this run-control-only refresh and wait for required checks after
pushed stabilization `3452e72`. Do not close B1 or attest landing readiness until both are green.

## Recovery Order

1. This guide (Run Control and Stop Gate first)
2. `.elves-session.json`
3. `docs/elves/learnings.md`
4. `docs/plans/project-landing-profile.md`
5. `docs/elves/execution-log-project-landing-profile.md`
6. `.elves/runtime/project-landing-profile-worker.md`
7. `.ai-docs/manifest.md`
