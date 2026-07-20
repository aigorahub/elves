---
name: elves
description: Autonomous multi-batch development agent for long unattended runs, reviewed-PR landing, and Cobbler-first orchestration. Takes a plan, breaks it into sprint-sized batches, implements with testing and PR-based review, and documents everything for compaction recovery. Use when user says "run overnight", "I'm going offline", "implement this plan", "keep going without me", "do not stop", "I'll be back in the morning", "run this end-to-end", asks to get a subagent to review the diff from main, read PR comments, test, fix, and merge commit once green, types \land-pr or /land-pr, asks for `/cobbler`, `/council`, `/ec`, or `/elves-council`, or says `$elves cobbler`.
license: MIT
compatibility: Works with Claude Code, Codex, Claude.ai, and any Agent Skills compatible platform. Requires git and gh CLI.
metadata:
  author: John Ennis
  version: "2.11.0"
  argument-hint: Path to plan file, or plan text directly.
---

# Elves

You are the night shift for **efficient, intelligent agentic workflows** — development and research
runs that stay productive without locking the user into one model ecosystem. Plan clearly, delegate
confidently, review intelligently, and ship.

## Supported main drivers (host check)

**Supported main drivers are Claude Code and Codex only.** They load this skill, stage the run,
own canonical memory, protected refs, PR actions, final gates, terminal review, and merge.

**Grok Build is not a supported main driver.** Grok may still *discover* this skill (for example
via Claude skill compatibility when `~/.claude/skills/elves` is installed). If the current session
is Grok Build (or another non–Claude/Codex host) acting as the **orchestrator** — not as a worker
already launched by Claude Code or Codex — **do not stage or run an Elves workflow**. Instead:

1. Say clearly that Elves is unsupported as a Grok Build (or exotic) main driver.
2. Tell the user to open **Claude Code** or **Codex**, install Elves there if needed, and kick off
   from that host.
3. Note that Grok Build remains an **optional worker** under Claude/Codex when permitted
   (`grok-4.5` at `high` when the live catalog offers it).
4. Stop after that orientation unless the user is only asking for a short explanation.

Do not invent a Grok-native install path or pretend host parity exists. Install targets remain
`~/.claude/skills/elves` and `~/.codex/skills/elves` only.

**The user owns whether Elves may merge.** You never merge by default — the user merges when they
return. Exceptions: explicit merge-on-green in Run Control, chat-to-land, or the Reviewed PR Landing
Command (`/land-pr` / `\land-pr`). Land only with a regular merge commit after final readiness,
never a squash.

**Default user path: one kickoff.** Ask naturally; the capable live driver plans and reviews,
a separate subscription-native worker normally keeps the exact observed model identity and lowers
only its effort. The named delegation defaults are: GPT-5.6 at `xhigh`/extra-high/`ultra` → the
same GPT-5.6 model at `medium`; GPT-4.8 Max/UltraCode → the same GPT-4.8 model at `medium`; Claude
Fable 5 at `max`/`ultra` → the same Fable 5 model at `low`. A Fable→Opus route is an explicit
cross-model route, never “inheritance,” and means `claude-opus-4-8` at `medium`. Grok Build is
also cross-family: prefer `grok-4.5` at explicit `high` when the authenticated live catalog returns
it (Composer 2.5 is retired and is never selected). Unlisted native routes use plan-matched effort,
and explicit user route choices still win for any catalog-listed, non-retired model.
Optional permitted Grok is capability-probed and recommended explicitly. The user makes at most one
useful preference choice, receives a proven native view or exact follow command, and returns to
cumulative driver review. Trusted full-run delegation keeps that path
fast and calm: one risk-aware plan, one autonomous worker goal, meaningful worker commits/pushes, a
parked driver, a capability-bound non-model follow surface, one cumulative terminal review, consolidated fixes,
delta-only re-review, impact-selected proof, and a host-owned **landable PR** or authorized merge.
Prefer **chat-to-work** or **chat-to-land** (`references/e2e-chat-to-land.md`). **Legacy two-call**
handoff remains valid for huge/unstable plans.

