# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

> Compaction recovery order: survival guide → `.elves-session.json` → learnings → plan →
> execution log → `.ai-docs/manifest.md` → constitution/TODO.

---

## Mission

Work the ten open `aigorahub/elves` issues in decreasing order of return. Close the four already
fixed by merged PR #241 with verified evidence. Fix #260, the #242 residual, the #249 closer, and
#258. Attempt #243 if the run stays healthy. Skip #246 (needs a supervised live OS-timer trial) and
the two operator-owned items in #249. End at a landable PR. Do not merge.

Plan: `docs/plans/v2.32-open-issue-harvest.md`.
Target release: **2.32.0**.

---

## Run Control

- **Run mode:** finite
- **Stop policy:** blocker-only (or user stop)
- **User intent:** "plan and stage a finite /elves run that works through the issues you have
  enough information to solve, in decreasing order of ROI"; then Fugu review, terminal review,
  fix blockers, landable PR, no merge, no `/land-pr`
- **Checkpoint due by:** none
- **Checkpoint semantics:** none
- **May continue after checkpoint:** n/a
- **Actual stop conditions:** Master Acceptance met with proof, or true Hard Stop / user stop
- **Workspace ownership:** dedicated worktree
  `/Users/john/aigora/dev/elves-v2-32-open-issue-harvest` on branch
  `feat/v2.32-open-issue-harvest`
- **Branch tip at start (collision tripwire):** `8d2a350f4f291117be10908c5def6b92211400bb`
- **Merge policy:** user-merges — merge is explicitly forbidden this run; `/land-pr` is forbidden
- **Final-response policy:** allowed only at a landable PR with Master Acceptance proven
- **Coordination mode:** Cobbler-first
- **Batch completion rule:** host-native: execution log → survival guide → commit → push
- **Progress visibility rule:** concrete batch subjects; no vague WIP subjects
- **Coordinator-to-implementer handoff:** n/a — host-native
- **Worker packet:** n/a — host-native
- **Handoff validation:** n/a — host-native
- **Re-read rule:** after every host-owned commit and push, re-read this guide first
- **E2E mode:** chat-to-work
- **Work driver:** host-native (Claude Code, Opus 5, high)
- **Implementation lane:** fast
- **Delegation scope:** none
- **Git mode:** host_only
- **Driver monitor mode:** interactive
- **Driver review policy:** Fugu review plus one independent terminal review
- **Follow mode:** n/a (not parked full-run)
- **Risk posture:** high
- **Trust mode:** trusted
- **Landing outcome:** landable_pr
- **Driver merge authorized:** no
- **Worker merge authority:** false
- **Stable plan IDs:** B0–B5; B#-A#; Master M-A#
- **Acceptance row syntax:** bare or bracketed B#-A# equivalent
- **Staging acceptance command:**
  `python3 scripts/acceptance_contract.py validate --repo-root . --session .elves-session.json`
- **High-risk checkpoints:** before B4 (fail-closed qualification gate); at terminal readiness
- **GitHub push auth route:** host `gh` projection
- **Continuation rule:** if work remains and stop conditions are unmet, continue without waiting

---

## Cobbler Session State

- **Cobbler-first:** yes (`cobbler.default_for_session: true`)
- **Session default:** plan, risk, and review decisions through Cobbler lenses when non-trivial

---

## Non-negotiables

1. Never merge. Never run `/land-pr`. The run ends at a landable PR.
2. Leniency added in B1 must never relax an identity, authority, or evidence field, and must never
   fabricate validation evidence from prose.
3. B4 must not make a missing effective-route signal into a qualification failure.
4. Never weaken, delete, or skip a test to obtain green.
5. Do not migrate the live `docs/elves/learnings.md` (#249 item 1 is operator-owned).
6. No force push, hard reset, or shared-branch rewrite.
7. Close a GitHub issue only after verifying its fix in the current `main` tree.

---

## Current position

- **Phase:** staging complete; executing
- **Active batch:** B0
- **Next action:** verify and close #244, #245, #247, #248
- **Blockers:** none at staging
- **PR:** none yet (open after the first implementation commits land)

---

## Stop Gate

- **Stop allowed right now:** no
- **Reason:** staging complete; B0–B4 unstarted
- **continuation_guard.stop_allowed:** false

---

## Deferred hygiene

- None at staging. Bank advisory nits mid-run; drain at terminal readiness.

---

## Decisions made

1. Issue triage verdicts fixed at staging: fix #260, #242 residual, #249 closer, #258; attempt
   #243 last; close #244/#245/#247/#248 as already fixed; skip #246 and #249 items 1 and 3.
2. Work driver is host-native. The work is small, delicate, and spread across fail-closed
   validators — not a good delegation shape.
3. Version target 2.32.0.
4. Worktree `/Users/john/aigora/dev/elves-v2-32-open-issue-harvest`.

---

## Batch board

| Id | Title | Status |
|----|--------|--------|
| B0 | Reconcile the issue ledger against merged PR #241 | pending |
| B1 | Prewalk artifact contracts + lenient bounds (#260) | pending |
| B2 | Terminal-flip events re-read (#242 residual) | pending |
| B3 | Learnings-ledger digest-interior guard (#249 closer) | pending |
| B4 | Observed effective route (#258) | pending |
| B5 | Observed-usage wiring (#243) | pending |

---

## Compaction recovery next action

Read this file → session JSON → plan B0 acceptance → verify the four already-fixed issues against
`main` and close them.
