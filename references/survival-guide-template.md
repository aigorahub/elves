# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART

> This is the Survival Guide. It's the notes the day manager leaves for the night shift. It's your
> persistent memory across context compactions and session restarts. After any compaction event,
> read this file before touching any code. If the information here contradicts what you think you
> remember, trust this file. Your memory is gone; this is not.
>
> Your core pattern is the Ralph Loop: try, check, feed back, repeat. Each batch is a draft
> refined through validation and review. The tests are the watch. You are working overnight with
> no one watching, and the tests are what keep you honest. The user operates on both ends (planning
> and review). You run the loop in the middle. You never merge unless the user sets a merge-on-green preference or explicitly invokes the reviewed-PR landing command.
>
> Assume the user may be offline for the rest of the run. If work remains and the recorded stop
> conditions are not met, continue. Do not wait for acknowledgment after commits, checkpoints, or
> summaries.
>
> Recommended read order after any compaction: survival guide -> `.elves-session.json` ->
> learnings -> plan -> execution log -> `.ai-docs/manifest.md` (if present) -> constitution/TODO.
>
> Helper commands written as `python3 scripts/...` are source-checkout shorthand. From an installed
> Claude Code or Codex skill, invoke them from the active Elves skill root while keeping the target
> repository as the working directory; see `references/runtime-helper-paths.md`.

---

## Mission