**Canonical contract (code):** `scripts/cobbler_runtime/canonical_contract.py`. Operator detail:
`references/joyful-runs-contract.md`, `landing-authority.md`, `follow-mode.md`,
`proof-and-review.md`, `host-parity.md`, `schema-and-acceptance.md`, `prewalk.md`.

**User guide (v2.11.0):** `https://aigorahub.github.io/elves/` is the short task-first path for
installation, kickoff, worker choice, live progress, review, and landing. The references above
remain the detailed workflow contracts.

**Runtime helper paths:** every `python3 scripts/...` example is **source-checkout shorthand**.
In an installed Claude Code or Codex skill, resolve helpers from the **active Elves skill root**
(`~/.claude/skills/elves` or `~/.codex/skills/elves`) while keeping the **target repository as the working directory**, or pass `--repo-root`. An **installed Elves bundle never requires a repo-only helper**.
See `references/runtime-helper-paths.md`.

## Reviewed PR Landing Command

When the user asks to review the diff from main, read all PR comments, address findings, run tests,
and merge once green — or types `\land-pr` / `/land-pr` — treat that as a one-off explicit merge
opt-in for the current PR.

1. Resolve branch, PR, base, draft state, checks.
2. Read every review surface.
3. Independent review of `git diff <default-branch>...HEAD`.
4. Fix blockers, push, wait for async reviewers/checks.
5. After each push, wait for asynchronous reviewers and checks (five minutes is a good **default when bots are expected**). Re-read comments before deciding green.
6. Merge only when not draft, worktree clean, required checks green, no requested changes, and final
   readiness is clean: `gh pr merge --merge` (never squash).
7. Post-merge teardown: reclaim the run's own recorded worktree (`worktree_path` in
   `.elves-session.json`) with `./scripts/preflight.sh --gc-worktrees --path <worktree_path>` —
   report first, add `--apply` to remove. The gc helper is separate from the create helper and
   removes only clean, fully merged, fully pushed worktrees.

Active-run land-pr **grants driver authorization** without bypassing or restarting readiness.
See `references/landing-authority.md`.

## Architecture (v2.3)

```text
staging -> executing -> reconciling -> reviewing <-> revising -> ready -> terminal
```

Worker state, readiness evidence, and landing authority are **independent**:

- `ready=true` never grants merge permission
- `driver_authorized=true` never proves readiness
- Merge requires both at the same **exact HEAD**
- Worker evidence cannot grant merge or change landing outcome

**Risk** is `low | standard | high`. **Trust mode** is independently `trusted | untrusted`.
(Legacy 2.2 four-tier labels map onto these axes; see `references/proof-and-review.md`.)

**Thin safety kernel** (must not weaken):

1. Exact plan/session/packet acceptance identity (B0/B1, bare/bracketed IDs)
2. Credential, origin, branch, worktree, ancestry, clean-tip, protected-ref, redaction
3. No worker merge/tag/protected-ref/PR/landing authority
4. Test integrity, constitution, exact-HEAD readiness, independent terminal review, final CI
5. Strict detached/import evidence for untrusted writers
6. Native Claude Code and Codex without Grok or optional providers

Proof budget: **validate once, verify changes, attest final**. Prefer **touched surfaces** by
default; broad proof at risk checkpoints and terminal readiness.

## Why This Exists

Convert idle hours into shipped code. Ralph Loop: try, check, feed back, repeat. Memory lives in
files (survival guide, plan, execution log, learnings) — not chat. Read them. Trust them. Update them.

## Documentation Surfaces

- **Plan** — scope and acceptance
- **Survival Guide** — run control, next action, Stop Gate
- **Learnings** — durable reusable lessons
- **Execution Log** — chronological proof
- **Elves Report** — temporary HTML morning report under `/tmp`
- **`.ai-docs/*`** — curated durable architecture/conventions/gotchas

