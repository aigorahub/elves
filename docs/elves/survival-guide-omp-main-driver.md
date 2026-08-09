# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

> Compaction recovery order: survival guide → `.elves-session.json` → learnings → plan →
> execution log → `.ai-docs/manifest.md` → constitution/TODO.

---

## Mission

Ship **Oh My Pi (`omp`) as a fourth supported Elves main driver** so a user can open `omp` and
run Elves with the same host-grade contract as Claude Code, Codex, and Grok Build (stage, ordinary
native launch, exact-session prewalk when qualified, separate native worker, review, landable PR).
Retain Phase 1 `omp-cli` worker and `/omp` shortcut under other hosts. User owns merge
authorization. Target release: **2.26.0** (or next free minor).

Plan: `docs/plans/omp-main-driver.md` (Fugu-revised).  
Fugu review: `docs/elves/fugu-omp-main-driver-plan-review.log`.

---

## Run Control

- **Run mode:** finite
- **Stop policy:** blocker-only (or user stop)
- **User intent:** "sounds good, plan and stage this as an elves run" for omp main-driver work
- **Checkpoint due by:** none
- **Checkpoint semantics:** none
- **May continue after checkpoint:** n/a
- **Actual stop conditions:** Master Acceptance met with proof, or true Hard Stop / user stop
- **Workspace ownership:** dedicated worktree
  `/Users/john/aigora/dev/elves-omp-main-driver` on branch `feat/omp-main-driver`
- **Branch tip at start (collision tripwire):** `74a1267d929a9e06faaafbf41326f66674396d22`
- **Merge policy:** user-merges (default — never merge unless user authorizes later)
- **Final-response policy:** disallowed until stop
- **Coordination mode:** Cobbler-first
- **Batch completion rule:** Host-native: update execution log → survival guide → commit → push
- **Progress visibility rule:** concrete batch subjects; no vague WIP subjects
- **Coordinator-to-implementer handoff:** n/a — host-native (still keep plan acceptance as source of truth)
- **Worker packet:** n/a — host-native
- **Handoff validation:** n/a — host-native
- **Re-read rule:** after every host-owned commit and push, re-read this guide first
- **Checkpoint rule:** n/a
- **E2E mode:** chat-to-work
- **Work driver:** host-native
- **Implementation lane:** fast
- **Delegation scope:** none
- **Git mode:** host_only
- **Driver monitor mode:** interactive
- **Driver update policy:** interactive material updates
- **Driver poll policy:** interactive
- **Driver review policy:** final independent review only
- **Follow mode:** n/a (not parked full-run)
- **Risk posture:** high
- **Trust mode:** trusted
- **Landing outcome:** landable_pr
- **Driver merge authorized:** no
- **Worker merge authority:** false
- **Stable plan IDs:** B0–B5; B#-A#; Master M-A#
- **Acceptance row syntax:** bare or bracketed B#-A# equivalent
- **Staging acceptance validation:** PASS — plan parsed; session id/text mappings match
- **Staging acceptance command:**
  `python3 scripts/acceptance_contract.py validate --repo-root . --session .elves-session.json`
- **High-risk checkpoints:** after B0 path freeze; before B3 installer; before B4 public main-driver claim; before release with launch_ready
- **GitHub push auth route:** host `gh` projection
- **Re-drive budget:** n/a (host-native)
- **Continuation harness:** none
- **Continuation rule:** if work remains and stop conditions unmet, continue without waiting

---

## Cobbler Session State

- **Cobbler-first:** yes (`cobbler.default_for_session: true`)
- **Session default:** plan, risk, and review decisions through Cobbler lenses when non-trivial

---

## Non-negotiables

1. No installer code or public main-driver claim before **B0 path freeze** (installed-binary load probe).
2. Never use omp product `--prewalk` as Elves prewalk.
3. Host token is `omp` only; never resolve `omp-cli` as main host.
4. Exactly one selected provider credential for launches; no ambient multi-key dump.
5. User owns merge authorization; host enforces only.
6. Phase 1 `omp-cli` worker + `/omp` shortcut must remain under Claude/Codex/Grok.
7. Do not claim main-driver parity while `launch_ready=False`.
8. No force push, hard reset, or shared-branch rewrite.

---

## Current position

- **Phase:** staged (launch-ready)
- **Active batch:** B0 — Discovery and qualification evidence
- **Next action:** B0.1 installed discovery + path freeze (Appendix B); then B0.2 transport/isolation canary
- **Blockers:** none at staging
- **PR:** none yet (open when first implementation commits land)

---

## Stop Gate

- **Stop allowed right now:** no
- **Reason:** staged run; B0–B5 and Master Acceptance incomplete
- **continuation_guard.stop_allowed:** false

---

## Deferred hygiene

- None at staging. Bank advisory nits mid-run; drain at terminal.

---

## Decisions made

1. Plan is Fugu-revised `docs/plans/omp-main-driver.md` (not reopening Phase 1 worker design).
2. Work driver host-native for high-risk host/install/prewalk work.
3. Landing: landable_pr only; no merge without later user authorization.
4. Version target 2.26.0 or next free minor at freeze.
5. Worktree: `/Users/john/aigora/dev/elves-omp-main-driver`.

---

## Batch board

| Id | Title | Status |
|----|--------|--------|
| B0 | Discovery + qualification evidence | pending (next) |
| B1 | Host recognition + ordinary native launch | pending |
| B2 | Elves exact-session prewalk | pending |
| B3 | Managed install `--target omp` | pending (after B0.1 freeze) |
| B4 | Policy + docs (four main drivers) | pending |
| B5 | Cumulative proof + release | pending |

---

## Compaction recovery next action

Read this file → session JSON → plan B0 acceptance → run B0.1 installed omp skill-load probe and freeze Appendix B.