[2–3 sentence description of what this run is trying to accomplish. Be specific. E.g.: "Refactor
the authentication layer to use short-lived JWTs with refresh tokens, replacing the current
session-cookie approach. All existing auth tests must pass. The public API surface must not change."]

---

## Run Control

- **Run mode:** [finite | open-ended]
- **Stop policy:** [deadline | explicit-user-stop | blocker-only]
- **User intent:** [copy the exact controlling instruction here, e.g., "I'll be back at 8am" or "Keep going until I stop you."]
- **Checkpoint due by:** [YYYY-MM-DD HH:MM timezone | none]
- **Checkpoint semantics:** [delivery target only | hard stop boundary | none]
- **May continue after checkpoint:** [yes | no]
- **Actual stop conditions:** [one short sentence]
- **Workspace ownership:** [owned branch + main checkout | dedicated worktree created with `./scripts/preflight.sh --create-worktree <branch> --base origin/main`] — never shared with another active agent; use `--dry-run` to inspect first
- **Branch tip at start (collision tripwire):** [`git rev-parse HEAD` recorded at staging; an advance is expected only when the exact registered trusted full-run session advances its assigned feature branch to a descendant of the last observed tip and the supervisor verifies its process fingerprint and protected refs unchanged; every other move is a collision]
- **Merge policy:** The user owns whether Elves may merge: [user-merges (default — you never merge) | merge-commit-on-green (opt-in: regular merge commit after the final readiness review passes, never squash) | reviewed-pr-landing-command / `\land-pr` / `/land-pr` (one-off explicit merge opt-in for the current PR)]
- **Final-response policy:** [allowed | disallowed until stop]
- **Coordination mode:** [Cobbler-first (default) | direct-agent override] — use Cobbler lenses for
  non-trivial planning, contract, risk, debugging, review, and synthesis decisions; use direct
  execution only for simple mechanical tasks or when the survival guide explicitly overrides it
- **Batch completion rule:** Host-native and legacy bounded batches end with `update execution log -> update survival guide -> commit -> push`. During trusted parked full-run, the worker closes internal batches with acceptance evidence plus meaningful feature-branch commits/pushes and bounded events; the host updates canonical run memory once at terminal/safety wake instead of shadowing every batch.
  The pinned guardrail `Every completed batch must end with a commit and push` applies to the host
  on host-native/legacy routes and to worker-internal batches on trusted `branch_progress`; it never
  requires a parked host to shadow worker pushes.
- **Progress visibility rule:** Host-native/legacy routes have the host push meaningful mid-batch
  slices with `[<branch> · Batch N/total · Contract|Implement|Validate|Review|Close] <concrete
  outcome>`. A trusted `branch_progress` full-run worker uses that schema only on its assigned
  feature branch while the host parks.
  Forbid vague subjects (`Updates`, `progress`, `WIP`, bare `fixes`). `Close` requires acceptance
  evidence. A trusted `branch_progress` full-run worker may commit and push only the assigned feature
  branch; protected refs, PR operations, run memory, final review, and merge stay host-owned. An
  `untrusted` lease worker may create only audited detached handoff commits and never owns refs,
  remotes, push, PRs, or run memory. The pinned shorthand `Git/PR ops never dispatch model inference`
  applies to protected refs, PR operations, and merge; trusted assigned-feature-branch commit/push
  is the explicit full-run exception.
- **Coordinator-to-implementer handoff:** Every worker packet carries intent/why, non-obvious
  rationale, Build On targets, owned surfaces, forbidden surfaces, acceptance evidence, failure
  modes/pitfalls, and HEAD/run-doc paths/route-session identity/output format. Incomplete handoffs are
  blocking coordinator defects. The packet also carries the confidence-reporting requirement:
  each batch completion reports confidence (high | medium | low) and unsure areas, if any — an
  empty list is a valid, complete answer; triage signal only, never authority.
- **Worker packet:** [path recorded at staging (also `worker_packet_path` in
  `.elves-session.json`) | n/a — host-native]. For any run that may be delegated, the consolidated
  standalone packet is a staging deliverable; the plan's per-batch handoff blocks are not a
  substitute for it.
- **Handoff validation:** [v2.8 advisory path | explicit-v1 declared in session + packet capsule |
  n/a — host-native]. Explicit-v1 state is a strict cold-handoff contract, never proof of exact-session prewalk continuity; see `references/schema-and-acceptance.md`.
- **Re-read rule:** Immediately after every host-owned commit and push, re-read this survival guide
  before doing anything else. During a trusted `parked_monitor` full-run, worker pushes do not wake
  the host; re-read once on a safety/blocked/terminal wake before cumulative review.
- **Checkpoint rule:** If `Checkpoint semantics` is `delivery target only`, log the checkpoint, push it, and continue immediately. Do not stop at the checkpoint.

- **E2E mode:** [chat-to-work | chat-to-land | legacy-two-call | direct]
- **Work driver:** [host-native | grok-build | devin-cli | untrusted-writer]
- **Implementation lane:** [fast | untrusted]
- **Delegation scope:** [none | batch | full_run]
- **Git mode:** [host_only | branch_progress | detached_lease]
- **Driver monitor mode:** [interactive | parked_monitor | n_a]
- **Driver update policy:** [default sanitized follow stream; no timed driver chat; material wakes
  only | quiet follow opt-out | interactive]
- **Driver poll policy:** [host wait primitive | half stale window, bounded 60–300s | interactive]
- **Driver review policy:** [final independent review only | per-batch]
- **Follow mode:** [default sanitized stream on full-run-await | quiet opt-out]
- **Risk posture:** [low | standard | high] (independent of trust)
- **Trust mode:** [trusted | untrusted]
- **Landing outcome:** [landable_pr | complete_and_merge]
- **Driver merge authorized:** [no | yes via land-pr / run control]
- **Worker merge authority:** false
- **Stable plan IDs:** [batches `B#`; `B0` and `B1` are equally valid starts with no preferred
  convention; batch acceptance `B#-A#`; Master Acceptance `M-A#`; legacy aliases mapped
  deterministically by document order and never renumbered]
- **Acceptance row syntax:** [bare `- [ ] B0-A1: criterion` and bracketed
  `- [ ] [B0-A1] criterion` are equivalent; duplicate ids remain invalid]
- **Batch helper syntax:** [`--batch 0` and `--batch B0` are equivalent; negatives and leading-zero
  aliases are invalid]
- **Staging acceptance validation:** [PASS — plan parsed; session and packet id/text mappings match |
  BLOCKED — targeted syntax or mismatch diagnostic]
- **Staging acceptance command:** [`python3 "$ELVES_SKILL_ROOT/scripts/acceptance_contract.py"
  validate --repo-root . --session <session-path>`; optional explicit `sync-session --write`]
- **High-risk checkpoints:** [list or none]
- **GitHub push auth route:** [host `gh` projection | named GH_TOKEN | named GITHUB_TOKEN | local/file remote | n/a]
- **Re-drive budget:** [N substantive external worker re-drives | n/a] — transient provider
  errors (overload/rate-limit/network) retry the same worker with escalating backoff and never
  consume this budget (see SKILL.md Worker failure recovery)
- **Continuation harness:** [none | /goal | host-native]
- **Continuation rule:** If work remains and `Actual stop conditions` are not met, continue without waiting for user acknowledgment.

---

## Cobbler Session State

> Rewrite this section in place. It records whether an Elves invocation has made Cobbler the default
> posture for the current run. This is durable run state, not ordinary Cobbler Mode chat state.

- **Cobbler default:** [on | off]
- **Activated by:** [Elves invocation | Cobbler Mode | explicit user instruction | survival-guide override]
- **Scope:** [current Elves run | current thread only]
- **Behavior:** [treat follow-up prompts as Cobbler-mediated by default / direct-agent override]
- **Persistence:** [survival guide and `.elves-session.json` | current-thread only]
- **Exit phrases:** ["Cobbler Mode: off", "leave Cobbler Mode", "stop using Cobbler by default"]

For staged or active Elves runs, `Cobbler default` should normally be `on` and `.elves-session.json`
should include `cobbler.default_for_session: true`. One-off Quick Cobbler answers do not need this
section.

---

## Session Budget

- **Started:** [YYYY-MM-DD HH:MM timezone]
- **User returns:** ~[YYYY-MM-DD HH:MM timezone] _("never" if open-ended)_
- **Checkpoint expectation:** [what should exist by the checkpoint or next user return]
- **Time budget:** ~[N] hours _("unlimited" if open-ended)_
- **Average batch time so far:** [Xm] _(update after each batch)_
- **Batches remaining:** [N of M]
- **Observed usage so far:** [totals from `cobbler_agents.py usage status`, or the literal
  `unobserved`] _(observed transport reports only; observed ≠ billed; cache reads excluded from
  ceilings; unknown is never a number)_
- **Usage ceiling (advisory):** [N tokens, or "none"] — crossing is a checkpoint and a
  notification, never a stop and never a routing input

---

## Stop Gate

> Rewrite this section in place. This is the explicit answer to "may I stop now?" Do not infer it.

- **Planned batches remaining:** [N]
- **Stop allowed right now:** [yes | no]
- **Why:** [one short sentence]
- **Next required action:** [one short sentence]

If `Planned batches remaining` is greater than 0, `Stop allowed right now` should normally be
`no`. Silence, clean commits, checkpoints, or green CI do not change that.

---

## Effort Standard

> Rewrite this section in place if the user gives a stronger instruction about pace or effort.

- Work as hard as you can for the full run on **plan acceptance and blockers**. Do not be lazy.
- Maintain the same drive on the last product batch as on the first.
- Do not settle for the minimum acceptable change on the planned path, or for a shallow pass when the next planned task remains.
- When one task is complete, immediately take the next highest-value action from the plan (not a polish detour).
- Hard work does **not** mean mid-run nit perfection, nested full reviews, or re-running a large full suite between ordinary batches. Use impact path mid-run; full suite and deferred hygiene at terminal.

## Deferred hygiene

> Bank advisory nits mid-run; drain at terminal readiness. Blockers are never deferred.

- **Open items:** [none / list: surface — what — why advisory]
- **Last drained:** [never / batch or HEAD]

## Out-of-scope findings

> Worth doing, but the plan does not cover it. Never fix it, never widen the batch, never drop it.
> Search first, then `gh issue create`, then record the URL here and in the terminal report.
> No `gh` or no repository: list them here and say so in the report.

- **Filed this run:** [none / list: `#N <url>` — one line on what and where]
- **Could not file:** [none / list: what and where, plus the reason `gh` was unavailable]

---

## Forbidden Stop Reasons

These are not valid reasons to stop the run while work remains:

- A checkpoint time was reached
- A commit or push succeeded
- CI is green
- A PR exists
- The user is silent or offline
- You wrote a useful summary
- The current batch is complete but later batches remain
- The advisory usage ceiling was crossed (observed-usage ledger: checkpoint and notify, never a
  stop)
- You feel unsure whether to continue
- **The remaining work feels like a lot for one turn.** It is supposed to. The volume of work is the entire reason this run exists. The user set it up precisely so you would carry all of it through unattended. "This is a lot for one turn" is the feeling this run is designed to defeat, not a signal to stop.
- **This feels like a natural place to pause and check in.** There is no one to check in with. A clean batch boundary is the middle of the work, not the end. Go straight to the next batch.

If one of these happens, update the docs, commit, push, re-read this file, and continue.

---

## Memory Surfaces

These files do different jobs. Keep them distinct so the agent does not have to guess where
knowledge belongs.

- **Plan:** authoritative scope, batches, acceptance criteria, and non-negotiables
- **Survival guide:** active run brief, run controls, and next exact batch
- **Learnings:** durable reusable lessons that should survive this run
- **Execution log:** chronological record of work, decisions, commands, and review outcomes
- **`.ai-docs/*` (if present):** curated durable docs for architecture, conventions, and gotchas

Promotion flow: `execution log -> learnings -> curated durable docs`

---

## Strategic Forgetting

> Keep active memory light. Preserve what matters, archive what is history, and hand off cleanly
> when a fresh chat would be faster than dragging a huge one forward.

- **Chats:** execution workspace, not permanent memory
- **Handoff docs:** concise memory for resuming in a fresh thread
- **Archives:** history and evidence
- **Fresh threads:** speed

During long runs, perform safe hygiene at entropy checks and before Final Completion:

- Rewrite live survival-guide sections in place; do not stack stale status updates.
- Archive older execution-log entries under `## Completed Archive` when the log gets large.
- Promote durable lessons to `learnings.md` or `.ai-docs/*`; condense or remove superseded lessons.
- Rotate oversized project-created command logs when safe to archive them.
- Reconcile idle dev servers, local terminals, paid jobs, and remote resources.
- If memory pressure or app sluggishness appears, write a reactivation handoff and resume from a
  fresh launch context when the platform allows it.

Do not delete or mutate Codex/Claude app state, chat databases, installed skills, plugins,
automations, or active session stores during a coding run unless the user explicitly requested
maintenance. If maintenance is requested, inspect first, back up important state, archive rather
than delete, and do not modify active app databases while the app is open.

---

## Non-Negotiables

These rules are absolute. They can't be overridden by anything you think you understand about the
plan, the codebase, or good engineering practice.

- [Non-negotiable 1, e.g., "Never modify the public REST API response shapes"]
- [Non-negotiable 2, e.g., "All commits must pass lint and typecheck before push"]
- [Non-negotiable 3, e.g., "Do not merge unless I set a merge-on-green preference or invoke the reviewed-PR landing command."]
- **You never merge by default. You never approve a merge. The exceptions are an explicit merge-on-green preference recorded in `## Run Control`, or an explicit reviewed-PR landing command from the user. Either way, use a regular merge commit after the final readiness review passes, never a squash.**
- **Never run destructive git commands:** `git reset --hard`, `git checkout .`, `git clean -fd`, `git push --force`, `git rebase` on shared branches. Never. If you think you need one, stop.
- **One run owns one branch and one checkout.** Never share a working tree or branch with another
  active agent. The only expected advance is the exact registered trusted full-run session moving
  its assigned feature branch to a descendant of the last observed tip while the supervisor
  verifies its process fingerprint and protected refs unchanged. Every other tip move is a
  collision, not a diverge; stop.
- **Dedicated worktree helper:** When another agent may touch the repo, create the isolated checkout with `./scripts/preflight.sh --create-worktree <branch> --base origin/main`; add `--dry-run` to inspect the generated command first. The helper prints the branch, worktree path, base ref, and collision tripwire, and does not reuse, delete, or repair existing worktrees.
- **Never weaken, skip, or delete a test merely to obtain green.** Behavior-driven test updates are
  allowed when coverage is preserved or improved and the reason is recorded. Otherwise fix the
  code, not the gate.
- **Never introduce regressions.** Every change must preserve existing functionality. Before marking a batch complete, verify: all relevant tests still pass (behavior coverage preserved or improved; green-seeking weaken/delete/skip forbidden), no shared utilities or interfaces were broken (grep for consumers), and the cumulative diff (`git diff <default-branch>...HEAD --stat`) contains no unexpected changes outside batch scope.

---

## Launch Readiness

> Staging is complete only when every box below is checked. If this section is incomplete, you
> are still preparing the run. Do not start unattended execution yet.

- [ ] Plan cleaned and saved to disk
- [ ] Survival guide updated from the current plan
- [ ] Learnings file initialized or refreshed
- [ ] Execution log initialized with batch breakdown and preflight notes
- [ ] Branch created or confirmed
- [ ] Branch and checkout ownership confirmed (dedicated worktree if other agents may touch the repo); no other agent shares this branch
- [ ] PR opened or existing PR recorded
- [ ] Preflight run and critical failures cleared
- [ ] Run mode, return time, and non-negotiables recorded
- [ ] Stop Gate initialized with `Stop allowed right now: no` unless a real stop condition already applies
- [ ] Single-kickoff continues after staging (legacy two-call only if explicit); launch prompt only for legacy path

---

## Current Phase

> Rewrite this section in place. Do not stack old updates here. Historical state belongs in the
> execution log, not in the live operator brief.
> When a batch finishes, update this file, commit, push, then re-read this file before any other
> action. Do not leave completed batch work sitting uncommitted.

**Status:** [Staging / Launch-ready / In progress / All batches complete / Scout mode / Blocked]

**Active batch:** [Batch N: Name]

**What was just finished:** [One sentence. E.g., "Batch 2 complete: JWT issuance and verification
implemented, all 47 tests pass, PR review clean."]

**Single next action:** [One sentence. E.g., "Start Batch 3: implement refresh token rotation."]

---

## Active Compute

> Include this section whenever the run uses paid compute, remote jobs, dev servers, or any
> resource whose status matters to stop/go decisions. Rewrite it in place.

| Resource | Purpose | Current status | Last verified | Stop / repurpose trigger |
| --- | --- | --- | --- | --- |
| [Pod / job / server] | [Why it exists] | [Running / idle / complete / stopped] | [timestamp] | [When to stop it] |

If not applicable, write: **No active paid or long-running compute.**

---

## Next Exact Batch

> Host-native/legacy routes update this section at the end of every batch. During a healthy trusted
> full-run, the parked host leaves it unchanged while the worker runs internal batches and
> reconciles it once at terminal/safety wake. It is the first thing the host reads after compaction.
> Do not improvise the next move from memory.

**Batch:** [B#: N: Name]

**Scope:**
- [Task 1]
- [Task 2]
- [Task 3]

**Acceptance criteria:**
- [ ] B#-A1: [Criterion 1]
- [ ] [B#-A2] [Criterion 2]

**Risk:** [One sentence describing the highest-risk aspect of this batch]

**Rollback authority:** [host-native/legacy: host-created `bN` ref before this batch | trusted
full-run: host-created `b0` ref before handoff plus worker commit SHAs for internal rollback]

---

## Post-Checkpoint Control Loop

Every host-native/legacy completed batch must end with a host commit and push followed by a re-read
of this guide. During trusted parked full-run, the worker records and pushes internal batch
progress while the host consumes bounded telemetry only: no per-batch host memory edit, commit,
push, or re-read. The host reconciles and re-reads once on safety/blocked/terminal wake. A pushed
checkpoint is proof of progress, not permission to stop.

After every host-owned commit and push—or once after a trusted parked worker wakes the host—answer
these questions before doing anything else:

1. What unfinished batch or task am I starting right now?
2. What paid compute or long-running resources are active right now?
3. What is each active resource doing? If any resource is idle, stale, or ambiguous, shut it down or pause it now.
4. Did the user change stop behavior, checkpoint meaning, priorities, or scope since the survival guide was last rewritten? If yes, rewrite `## Run Control`, `## Current Phase`, `## Stop Gate`, and `## Next Exact Batch` now.
5. Does the Stop Gate still say `Stop allowed right now: no`, or does `.elves-session.json` still say `continuation_guard.stop_allowed: false`? If yes, continue immediately.
6. Am I allowed to stop? If the answer is anything other than a clear hard stop, explicit user stop, or true blocker, continue immediately.

---

## Documentation Triggers

Before closing a batch, explicitly decide which durable docs changed and why:

- **Behavior changed:** update the relevant human-facing docs (`README`, config docs, examples,
  changelog, inline instructions).
- **Architecture shifted:** update `.ai-docs/architecture.md`.
- **New repeatable pattern or policy:** update `.ai-docs/conventions.md`.
- **New trap or hidden dependency:** update `.ai-docs/gotchas.md`.
- **Reusable lesson from the run:** update the learnings file.

If none apply, record that no durable doc updates were needed. Do not leave it implicit.

---

## Process Tuning Triggers

During entropy checks, also look for repeated process friction:

- the same review warning or regression note appearing across batches
- repeated `PENDING-DOCS` findings
- validation getting slower every batch without a clear reason
- recurring recovery confusion that points to stale run-state docs or templates

If a pattern clearly repeats, tighten the loop itself: update the survival guide, a template,
`learnings.md`, or tool configuration, then record the adjustment in the execution log. Keep this
lightweight. Tune the process you're already using; do not invent a new subsystem mid-run.

---

## Memory and Resource Hygiene

Run this lightweight cleanup during entropy checks, after unusually large batches, and before
Final Completion:

- [ ] Survival guide live sections are concise and current
- [ ] Execution log is readable; old completed entries archived in place if large
- [ ] Durable lessons promoted; stale or superseded lessons condensed
- [ ] Oversized project logs rotated or archived if safe
- [ ] Idle dev servers, terminals, paid jobs, and remote resources reconciled
- [ ] Reactivation handoff written if a fresh chat should take over

This is performance hygiene for the active run. It does not include deleting local app data or
editing live Codex/Claude session databases.

---

## Elves Report

- **Generate Elves Report:** yes for substantial finite runs; checkpoint-only if the user asks during
  an open-ended run or before Stop Gate allows final stopping
- **Default path:** `/tmp/elves-report-<repo-slug>-<yyyy-mm-dd>.html`
- **Commit report:** no, unless the user explicitly requests a durable artifact
- **Source of truth:** survival guide, `.elves-session.json`, learnings, plan, execution log, and
  live PR/CI state
- **Required sections:** status, executive summary, problems found, lessons learned, batch timeline,
  validation and review proof, residual risks, human next steps, source links
- **Batch timeline format:** collapsible `<details>` entries, one per batch, so the manager can
  scan the whole night and expand specific work
- **Visual standard:** match this project's visual identity, reuse local brand assets when
  available, and avoid generic AI-dashboard styling
- **Template:** use `references/elves-report-template.html` as a starting point when present
- **Images:** optional only on explicit request; prefer HTML/Markdown for precise audit detail
- **Deliver to the user:** the final step of the run is a fresh Final Readiness Review (`git diff <default-branch>...HEAD`, every PR comment, and every test that makes sense) confirming the branch is green; then surface the report path in the notification and tell the user to read it before reviewing or merging — or, only if they set a merge-on-green preference or invoked the reviewed-PR landing command, land a regular merge commit (never a squash).

The Elves Report is the workers' morning report to their manager. It should answer: what did the
elves do, what problems did they find, what changed, how do we know, what did they learn, what still
worries us, and what should the manager do next?

---

## Acceptance Checks

Before marking any batch complete, verify all of the following:

**Policy:** Green CI + `status: complete` is not landable. Landable is plan Acceptance with proof.

Stable ids are required for new plans: batch `B#`, batch acceptance `B#-A#`, and branch-level
Master Acceptance `M-A#`. `B0` and `B1` are equally valid starts, with no Elves preference. Bare
`- [ ] B0-A1: criterion` and bracketed `- [ ] [B0-A1] criterion` rows are equivalent. Legacy
numeric/unlabelled plans remain compatible by deterministic document-order aliases recorded before
completion; never renumber an established alias. Before worker launch, staging must parse the plan
and require session and packet criteria to match it by id and text, with targeted diagnostics for
bad syntax or mismatches.

- [ ] Staging acceptance validation passed before any worker launch (plan syntax parsed; session
      and packet id/text mappings match)

- [ ] Impact-path validation green mid-run; full suite (or project full gate) green at terminal readiness
- [ ] Deferred hygiene drained or explicitly empty at terminal
- [ ] Plan Acceptance criteria for this batch are met with `B#-A#` evidence (not only "tests green")
- [ ] `.elves-session.json` batch entry has non-empty `acceptance: [{id: "B#-A#", criterion, met: true, evidence}]` before `status: complete`
- [ ] Every `M-A#` Master Acceptance criterion is reconciled with evidence before branch readiness
- [ ] God-file / split batches: LOC/facade/size bars proven; structure/regex locks alone do not complete the batch unless the plan allows characterization-only
- [ ] One batch per close commit (or separate **Validate:** sections per batch id if multi-batch)
- [ ] Gate transcripts saved under Evidence / SCRATCH (below) when that layout is in use
- [ ] PR review performed, all blocking findings resolved
- [ ] Execution log updated with timestamps, commands run, test results, commit SHA
- [ ] Survival guide updated with new Current Phase and Next Exact Batch
- [ ] Stop Gate updated with new remaining-batch count and next required action
- [ ] Active Compute section updated, or explicitly marked as not applicable
- [ ] Memory and Resource Hygiene checked for long runs or large batches
- [ ] Route closeout is correct: host commit/push/re-read for host-native/legacy, or worker
  commit/events/report plus one terminal/safety host reconciliation for trusted full-run
- [ ] Rollback proof matches route: host-created `bN` before a host-native/legacy batch, or one
  host-created `b0` before trusted full-run handoff plus recorded worker commit SHAs
- [ ] Before operational-artifact cleanup, with run docs committed and Git clean, project-native
  broad gates pass and `python3 "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py" --session
  <session-path> --repo-root .` passes
- [ ] Any repository-specific aggregate verifier runs only when the target checkout itself provides
  it; an installed Elves bundle does not depend on repo-only helpers

---

## Evidence / SCRATCH Layout

> Optional but strongly recommended for long runs and for less-disciplined models. Capture gate
> transcripts before flipping a batch to `complete`. Keep this tree gitignored (ephemeral).

```text
[scratch-or-evidence-root]/
  batch-1/
    typecheck   # or typecheck.log / typecheck.txt
    lint
    test
    build
  batch-2/
    typecheck
    lint
    test
    build
```

- **Evidence root:** `[path/to/scratch-or-.elves/evidence | unset]`
- **Required for complete:** when set, each complete batch should have the four gate artifacts above
- **Landing check:** resolve `ELVES_SKILL_ROOT` to the active installed Claude Code or Codex Elves
  bundle, then run `python3 "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py" --session <session-path> --repo-root .`
  with `--evidence-root <path> [--require-evidence-dirs]` when configured. The session's tracked
  `plan_path` is authoritative; an explicit `--plan <plan-path>` is only an equality assertion and
  must match exactly. The repo-relative source-checkout shorthand is for Elves development only.

Do not commit raw gate transcripts into the product PR unless the user asks. They are run evidence,
not product code.

---

## Tool Configuration

> These commands are the ground truth for this project. They take precedence over auto-discovery.
> If a tool isn't configured here, fall back to auto-discovery from SKILL.md.
> Leave a field blank or comment it out if it doesn't apply to this project.

```yaml
# --- Lint ---
# Default (Node.js/npm):
lint: npm run lint --if-present
# Alternatives:
# lint: pnpm lint
# lint: ruff check .
# lint: golangci-lint run
# lint: cargo clippy -- -D warnings
# lint: make lint

# --- Typecheck ---
# Default (Node.js/npm):
typecheck: npm run typecheck --if-present
# Alternatives:
# typecheck: pnpm typecheck
# typecheck: mypy .
# typecheck: go build ./...   # Go's compiler is the type checker
# typecheck: cargo check
# typecheck: make typecheck

# --- Build ---
# Default (Node.js/npm):
build: npm run build --if-present
# Alternatives:
# build: pnpm build
# build: # (Python typically has no explicit build step)
# build: go build ./...
# build: cargo build
# build: make build

# --- Test ---
# Default (Node.js/npm):
test: npm test --if-present
# Alternatives:
# test: pnpm test
# test: pytest
# test: go test ./...
# test: cargo test
# test: make test

# --- E2E (optional; only when the user asked for browser proof) ---
# e2e: npx playwright test
# e2e: pnpm exec playwright test
# e2e: make e2e
# e2e:   # leave blank if not applicable

# --- Smoke test (optional) ---
# Run after deployment/preview to verify the service is up.
# smoke: curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/health
# smoke: curl -s -o /dev/null -w "%{http_code}" https://preview-[branch].example.com
# smoke:   # leave blank if not applicable

# --- Review method ---
# Default: GitHub PR comments (zero config — always available)
review: github-pr-comments
# Opt-in alternatives:
# review: custom-api
# review-api-url: https://review.example.com/api/review
# review-api-header: x-api-key: ${REVIEW_API_KEY}

# --- Public API surface snapshot (optional) ---
# Use this when the project has consumer-facing contracts such as REST/GraphQL schemas, package
# exports, CLI help, webhooks/events, or documented config keys.
# Public API surface snapshots are optional regression evidence; tests, review, and the human-owned constitution still decide behavior.
api-surface-snapshot:
  enabled: auto        # false | auto | true
  required: false      # true only when explicitly opted in for this run
  baseline-path: .elves/api-surface/baseline.json
  current-path: .elves/api-surface/current.json
  diff-path: .elves/api-surface/diff.md
  sources:
    rest: auto
    graphql: auto
    exports: auto
    cli: auto
    events: auto
    config: auto
  policy:
    unavailable-source: warning
    additive-change: info
    intentional-breaking-change: requires-plan-note
    unexpected-breaking-change: blocking
# A missing snapshot source is not blocking unless required: true was explicitly set in the survival guide.
# enabled: false plus required: true is invalid staging config.
# Snapshot artifacts are run artifacts, not product docs; keep .elves/ ignored and do not commit raw snapshots by default.

# --- Notification method ---
# Default: PR comment (zero config — always available)
notification: pr-comment
# Opt-in alternatives:
# notification: slack-webhook      # requires ELVES_SLACK_WEBHOOK env var
# notification: custom-cmd         # requires ELVES_NOTIFY_CMD env var
```

### Math Configuration (optional)

> Use this when the run is mathematical research: preliminary discovery, proof search, source
> audit, paper drafting, or post-draft review. Math is a Cobbler-managed domain workflow. Configure
> role slots, not provider secrets.

```yaml
math-coordination: cobbler-managed-domain-workflow
math-provider-policy: native-first-with-optional-external-routes
math-required-env: []
math-optional-env:
  - OPENROUTER_API_KEY
  - GEMINI_API_KEY
  - ANTHROPIC_API_KEY
  - XAI_API_KEY
  - OPENAI_API_KEY
  - EXA_API_KEY
math-role-models:
  subfield_scout: native-subagent
  cross_field_synthesizer: native-coordinator
  proof_critic: native-subagent
  derivation_checker: native-subagent
  source_auditor: native-subagent
  exposition_editor: native-subagent
  formalization_scout: native-subagent
  evolutionary_search: off
math-optional-tools:
  # - alphaevolve
math-external-route-examples:
  # subfield_scout: openrouter:<model-id>
  # proof_critic: openrouter:<model-id>
  # evolutionary_search: alphaevolve:<task-id>
math-alphaevolve:
  enabled: false
  auth: gcloud-impersonation
  artifact_dir: alphaevolve_runs
  promote_policy: independent-local-replay-only
math-fallback-policy: record-before-switching-provider
math-ledger-dir: docs/math
```

OpenRouter is a useful optional math role preset for broad model diversity, but do not make
`OPENROUTER_API_KEY` required unless the user explicitly sets that requirement for this math run.
Google Cloud AlphaEvolve is an optional evolutionary-search tool for numerical examples and
counterexample signals when a project runner exists (`references/math-alphaevolve.md`); it is never
required and never a proof engine. If provider routes are missing, use host-native subagents or
direct analysis and record the fallback in the model-call ledger.

### Cobbler Coordination Defaults

> Cobbler-first coordination is the default for Elves runs. Quick Cobbler is the one-off answer
> mode: native subagent first, read-only, and stateless. Provider-backed council is optional
> advanced plumbing, not required for normal Cobbler or Council-compatible use.

```yaml
cobbler-enabled: true
cobbler-coordination-default: cobbler-first
cobbler-default-for-elves-runs: true
cobbler-default-mode: quick
cobbler-default-backend: native-subagents
cobbler-primary-invocations:
  claude-code: /cobbler
  codex: "$elves cobbler: <task>"
cobbler-compatibility-aliases:
  - /council
  - /ec
  - /elves-council
  - "$elves council: <task>"
cobbler-default-answer-shape:
  - Recommendation
  - Why this fits
  - Strongest dissent
  - Risks
  - Next move
  - Confidence
cobbler-default-role-count: 3
cobbler-max-role-count: 5
cobbler-quick-read-only: true
cobbler-quick-stateless: true
cobbler-run-logging: existing-elves-memory
cobbler-harness-loop:
  - capability-scan
  - route-and-medium-selection
  - context-packet
  - execute-agents-tools-skills
  - collect-evidence
  - fit-answer
  - present-record
  - reclassify
cobbler-output-mediums:
  - chat-answer
  - file-edit
  - pr-comment
  - execution-log
  - .elves-session.json
  - elves-report
cobbler-context-packet:
  - user-intent
  - mode
  - work-scope
  - relevant-files
  - run-state-pointers
  - available-tools-skills
  - source-freshness
  - constraints
  - forbidden-actions
cobbler-model-routing-policy: native-first
cobbler-provider-backed-fallback: native-subagent-and-note

# Optional provider-backed council diversity. Keep disabled unless the user opts in.
cobbler-provider-backed-enabled: false
cobbler-provider-backed-policy: optional-external-providers
cobbler-provider-backed-required-env: []
cobbler-provider-backed-optional-env:
  - OPENROUTER_API_KEY
  - GEMINI_API_KEY
  - ANTHROPIC_API_KEY
  - XAI_API_KEY
  - OPENAI_API_KEY
cobbler-provider-backed-role-models:
  default: native-subagent
  architect: native-subagent
  skeptic: native-subagent
  implementation_analyst: native-subagent
  tester: native-subagent
  synthesis: native-coordinator
cobbler-provider-backed-role-effort:
  architect: high
  skeptic: high
  tester: medium

# Optional effort values are hints only: low, medium, high, or xhigh when the backend supports them.
#
# Example external route when provider-backed council is explicitly enabled:
# cobbler-provider-backed-role-models:
#   skeptic: "openrouter:<model-id>"
#   fast_sanity: "openrouter:<fast-model-id>"
```

Legacy `council-*` config keys remain compatibility aliases for existing `v1.14.0` setups.

### Full-Run Model Routing (optional)

> Use this only for full Elves runs that should prefer different elves for implementation,
> validation, review, scouting, or synthesis. This is routing metadata, not a guaranteed model
> switch. Native host capability is the default. Missing optional provider access falls back to
> host-native work and is not blocking unless this survival guide explicitly sets `required: true`
> for a phase.

```yaml
model-routing:
  enabled: true
  policy: native-first
  fallback: host-native
  phases:
    implement:
      preference: strongest-host-native
      provider-backed-allowed: false
      required: false
    validate:
      preference: reliable-host-native
      provider-backed-allowed: false
      required: false
    review:
      preference: independent-lens
      provider-backed-allowed: true
      required: false
    scout:
      preference: broad-fast-lens
      provider-backed-allowed: true
      required: false
    synthesize:
      preference: coordinator
      provider-backed-allowed: true
      required: false

# Terse aliases are allowed during staging and should expand to the structured block above.
implement-model: strongest-host-native
validate-model: reliable-host-native
review-model: independent-lens
scout-model: broad-fast-lens
synthesize-model: coordinator

# Record only material route changes in the execution log or `.elves-session.json`:
# Execution Log: Requested route / Actual route / Fallback reason
# JSON keys: requested_route, actual_route, fallback_reason
```

---

## Architectural Boundaries (optional)

> If your project has explicit architectural layers or module boundaries, define them here so the
> agent respects them during implementation. This is especially valuable for larger codebases where
> an agent might inadvertently introduce cross-layer dependencies or violate module ownership.
>
> If your project doesn't have formal boundaries, skip this section entirely.

```yaml
# Example: layered architecture with enforced dependency direction
# layers (dependencies flow downward only):
#   - ui          # Components, pages, views
#   - runtime     # App lifecycle, routing, middleware
#   - service     # Business logic, orchestration
#   - repo        # Data access, API clients
#   - config      # Configuration, environment
#   - types       # Shared types, interfaces, enums
#
# enforcement:
#   - structural-tests: src/__tests__/architecture.test.ts
#   - lint-rule: no-restricted-imports (configured in eslint)
#
# module-ownership:
#   - auth/: "Do not modify without updating the auth integration tests"
#   - billing/: "Non-negotiable: never modify billing logic"
```

---

## Rollback and Safety Rules

1. **Create rollback authority for the selected route:**

   Host-native and legacy bounded execution create a host-owned ref before every batch:
   ```bash
   python3 scripts/cobbler_agents.py implement rollback-ref --json \
     --run-id <run-id> --session-id <exact-session-id> --batch <N> \
     --head <batch-start-head> --push
   ```

   Trusted parked full-run creates exactly one host-owned launch ref before
   `full-run-prepare`/`full-run-launch`:
   ```bash
   python3 scripts/cobbler_agents.py implement rollback-ref --json \
     --run-id <run-id> --session-id <exact-session-id> --batch 0 \
     --head <start-head> --push
   ```

   The host command creates the local
   `refs/elves/rollback/<run-id>/<session-id>/bN-<digest>` ref first, then pushes that exact ref
   without force. Record the returned `ref` in the execution log. While parked, the host creates no
   per-batch refs; worker commit SHAs are internal rollback points. The worker never creates, moves,
   or pushes refs other than its assigned feature branch.
2. **Never force-push** the working branch.
3. **Never rebase** the working branch during a run (it invalidates recorded rollback refs).
4. **Never merge by default.** Not even a fast-forward. The user merges when they return — unless they set a merge-on-green preference or explicitly invoke the reviewed-PR landing command. In either opt-in path, land a regular merge commit (never a squash) only after the final readiness review passes.
5. **If something goes badly wrong**, stop and create a clean recovery branch from the last good
   host rollback ref or audited worker commit SHA instead of rewriting history:
   ```bash
   git checkout -b recovery/from-elves-batch-N <ref-returned-by-rollback-ref>
   git push -u origin HEAD
   ```
   Then document what happened in the execution log and stop. Leave the original branch untouched for later inspection.
6. **Stage specific files.** Never `git add -A` blindly. Know what you're committing.
7. **If the branch tip moves outside the trusted exception**, stop and surface the collision. An
   advance is expected only when the exact registered trusted full-run session advances its
   assigned feature branch to a descendant of the last observed tip and the supervisor verifies
   the process fingerprint and protected refs unchanged. Do not commit on any other move. Prevent
   collisions by owning a dedicated branch and worktree (see `## Run Control`).

---

## Batch Sizing

> Default: what a team of 4 developers would accomplish in a 2-week sprint (~40 person-days).
> Override below if the user specified different sizing in the plan.

```yaml
# Optional override — remove this section to use defaults
# team-size: [N]
# sprint-length: [N weeks]
```

---

## Plan and Log Paths

- **Plan:** `[path/to/plan.md]`
- **Learnings:** `[path/to/learnings.md]`
- **Execution log:** `[path/to/execution-log.md]`
- **Durable docs manifest (optional):** `[.ai-docs/manifest.md]`
- **Architecture doc (optional):** `[.ai-docs/architecture.md]`
- **Conventions doc (optional):** `[.ai-docs/conventions.md]`
- **Gotchas doc (optional):** `[.ai-docs/gotchas.md]`
- **Branch:** `[feat/branch-name]`
- **PR number:** [#N] _(fill in after PR is created)_
- **Plan hash at session start:** `[md5-hash]` _(fill in at session start, used to detect plan edits)_

---

## After Any Compaction

When you restart after a compaction, do these steps in order. No shortcuts.

1. Read this file (survival guide). You are doing this now.
2. **Read the Run Control section and Stop Gate above.** Confirm the run mode, stop policy, checkpoint semantics, actual stop conditions, and whether stopping is currently allowed. If open-ended, you are not allowed to stop on your own. This is the most important thing to recover.
3. Read `.elves-session.json` if it exists. Confirm current batch, PR number, test baseline, and `continuation_guard`.
4. Read the learnings file if one exists.
5. Read the plan. Confirm the overall scope hasn't changed (compare hash if recorded above).
6. Read the execution log. Find the last completed batch and the last **Decisions made** entry.
7. Read `.ai-docs/manifest.md` if it exists and then any linked durable docs that matter to the next batch.
8. Read the Active Compute section if present. Know what live resources exist before making any new plan.
9. Read the `continuation_guard`. If `stop_allowed` is `false`, continue without re-deciding whether the run should end.
10. Identify the first incomplete batch or the single next action (look at Current Phase, Stop Gate, `continuation_guard.next_required_action`, and Next Exact Batch above).
11. Check the clock. How much time budget remains? (If open-ended: unlimited.)
12. Resume immediately. Don't ask for help. Don't redo completed work.

The execution log is your proof of what is done. If something appears in the log as complete, it is
complete. Don't re-implement it.

---

# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART


<!-- v2.3 risk/proof policy pins -->
- thin safety kernel; risk low|standard|high independent of trust trusted|untrusted
- validate once, verify changes, attest final
- impact-selected proof during work; broad proof once at terminal readiness and explicit high-risk checkpoints
- mid-run impact path only; deferred hygiene for advisories; full suite at terminal
- mid-run nonblocking new/unresolved PR feedback; terminal waits for required checks