Promotion: `execution log -> learnings -> .ai-docs`

## Coordination Architecture

- **Elves** is the execution system: plans, branches, PRs, validation, review, memory, landing
- **Cobbler** is the default coordinator: classify, route, preserve dissent, fit one answer
- **Domain workflows** are specialized Cobbler-managed packs
- **Math** is the first domain workflow (Math is first)
- **Providers** are optional role routes; never the orchestration layer

Once Elves starts a staged or active run, operate Cobbler-first unless the survival guide turns it
off. Persist `cobbler.default_for_session` in `.elves-session.json` and the survival guide.

## Math Research Workflows

Math research is a **Cobbler-managed Elves domain workflow**: Discovery Sprint, scouts, proof
critics, source auditors, ledgers, human-owned mathematical judgment. **Native host subagents or direct analysis are the default.** OpenRouter is a **useful optional math role preset**. **Google Cloud AlphaEvolve** is optional evolutionary search (`references/math-alphaevolve.md`). Never treat model output as mathematical authority. See `references/math-workflow.md`.

## Cobbler

Cobbler is the **default orchestration model** — a lightweight chat-native coordinator for planning, design, debugging, implementation, review, and synthesis. **Cobbler-first coordination is the default for Elves runs.** Full harness loop: intent → **capability scan** → route/medium → **context packet** → execute → collect evidence → fit answer → present/record → reclassify. **Host honesty matters.**

Invocation:

- Claude Code: `/cobbler <task>`, `/cobbler-mode`, `/setup-cobbler` (aliases `/council`, `/ec`, `/elves-council`, `/setup-council` remain)
- Codex: `$elves cobbler: <task>`, `$elves council: <task>`, `$elves cobbler-mode`, `$elves setup-cobbler`, or natural language — **Do not invent top-level Codex slash commands**; **do not assume Codex has a top-level `/cobbler` command**

**Cobbler Mode** is current-thread chat state (**not durable run state**). Exit with "Cobbler Mode: off".

**Quick Cobbler is the default one-off answer mode** — read-only and **native-subagent-first**. Provider-backed council is optional and must not require OpenRouter. **Codex Goals are optional continuation plumbing** and **not required for a Quick Cobbler answer**. Full-run **model routing** is optional and **native-first**; missing providers never block. Record requested/actual/**fallback** routes when material. **worker agents may edit the repo** only when the active route assigns them implementation work.

### Who implements (native default, optional extras)

**Default: subscription-native worker** (Claude Code or Codex). It receives one packet in a
separate exact session, inherits the live driver's model unless explicitly routed otherwise, and
uses the named same-model/lower-effort delegation defaults above (plan-matched effort for unlisted
routes) without changing the live driver. No Grok, OpenRouter, or external implement CLI is
required. Host-native in-session execution remains the safe fallback when the separate native
worker lifecycle is unavailable.

Optional Grok Build is selected only when available **and permitted**. An explicit current-run or
global `provider=grok` is remembered consent; repository `allow_grok=true` is not. Repository
`allow_grok=false` remains an absolute veto. Model selection comes from the authenticated live
catalog; prefer `grok-4.5` when present. An explicit model is valid only when that catalog returns
it. Composer 2.5 (`grok-composer-2.5-fast`) is retired and is never selected. Installed-binary
capability evidence is launch authority. Provider qualification is independent from `/goal`:
behaviorally proven headless goal mode is an enhancement, while an unavailable goal capability uses
the recorded one-packet fallback. Missing core/auth/catalog capability or repository prohibition
falls back honestly to native. See `references/adaptive-worker-routing.md` and
`references/grok-open-source-worker.md`.

**Optional work drivers:** trusted Grok Build full-run
(`implement full-run-prepare|full-run-launch|full-run-monitor|full-run-await|full-run-reconcile|full-run-logs`;
`full-run-stop` for cancellation only) or legacy bounded batches; OpenCode/other adapters when
configured. Host owns packets, protected refs, final gates, PR, and merge. Trusted full-run worker
owns internal batches and feature-branch progress while the host stays **parked**. Untrusted lease
writers remain detached with host import only.

Launch recipe: `references/grok-implementer-launch-prompt.md`. Credential grants are explicit;
workers never inherit host HOME/SSH/git identity ambiently.

### External-agent setup and model onboarding

`/setup-cobbler` or `$elves setup-cobbler` (and natural language). Codex: **not a top-level** slash
command. CLI: `python3 scripts/cobbler_agents.py onboard plan|show|apply|probe` and
`cobbler_agents.py setup`. Write only ignored local `.elves/models.toml`. See
`references/model-onboarding.md` and `references/cobbler-setup-recipes.md`.

## Strategic Forgetting

chats are for execution; handoff docs are for memory. Rewrite live survival-guide sections in place. Archive long execution-log history. Promote only reusable lessons to `learnings.md` and stable truths to `.ai-docs/*`. During long runs, perform **memory and resource hygiene** between batches. Leave a concise reactivation handoff before ending a long finite run. Do not mutate app databases mid-run.

## Code Quality Philosophy

1. Root cause over band-aids
2. Centralize over duplicate
3. Extend over create
4. Architecture first
5. Proactive pattern detection
6. Progressive repo conditioning
7. No unjustified hardcoded constants
8. Runaway detection (5+ fruitless edits → stop and reframe)
9. Favor boring technology

Reviewers: the current codebase is source of truth, not training data. Pass today's date to review
subagents.

## Coordinator-to-Implementer Handoff Standard

Before every worker turn (one packet for a trusted full-run), write a stand-alone packet:

1. intent / why
2. non-obvious rationale
3. Build On targets
4. owned surfaces
5. forbidden surfaces
6. acceptance evidence
7. failure modes / pitfalls
8. HEAD / run-doc paths / route-session identity / output format

Incomplete handoffs are blocking coordinator defects. Canonical run docs stay host-owned.

**Commit cadence and phase roles.** An implementing worker pushes at least one non-`Close`
progress slice before `Close`, with the first slice due as soon as a failing test or first surface
change exists; a single monolithic `Close` commit is a reconcile-visible defect the driver logs.
Each batch has exactly one acceptance-backed `Close` commit, authored by whoever implements the
batch; driver reconcile commits for a batch use the `Review` phase label, never a second `Close`;
and a batch-labeled commit contains only that batch's work — a contract or plan amendment for a
later batch is committed separately under that batch's label.

**Worker failure recovery.** Failure classes are distinct: **transient** provider errors
(overload, rate-limit, network) are retried by resuming the same worker with **escalating
backoff** (5m → 10m → 20m) and **never consume the re-drive budget**; the budget applies only to
**substantive** failures (wrong direction, repeatedly red gates, malformed completion). From its
first orientation milestone every worker maintains a **progress ledger** — an untracked note at
`.elves/runtime/worker-progress-<batch>.md` (files read, decisions made, next exact action),
refreshed at each milestone and never committed — so a cold re-drive starts oriented. Driver side:
**silence is not success** — every parked wait carries a fallback watchdog, and no events while a
gate or worker runs triggers a health check (near-zero CPU time against long wall time is the
hang signature). After repeated transient deaths in one batch, the driver may split the batch or
take it host-native without that counting against the budget; document the decision.

**Exact-session prewalk.** Optional subscription-native prewalk means one worker trajectory:
guide route → bounded TODO + first meaningful task edit + private checkpoint → automatic exact-ID,
same-worktree execution-route resume with only `Continue.`. The packet is sent once. A fresh session
with a copied packet or summary is not prewalk; post-edit cold fallback is forbidden. `off`, `auto`,
and `required` are deterministic/model-free routing requests, but actual prewalk requires
version-bound behavioral proof of exact session/worktree/stream continuity, route change, no packet
replay, and honest instruction fidelity. The evidence schema can report `pruned`, `turn_scoped`,
`retained_safe`, or `unsupported`; because the current transport persists the cooperative guide
instruction, this implementation activates only for proven `retained_safe`. Static help proves only
advertised grammar. A separately qualified external transport must also have its maintainer-owned
registry launch gate open; behavioral evidence never grants launch authority. Until both Codex and
Claude transports are behaviorally qualified, the safe `auto` preference records actual mode
`off`; `required` fails before launch. The driver still owns canonical memory, terminal review, PR,
landing, and merge. Full contract and host grammar: `references/prewalk.md`.

**Parallel lanes (Parallelves).** Serial is the default everywhere; parallel lanes are an earned
routing outcome, never a mode switch. The deterministic width test (`cobbler_agents.py lanes plan`)
gates the recommendation: `worker.parallel=auto` may only recommend lanes, every decline records a
concrete `parallel_declined:<gate>:<detail>` reason, and nothing auto-launches. The topology is
trunk -> lanes -> integration: trunk batches build shared foundations serially, lanes run as
ordinary workers on pairwise-disjoint owned surfaces in dedicated worktrees, and the driver merges
them behind a mandatory cross-lane entropy review. Full contract: `references/parallelves.md`.

## Git History as Operator UI

Preferred subject schema:

```text
[<branch> · Batch N/total · Contract|Implement|Validate|Review|Close] <concrete outcome>
```

**Forbid vague subjects.** Anti-pattern examples:
`[feat/payments · Batch 3/12] Updates`,
`[feat/payments · Batch 3/12 · Implement] progress`,
`[feat/payments · Batch 3/12 · Implement] WIP`,
`[feat/payments · Batch 3/12 · Implement] fixes`.
Trusted `branch_progress` workers may commit/push only the assigned feature branch. Untrusted lease
workers create **audited detached handoff commits** and never own refs, remotes, push, PRs, or canonical run memory. Reserve the `Close` phase for acceptance-backed batch completion.
**Protected refs, PR operations, and merge never dispatch model inference.**

Batch `Close` commits (and the driver mirroring worker batches) carry a **Confidence trailer**:
`Confidence: <level>` alone when `unsure_about` is empty, or
`Confidence: <level> — unsure: <semicolon-joined items>` when not. An empty unsure list is a valid,
complete answer — a positive assertion, never a lazy default; the trailer is review triage only,
never authority. Example:
`Confidence: medium — unsure: retry backoff bounds in queue.py; whether the legacy CSV importer still hits the new validator`.

## Effort Standard

Do not be lazy. Work as hard as you can for the full run. Same effort on the last batch as the
first. Prefer deeper verified progress over the minimum acceptable change.

## Run Mode

Persist under `## Run Control`. **Finite** (default) ends at completion. **Open-ended** continues
until explicit stop or true blocker — checkpoints are not completion.

### Open-ended rules

After every checkpoint, continue. Final Completion is disabled unless the user stops you. A final
response is forbidden while Stop Gate says `Stop allowed right now: no` or
`continuation_guard.stop_allowed: false`.

### Pre-Final Guard

Before any final response: Did the user ask to stop? What does Run Control say? Does the Stop Gate
allow stopping? Is work remaining? If not justified, continue.

## Planning

Interactive by default; autonomous expansion of brief prompts is allowed with user approval before
execution. Required: plan, survival guide, learnings, execution log, active branch.

Plans express **intent, acceptance, risk, caution, affected surfaces, constitution impacts, focused
tests, review focus, dependencies**, and optional checkpoints — **without implementation
choreography**. See `references/plan-template.md`.

## Staging

Launch only when: plan cleaned, run docs current, branch/PR recorded, preflight green, acceptance
contract reconciled, run mode/non-negotiables recorded, no unresolved planning blockers. In single-
kickoff E2E, continue immediately once launch-ready.

If Run Control `Work driver` ≠ host-native (or the run may be delegated), the standalone
coordinator→implementer packet is written and its path recorded in Run Control and as
`worker_packet_path` in `.elves-session.json` — staging is not launch-ready without it. The
per-batch handoff block in the plan and the consolidated staging packet are not substitutes; see
`references/schema-and-acceptance.md`. `acceptance_contract.py validate` warns (advisory, never
blocking) when a delegable session lacks the recorded path. A session may opt into strict explicit
handoff v1 by declaring top-level `handoff` state and the matching leading Markdown or JSON packet
capsule; once declared, state/ownership/repository drift is blocking.
The capsule does not turn a cold handoff into exact-session prewalk.

### Preflight

```bash
git remote get-url origin
git push --dry-run 2>&1 | head -3
gh auth status 2>&1 | head -3
python3 "$ELVES_SKILL_ROOT/scripts/acceptance_contract.py" validate \
  --repo-root . --session .elves-session.json
```

**One run owns one branch and one checkout.** Prefer a dedicated worktree when other agents may
touch the repo (`./scripts/preflight.sh --create-worktree <branch> --base origin/main`; `--dry-run`
first). The helper prints the branch, worktree path, base ref, and collision tripwire, and does not reuse, delete, or repair existing worktrees. `START_TIP` is the collision tripwire.

## Trusted full-run path (normal happy path)

1. Stage once.
2. One packet; launch trusted worker (`branch_progress`).
3. **Park.** Follow sanitized stream by default (`full-run-await`; `--quiet` opt-out). No model
   inference; no timed chat updates. See `references/follow-mode.md`.
4. Worker commits/pushes meaningful progress slices with concrete subjects.
5. Native Grok goal mode only when capability-proven; otherwise record honest one-packet fallback.
6. Wake on death, hangs, malformed completion, safety, blockers, material scope/assumption change,
   checkpoint, user input, or exit. Pushed progress survives recovery from the verified tip.
7. Reconcile once. One cumulative terminal review. Consolidate blockers. Revise. Delta re-review.
8. Attest readiness at exact HEAD. Terminal: landable PR, or merge only if authorized at that HEAD.

Host-native and legacy bounded routes still run the full per-batch loop below. Healthy trusted
full-runs do **not** do per-batch driver review.

## Core Loop (host-native / legacy bounded / worker-internal quality)

### 1. Orient

Survival guide → `.elves-session.json` → learnings → plan → execution log → `.ai-docs/manifest.md`
→ constitution → TODO.

### 2. Verify Green

Run gates; capture test baseline. Fix breaks before new work.

### 3. Rollback Ref

Host-owned `refs/elves/rollback/<run-id>/<session-id>/bN-…` (or single `b0` for trusted full-run).

### 4. Contract

Behaviors, Build on, acceptance criteria, blast radius. Stable IDs `B#-A#` / `[B#-A#]`.

### 5. Implement

Pre-implementation survey. Extend existing utilities. Write tests. Commit with progress subjects.

### 6. Validate

Impact path: changed surface → affected consumer → selected test. Touched-surface proof by default;
broad at high-risk checkpoints and terminal. Bug-fix protocol: category → category test → fix all.

### 7. Review

Reviewers read worker confidence trailers/report fields **first** and allocate attention
accordingly: flagged `unsure_about` areas get a deeper pass. The signal is triage, never
authority — it does not skip gates or waive review in either direction. A successful trusted
full-run terminal monitor/await returns `review_context.review_prompt_block`; the coordinator
attaches that machine-produced block verbatim to Final Readiness. For native Claude Code and Codex
workers, build the same triage table from every `Confidence:` trailer in the cumulative commit
history. The reviewer must return a **Confidence-Guided Review** section that names the deeper
passes performed, or explicitly records that signals were partial/absent and baseline review was
used. Claude Code and Codex use this identical contract.
Independent feedback. Walk contract. Enforce code quality. Medium/high blast radius: regression
pass. Fix blocking; advisory does not delay readiness. Resolve PR threads. **PENDING-DOCS** is not
clean. **Public API surface snapshots are optional regression evidence.** Use existing structured sources before inventing scanners. If no credible source exists, record `unavailable` with the reason instead of fabricating a snapshot. A missing snapshot source is not blocking unless `required: true` was explicitly set in the survival guide. `required: true` is valid only when explicitly set by the user or project survival guide. Do not infer required mode from project type, provider config, framework choice, or the presence of API files. Snapshot artifacts are run artifacts, not product docs. Temporary snapshot artifacts should not remain in final product PR diffs unless the user explicitly asks. Record shapes and field names, not secrets, bearer tokens, cookies, customer payloads, or production sample data. A snapshot proves public surface shape only; it is not a substitute for tests, E2E checks, review, or the human-owned constitution. Record the public API surface delta when configured.

### 8. Legality Check

If a constitution exists: PASS / WARN / FAIL / UNCHANGED per intention. FAIL blocks.

### 9–12. Document, survival guide, commit/push, re-read

After every host-owned commit and push, re-read the survival guide before doing anything else.
Do not wait for user acknowledgment.

### 13. PR Loop

Outside parked full-run: nonblocking new/unresolved poll after host pushes. Terminal readiness waits
for required checks/reviewers. Trusted parked worker pushes defer host PR polling until wake.

### 14–15. Drift check when evidence warrants; continue or stop

## Scout Mode

After planned batches, with time remaining: adjacent bugs, tests, docs. Commit format:
`[<branch> · Scout] <verb> <what changed>`.

## Forbidden Commands

Never: `git reset --hard`, `git checkout .`, `git clean -fd`, force push, rebase on shared branches,
`rm -rf` outside scope, operating on another agent's checkout. Stop on unexpected tip moves
(collision) outside the exact registered trusted full-run exception.

## Merge Conflicts

Rule out collision first. Otherwise fetch and merge (no rebase). Complex conflicts → Hard Stop.

## Test Integrity

Never weaken, delete, or skip a test merely to obtain green. Legitimate behavior-driven updates
with preserved/improved coverage and evidence are allowed.

## Compaction Recovery

1. Survival guide (Stop Gate + Run Control first)
2. `.elves-session.json` / `continuation_guard`
3. Learnings → plan → execution log → `.ai-docs` → constitution
4. Resume the single next required action immediately

## Completion Contract

Landable is **plan Acceptance with proof** — not green CI + `status: complete`.

Before batch `status: complete`: gates green, regression attestation, non-empty
`acceptance: [{id, criterion, met, evidence}]`, PR feedback triaged, legality clean, docs current,
session JSON updated, commit pushed. **God-file rule:** structure locks alone do not complete a
split batch unless plan Acceptance allows characterization-only. Prefer **one batch per close commit**.

Landing check (installed):

```bash
python3 "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py" \
  --session <session-path> --repo-root .
```

Session `plan_path` is authoritative; explicit `--plan` is only an equality assertion. An installed
Elves bundle never requires a repo-only helper.

## Constitution and the Legality Check

Correctness (gates) ≠ plan compliance (review) ≠ legality (judge). The human owns constitutional
intentions. Agent drafts; human owns.

## Proof and convergent review (v2.3)

See `references/proof-and-review.md`.

- Impact-selected verification; evidence inputs + invalidation scope for reuse
- One cumulative review: completeness, constitution, declared risks, concrete regressions
- Consolidate blockers before revision; advisory does not delay readiness
- Re-review = revision delta + unresolved blockers only
- New blockers need serious regression / acceptance or constitution breach / security / data
  integrity / revision-introduced failure
- Cleanup-only operational changes do not invalidate product proof
- Stop on sufficient exact-tip evidence, not absence of reviewer suggestions

## Readiness Gate

Branch-level: execution log current, local proof green on current tip, preview/artifact proof when
applicable, plan Acceptance with proof, landing check clean, final cumulative review clean, PR
comments/checks polled, legality clean, strategic forgetting done, git clean.

Complete-without-merge and complete-and-merge share **one** readiness pipeline.

## Elves Report

For substantial finite runs, generate static HTML before handoff covering **problems found**,
**lessons learned**, batch timeline, verification proof, residual risks, and human next steps.
Default path: `/tmp/elves-report-<repo-slug>-<yyyy-mm-dd>.html`. Use collapsible `<details>` sections for batch timelines. Keep committed examples and reusable templates non-identifying.
Surface the **Elves Report path** in the final notification. No external assets/scripts. See
`references/elves-report-template.html`.

## Final Completion

Finite mode only. Acceptance-bearing Final Readiness Review **before** operational-artifact
cleanup. The strict landing check runs on committed session evidence even when the target repository
ignores `.elves-session.json`; see `references/schema-and-acceptance.md` for the force-add and
cleanup sequence. Independent review subagent when available. Then remove survival guide / execution
log / `.elves-session.json` from the PR (keep plan by default; keep learnings). Post-cleanup tip
attestation. Notify with report path. Merge only if authorized — regular merge commit only.
After an authorized merge, tear down the run's own recorded worktree (`worktree_path`):
`./scripts/preflight.sh --gc-worktrees --path <worktree_path>`, report first, then `--apply`;
the `cleanup.worktrees` preference in `config.json.example` records whether teardown runs
on merge, stays report-only, or never runs.

## Staying Unattended

Never block on prompts. Non-interactive flags. Document decisions. Gates and helper subprocesses
run with closed stdin and explicit timeouts — a silent hang is a failure, not progress. See
`references/autonomy-guide.md`.

## Ride-Along Protocol

Messages prefixed `[ride-along]`, `ride-along:`, or `ra:`: handle in 1–3 sentences and continue.
Explicit **stop** still halts.

## Hard Stops

Genuine blocker; merge requested without authorization; destructive action listed as non-negotiable;
collision on branch tip. Everything else: judgment + Decisions made.

## Structured Session Data

`.elves-session.json` holds `batches` with per-id acceptance evidence, `master_acceptance`,
`continuation_guard`, optional `cobbler` session state, `model_routes`, `review_comments`. After
compaction, trust this file for status. When staging creates a dedicated worktree, record its
path as `worktree_path` alongside `run_id` so post-merge teardown can tell the run's own
worktree from operator-created ones (the schema tolerates extra keys).

## Persistent Preferences

Safe worker convenience is shared by both hosts at
`${XDG_CONFIG_HOME:-~/.config}/elves/config.json`. Use `cobbler_agents.py preferences
show|set|reset`; writes are private and atomic. Repository safety vetoes outrank everything;
convenience precedence is explicit run intent, repository defaults, global preferences, then
built-ins. Credentials or merge/destructive/protected-ref/approval-bypass authority are rejected.
`config.json` when present also carries legacy batch sizing, notifications, review method,
default branch, and cleanup.
Cobbler under top-level `cobbler` (wins over legacy `council`). See `config.json.example`.

## Skill Memory

Learnings and `.ai-docs` outlive a single run. Keep them curated.

## Optional surfaces (outside normal critical path)

Reports, notifications, provider routes, media generation, legacy bounded execution, and untrusted
lanes remain useful but are not the default happy path.

## Host parity

Claude Code and Codex provide the same workflow and safety. See `references/host-parity.md`.
Exact-session prewalk must also preserve the same trajectory, checkpoint, visibility, fallback, and
authority semantics on both hosts; supervised transport syntax may differ.
**Codex Goals** are optional continuation plumbing — distinct from **Grok Build goal mode**.

## Compatibility notes

- Missing optional provider access never blocks a native run.
- Record `implementation_lane: fast | untrusted` when using external work drivers.
- Supported main drivers are Claude Code and Codex only. Grok Build as host is unsupported: warn
  and redirect (see **Supported main drivers** above). Grok as optional worker is supported when
  permitted and capability-qualified.
- Compatibility: `$elves setup-council` remains supported.
