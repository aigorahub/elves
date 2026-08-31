# Kickoff Prompt Template

> **Recommended: one kickoff after conceptual agreement.** The trusted full-run / parked-monitor
> route is optional; the default includes a sanitized non-model follow
> stream (`full-run-await`; `--quiet` opt-out), exact-HEAD readiness independent of merge
> authorization, and impact-selected convergent review. See
> [`joyful-runs-contract.md`](joyful-runs-contract.md) and [`follow-mode.md`](follow-mode.md).
> The default implementation seat is now a separate subscription-native worker chosen from the
> plan's execution reasoning. Ask naturally; Elves shows the recommendation and asks at most one
> preference question. Optional Grok is used only when permitted and capability-qualified. See
> [`adaptive-worker-routing.md`](adaptive-worker-routing.md).
>
> Chat with the main agent (optional multi-planner lenses) until the work is clear, then send
> **Chat-to-work** (landable PR, no merge) or **Chat-to-land** (through merge) — templates at the
> bottom of this file. Design: [`e2e-chat-to-land.md`](e2e-chat-to-land.md).
>
> The agent plans, stages (branch/PR/docs/preflight), and runs batches in that same run. It does not
> stop after staging to wait for a second human message. Merge only if you chose chat-to-land.
>
> **Legacy two-call handoff** (below) is for huge or unstable plans: stage until launch-ready, stop,
> then a short launch prompt. Most historical "elves stopped" failures were incomplete staging —
> single-kickoff E2E puts staging on the agent.
>
> Think of staging as winding the spring: clean the docs, line up the branch and PR, and run
> preflight before implementation. In the recommended single-kickoff path, continue immediately
> once the runway is clear. A fresh launch call belongs only to explicit legacy two-call runs.
>
> **The Daily Briefing.** Block time at the end of your workday (even 30 minutes) to brief your
> agents. Friday afternoons deserve more deliberate treatment: the weekend is roughly 60 hours of
> potential agent runtime. A two-hour planning session on Friday can produce a week's worth of
> output before Monday morning.

---

## Legacy Step 1: Stage-Only Template

> Use this only after explicitly choosing legacy two-call. The goal is to get everything lined up
> and then stop. For normal chat-to-work/chat-to-land, use the E2E templates below; the agent stages
> first and then continues in the same run.

```
Stage this Elves run. Do not start implementing the batches in this call.

**Plan:** [path/to/plan.md]
**Branch:** [feat/branch-name]
**Survival guide:** [path/to/survival-guide.md]  (or: "generate from template")
**Learnings:** [path/to/learnings.md]            (or: "generate from template")
**Execution log:** [path/to/execution-log.md]    (or: "generate from template")

**Your job in this call:**
- Tighten the plan if needed so it can survive compaction without the conversation
- Generate or refresh the survival guide, learnings file, and execution log
- Set `## Run Control` explicitly, including run mode, checkpoint semantics, may-continue-after-checkpoint, actual stop conditions, workspace ownership (owned branch, and dedicated worktree if used), merge policy (default: you never merge; opt-ins: merge-commit-on-green or reviewed-pr-landing-command), and `Active Compute` if relevant
- Set `Coordination mode` to Cobbler-first by default: use independent lenses for non-trivial
  planning, contract, risk, debugging, review, and synthesis decisions, while keeping writes, git,
  PRs, and durable memory in the coordinator unless explicitly delegated
- Add `## Cobbler Session State` to the survival guide and `cobbler.default_for_session: true` to
  `.elves-session.json` so follow-up prompts remain Cobbler-mediated after compaction
- If the plan is mathematical, record math as a Cobbler-managed domain workflow and copy any
  explicit math role/provider preferences into the survival guide without making provider keys
  required by default
- Create or switch to the branch, open or update the PR, and record the PR number
- Claim a dedicated checkout: confirm no other agent is working this branch or working tree. When other agents may touch the repo, create the branch directly in a dedicated git worktree instead of in the main checkout (`./scripts/preflight.sh --create-worktree <branch> --base origin/main`; add `--dry-run` to inspect first), and record the branch tip as a collision tripwire. The helper prints the branch, worktree path, base ref, and collision tripwire and does not reuse, delete, or repair existing worktrees. Record the created worktree path as `worktree_path` in `.elves-session.json`, and expect post-merge teardown of that worktree via the separate gc helper (`./scripts/preflight.sh --gc-worktrees`; report by default, `--apply` removes only clean, fully merged, fully pushed worktrees).
- If the run may be delegated to a separate worker (Run Control `Work driver` ≠ host-native),
  write the standalone coordinator→implementer packet now and record its path in Run Control
  (`Worker packet:`) and as `worker_packet_path` in `.elves-session.json` — staging is not
  launch-ready without it. Worker commits follow SKILL.md's commit cadence and phase roles (at
  least one pushed non-Close progress slice before Close), and worker failures follow SKILL.md's
  Worker failure recovery (transient errors back off and resume without consuming the re-drive
  budget; workers keep an untracked progress ledger under `.elves/runtime/`).
- Configure optional public API surface snapshot behavior if this project has public contract
  surfaces. Default to `api-surface-snapshot.enabled: auto`, keep `required: false` unless I
  explicitly opt in, and keep snapshot artifacts under ignored `.elves/api-surface/`.
- Run preflight and log any warnings or blockers
- Record any durable-doc paths the run should use (`.ai-docs/*`) if the repo keeps them

**Non-negotiables:**
- [Hard rule 1]
- [Hard rule 2]
- [Hard rule 3]

**Stop condition for this call:**
- This is an explicit legacy two-call run: stop only after launch readiness is proven
```

**Example:**

```
Stage this Elves run. Do not start implementing the batches in this call.

**Plan:** docs/plans/auth-refactor.md
**Branch:** feat/jwt-auth
**Survival guide:** docs/elves/survival-guide.md  (generate from template if missing)
**Learnings:** docs/elves/learnings.md            (generate from template if missing)
**Execution log:** docs/elves/execution-log.md    (generate from template if missing)

**Your job in this call:**
- Tighten the plan if needed so it can survive compaction without the conversation
- Generate or refresh the survival guide, learnings file, and execution log
- Set `## Run Control` explicitly, including run mode, checkpoint semantics, may-continue-after-checkpoint, actual stop conditions, workspace ownership (owned branch, and dedicated worktree if used), merge policy (default: you never merge; opt-ins: merge-commit-on-green or reviewed-pr-landing-command), and `Active Compute` if relevant
- Set `Coordination mode` to Cobbler-first by default: use independent lenses for non-trivial
  planning, contract, risk, debugging, review, and synthesis decisions, while keeping writes, git,
  PRs, and durable memory in the coordinator unless explicitly delegated
- Add `## Cobbler Session State` to the survival guide and `cobbler.default_for_session: true` to
  `.elves-session.json` so follow-up prompts remain Cobbler-mediated after compaction
- If the plan is mathematical, record math as a Cobbler-managed domain workflow and copy any
  explicit math role/provider preferences into the survival guide without making provider keys
  required by default
- Create or switch to the branch, open or update the PR, and record the PR number
- Claim a dedicated checkout: confirm no other agent is working this branch or working tree. When other agents may touch the repo, create the branch directly in a dedicated git worktree instead of in the main checkout (`./scripts/preflight.sh --create-worktree <branch> --base origin/main`; add `--dry-run` to inspect first), and record the branch tip as a collision tripwire. The helper prints the branch, worktree path, base ref, and collision tripwire and does not reuse, delete, or repair existing worktrees. Record the created worktree path as `worktree_path` in `.elves-session.json`, and expect post-merge teardown of that worktree via the separate gc helper (`./scripts/preflight.sh --gc-worktrees`; report by default, `--apply` removes only clean, fully merged, fully pushed worktrees).
- If the run may be delegated to a separate worker (Run Control `Work driver` ≠ host-native),
  write the standalone coordinator→implementer packet now and record its path in Run Control
  (`Worker packet:`) and as `worker_packet_path` in `.elves-session.json` — staging is not
  launch-ready without it. Worker commits follow SKILL.md's commit cadence and phase roles (at
  least one pushed non-Close progress slice before Close), and worker failures follow SKILL.md's
  Worker failure recovery (transient errors back off and resume without consuming the re-drive
  budget; workers keep an untracked progress ledger under `.elves/runtime/`).
- Configure optional public API surface snapshot behavior if this project has public contract
  surfaces. Default to `api-surface-snapshot.enabled: auto`, keep `required: false` unless I
  explicitly opt in, and keep snapshot artifacts under ignored `.elves/api-surface/`.
- Run preflight and log any warnings or blockers
- Record any durable-doc paths the run should use (`.ai-docs/*`) if the repo keeps them

**Non-negotiables:**
- Never modify public /api/* response shapes
- All commits must pass lint and typecheck before push
- Do not touch the OAuth routes or password reset flow
- You never merge by default. The PR is for me to review, unless I explicitly opt into merge-on-green or ask for the reviewed-PR landing command.

**Stop condition for this call:**
- This is an explicit legacy two-call run: stop only after launch readiness is proven
```

---

## Legacy Step 2: Hard Launch Template

> In the explicit legacy path, use this in a fresh call after staging is done. Keep it short. The plan already carries the
> project detail; the launch prompt should reinforce behavior and momentum.

```
The run is staged. Start now.
Read [path/to/survival-guide.md] first, then `.elves-session.json` if it exists, then [path/to/learnings.md] if it exists, then [path/to/plan.md], then the execution log at [path/to/execution-log.md], then `.ai-docs/manifest.md` if it exists.
I am going offline until [WHEN].
By [WHEN], I want [CHECKPOINT DELIVERABLE]. This is a [delivery checkpoint / hard stop].
Operate Cobbler-first: use independent lenses for non-trivial planning, contract, risk, debugging, review, and synthesis decisions; keep writes, git, PRs, and durable memory in the coordinator unless explicitly delegated.
Do not stop unless you hit a genuine blocker with no reasonable workaround.
Do not be lazy. Work as hard as you can for the entire run on plan acceptance and blockers.
Do not coast after the first success, first green check, or first useful checkpoint. Push each batch through impact-path proof and blockers, bank advisory nits as deferred hygiene, then continue immediately. Full suite and polish drain at terminal readiness.
If you notice something worth doing that the plan does not cover, do not fix it and do not widen the batch: search existing issues, then `gh issue create`, record the URL in the survival guide under Out-of-scope findings, and continue. Without `gh` or a repository, list it there instead and say so in the report.
If the remaining work feels like a lot for one turn, that is the point: the volume is the reason this run exists, not a reason to stop.
On host-native and legacy bounded routes: Every completed batch must end with a commit and push before you start anything else.
Immediately after every commit and push, re-read the survival guide before any other action. During a healthy
trusted `branch_progress` full-run, the worker commits/pushes its internal batches while the host
stays parked with no per-batch run-memory edit, commit, push, or re-read; reconcile once at a
terminal or safety wake.
If this is a delivery checkpoint, log it, push it, and continue immediately. Do not stop at the checkpoint.
Do not wait for me to acknowledge checkpoints, summaries, or clean commits. If work remains, keep going.
Do not send a final response unless the survival guide Stop Gate says stopping is allowed or a true blocker forces it.
Before any final response, audit the current state against every requirement at the current HEAD — do not rely on intent, partial progress, or memory of earlier work.
Use your judgment. Work in small batches and commit frequently.
Make the commit subjects read like progress reports.
Mid-run: impact-path validation (selected tests / touched E2E). Terminal: full suite or project full gate, then drain deferred hygiene.
After every host-owned or legacy bounded push, read PR comments and checks, fix blockers, and re-check for regressions against earlier verified work. During a healthy trusted full-run, do this once at terminal/safety wake, never once per worker push.
If the run uses paid compute, remote jobs, or long-lived servers, keep the survival guide's `Active Compute` section current after every host-owned push and topology change; use bounded worker telemetry while a trusted full-run remains healthy.
Keep going until the plan is done, I stop you, or you hit a true blocker.
```

**Example:**

```
The run is staged. Start now.
Read docs/elves/survival-guide.md first, then `.elves-session.json` if it exists, then docs/elves/learnings.md if it exists, then docs/plans/auth-refactor.md, then the execution log at docs/elves/execution-log.md, then `.ai-docs/manifest.md` if it exists.
I am going offline until 7:30am ET.
By 7:30am ET, I want a review-ready checkpoint with green local validation. This is a delivery checkpoint, not a stop boundary.
Do not stop unless you hit a genuine blocker with no reasonable workaround.
Do not be lazy. Work as hard as you can for the entire run on plan acceptance and blockers.
Do not coast after the first success, first green check, or first useful checkpoint. Push each batch through impact-path proof and blockers, bank advisory nits as deferred hygiene, then continue immediately. Full suite and polish drain at terminal readiness.
If you notice something worth doing that the plan does not cover, do not fix it and do not widen the batch: search existing issues, then `gh issue create`, record the URL in the survival guide under Out-of-scope findings, and continue. Without `gh` or a repository, list it there instead and say so in the report.
If the remaining work feels like a lot for one turn, that is the point: the volume is the reason this run exists, not a reason to stop.
On host-native and legacy bounded routes: Every completed batch must end with a commit and push before you start anything else.
Immediately after every commit and push, re-read the survival guide before any other action. During a healthy
trusted `branch_progress` full-run, the worker commits/pushes its internal batches while the host
stays parked with no per-batch run-memory edit, commit, push, or re-read; reconcile once at a
terminal or safety wake.
This checkpoint is for delivery only. Log it, push it, and continue immediately. Do not stop at 7:30am ET.
Do not wait for me to acknowledge checkpoints, summaries, or clean commits. If work remains, keep going.
Do not send a final response unless the survival guide Stop Gate says stopping is allowed or a true blocker forces it.
Before any final response, audit the current state against every requirement at the current HEAD — do not rely on intent, partial progress, or memory of earlier work.
Use your judgment. Work in small batches and commit frequently.
Make the commit subjects read like progress reports.
Mid-run: impact-path validation (selected tests / touched E2E). Terminal: full suite or project full gate, then drain deferred hygiene.
After every host-owned or legacy bounded push, read PR comments and checks, fix blockers, and re-check for regressions against earlier verified work. During a healthy trusted full-run, do this once at terminal/safety wake, never once per worker push.
If the run uses paid compute, remote jobs, or long-lived servers, keep the survival guide's `Active Compute` section current after every host-owned push and topology change; use bounded worker telemetry while a trusted full-run remains healthy.
Keep going until the plan is done, I stop you, or you hit a true blocker.
```

---

## Tips

**Use separate calls only for the legacy path**
Staging must still absorb plan cleanup and setup churn, but chat-to-work/chat-to-land continue into
execution in the same run once launch-ready. A fresh launch call is for an explicitly chosen legacy
handoff or a plan that is still too unstable to freeze.

**If you send one E2E kickoff, the agent should stage first and then continue**
A large plan plus “run now” still forbids coding before launch readiness. It does not create a
second human gate: finish staging, then enter the batch loop unless intent or merge policy remains
genuinely ambiguous.

**The agent should push back only on unresolved intent**
Ask for clarification when scope, non-negotiables, or merge authorization cannot be inferred
safely. Do not turn routine internal staging into an unnecessary second user call.

**Don't repeat the whole plan in the launch prompt**
Point to the plan by path. If the launch prompt starts looking like a second plan file, it is too
long.

**Use Codex Goals as a continuation backend when available**
If launching from Codex with Goals enabled, wrap the same launch prompt in `/goal`. Goals keeps
Codex moving; Elves still defines completion through the survival guide Stop Gate and Readiness
Gate. If a goal budget is exhausted before readiness is clean, the agent should write a
reactivation handoff, commit, push, and avoid claiming completion.

**Point to durable memory too**
If the run uses a learnings file or `.ai-docs`, include those paths in the launch prompt so the
agent rehydrates from durable knowledge instead of rediscovering it.

**State checkpoint semantics explicitly**
Don't make the agent guess whether "8am" is a delivery checkpoint or a hard stop. Say which it is.

**Call out paid compute**
If pods, remote jobs, or long-lived servers are involved, tell the agent and require `Active
Compute` updates in the survival guide.

**Make the launch prompt behavior-heavy**
The launch prompt should remind the agent how to behave: don't stop, use judgment, work in small
batches, commit frequently, validate aggressively, review PR feedback, and watch for regressions.

**Keep memory fast**
For long runs, tell the agent to perform memory and resource hygiene during entropy checks: keep
the survival guide concise, archive old execution-log entries in place, promote durable lessons,
stop idle resources, and write a fresh-thread handoff if the active chat or app becomes sluggish.

**Require a final readiness review**
The acceptance-bearing Final Readiness review is mandatory before operational-artifact cleanup. If
the run then commits that narrow cleanup, a strict current-tip attestation is the final gate. Before
the final handoff, the agent should run a fresh cumulative review of `git diff <default-branch>...HEAD`, read
every PR review comment, run every test that makes sense, and confirm checks, docs, and memory
hygiene are clean. Before cleanup, run the target project's broad gates plus
`python3 "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py" --session <session-path> --repo-root .`.
After cleanup, rerun the project-native broad gates on a clean current tip and verify the cleanup
commit removed only the recorded session artifacts. Run a repository-specific aggregate verifier
only when the target checkout itself provides one; installed Elves never depends on a repo-only
helper. Use a review subagent when the platform supports one; otherwise do the review directly. Fix
blockers and repeat until you are confident the branch is green. Then hand the user
the HTML Elves Report and tell them to review it. Stop for the user to merge unless they explicitly
set a merge-on-green preference or asked for the reviewed-PR landing command; in either opt-in path,
perform a regular merge commit (never a squash).

If the user asks for the reviewed-PR landing command, or types `\land-pr` or `/land-pr`, treat that
as a one-off merge opt-in for the current PR, and run the ceremony in order: resolve the PR and read
every review surface; run a **Fugu review of the current PR diff only when needed and authorized**
(the user authorized paid Fugu use in this session and one unresolved high-impact review question
remains; use `/fugu review <scope>` or `$elves fugu review <scope>`, and never invent a raw Fugu call;
otherwise record the skip and its reason); get a fresh
subagent host review of `git diff <default-branch>...HEAD`; fix blockers; update the docs the change
touches and bump the version when the repository versions (Elves itself versions, an unversioned
repository skips the bump); run sensible tests; wait for asynchronous review/CI updates; re-read the
feedback queue; and then use `gh pr merge --merge` only when everything is green. Never squash.

**Check in with `ra:`**
You don't have to disappear completely. If you want to give context or change priorities during
the run, prefix your message with `ra:`. `ride-along:` and `[ride-along]` also work. The agent
will respond briefly and keep going without stopping.

**Friday staging is leverage**
Use Friday afternoon to build a clear plan and make sure preflight is green. In the recommended
single-kickoff path, let the same run continue through the weekend; use a clean second call only
when you deliberately selected legacy two-call.

---

## Chat-to-work (E2E, no merge)

> One kickoff: clarify intent (optionally multi-planner), materialize plan + stage, run all batches
> to a **landable PR**. **Do not merge.** Design: [`e2e-chat-to-land.md`](e2e-chat-to-land.md).
>
> Internally still stage-then-execute (docs/PR before coding). User may send one message.

```
Elves E2E: chat-to-work (no merge).

**Intent / brief:**
[What I want built or researched. Constraints, non-negotiables, deadline if any.]

**Repo / branch preference:** [auto or feat/…]
**Work driver:** [host-native | grok-build | opencode-cli | …]
**Delegation scope:** [none | batch | full_run]
**Multi-planner:** [optional host Cobbler only | also use available plan/review lenses]

**Your job (one continuous run after planning is solid):**
1. Chat only as needed to sharpen intent. Optionally route independent planners (Cobbler / available
   lenses). Reach conceptual agreement; synthesize one plan on disk.
2. Stage fully (you own staging quality): survival guide, learnings, execution log, branch, PR,
   preflight, Cobbler session state. Set Run Control: `e2e mode: chat-to-work`,
   `merge policy: never-merge`, labor re-drive budget 3. Treat `B0` and `B1` as equally valid
   batch starts and accept both bare `- [ ] B0-A1: …` and bracketed `- [ ] [B0-A1] …` stable-id
   rows. Before any worker launch, parse the authoritative plan with targeted syntax errors and
   require session and packet acceptance ids/text to match it using the installed
   `acceptance_contract.py validate` helper; use explicit `sync-session --write` when deriving
   pending session rows from the plan is useful.
3. **Do not stop for a second human “launch” message.** For host-native or bounded delegation,
   execute the ordinary per-batch loop. If `work driver: grok-build` and `delegation scope:
   full_run`, create the host-owned run/session `b0` rollback ref at the launch head before the
   packet/launch, write one complete packet, launch one exact persistent session, then park on
   bounded telemetry; do not re-enter per-batch implementation/review/PR chatter while the worker
   commits and pushes. Wake only for safety/blocked/terminal events or explicit user input.
4. Check labor completeness after each bounded return, or once at trusted full-run wake/exit. If
   incomplete: gap-packet + exact-session re-drive up to budget; then host finish or hard-stop.
   Never mark partial labor complete or turn a healthy full-run into per-batch prompting.
5. Run Final Readiness / Readiness Gate. Leave a landable PR for me. Generate Elves Report if the
   run is substantial.

**Continuation:** Prefer `/goal` (Codex) or host long-run continuation with the same rules once
staging is launch-ready. Goal/memory authority is the survival guide Stop Gate + Readiness Gate.

**Hard rules:**
- You never merge.
- Supported main driver is this host (Claude Code or Codex). Optional tools never required.
- Do not stop unless Stop Gate allows it, I stop you, or a true blocker.

**Stop when:** plan batches are done (or true blocker), PR is landable, you did not merge.
```

---

## Chat-to-land (E2E through merge)

> Same as chat-to-work, then **reviewed-PR landing** through a regular merge commit.
> This is an explicit merge opt-in. Design: [`e2e-chat-to-land.md`](e2e-chat-to-land.md).

```
Elves E2E: chat-to-land (merge when green).

**Intent / brief:**
[What I want built or researched. Constraints, non-negotiables, deadline if any.]

**Repo / branch preference:** [auto or feat/…]
**Work driver:** [host-native | grok-build | opencode-cli | …]
**Delegation scope:** [none | batch | full_run]
**Multi-planner:** [optional host Cobbler only | also use available plan/review lenses]

**Your job (one continuous run after planning is solid):**
1. Chat only as needed to sharpen intent. Optionally route independent planners. Reach conceptual
   agreement; synthesize one plan on disk.
2. Stage fully (you own staging quality): survival guide, learnings, execution log, branch, PR,
   preflight, Cobbler session state. Set Run Control: `e2e mode: chat-to-land`,
   `merge policy: reviewed-pr-landing-command`, labor re-drive budget 3. Treat `B0` and `B1` as
   equally valid batch starts and accept both bare `- [ ] B0-A1: …` and bracketed
   `- [ ] [B0-A1] …` stable-id rows. Before any worker launch, parse the authoritative plan with
   targeted syntax errors and require session and packet acceptance ids/text to match it using the
   installed `acceptance_contract.py validate` helper; use explicit `sync-session --write` when
   deriving pending session rows from the plan is useful.
3. **Do not stop for a second human “launch” message.** For host-native or bounded delegation,
   execute every batch end-to-end. If `work driver: grok-build` and `delegation scope: full_run`,
   create the host-owned run/session `b0` rollback ref at the launch head before the packet/launch,
   launch one complete packet into one exact session, and park on bounded telemetry until a
   safety/blocked/terminal wake; no per-batch host prompting or PR loop.
4. Labor completeness: verify each bounded return, or verify the whole trusted full-run once at
   wake/exit; re-drive gaps (budget 3) or host-complete / hard-stop. Never accept partial labor.
5. Final Readiness Gate on the tip. Elves Report for substantial runs.
6. **Reviewed PR landing (explicit merge opt-in):** read every PR comment/check; run an
   Elves-routed Fugu review only when the user authorized paid Fugu use in this session and one
   unresolved high-impact review question remains (`/fugu review <scope>` or `$elves fugu review
   <scope>`; never a raw Fugu call; otherwise record the skip and its reason); fresh cumulative host review of
   `git diff <default-branch>...HEAD`; fix blockers; update docs and bump the version when the
   repository versions; re-poll async review/CI; then `gh pr merge --merge` only when not draft,
   checks green, no blocking review, clean worktree. Never squash or rebase.

**Continuation:** Prefer `/goal` (Codex) or host long-run continuation once staging is ready.
Authority remains Stop Gate until Readiness; then landing rules above.

**Hard rules:**
- Merge only via regular merge commit after landing criteria; never squash.
- Main driver is this host; optional tools are optional.
- Do not stop mid-run because a work driver "finished a turn" — check completeness.

**Stop when:** PR is merged with a merge commit, or a true blocker prevents safe merge (report exactly what remains).
```

**Codex tip:** after stage inside the same E2E run (or in an explicit legacy second call), you can wrap the
execution tail with `/goal` using the short launch body from [`codex-goals.md`](codex-goals.md),
plus the e2e mode and merge policy from the survival guide.


<!-- v2.3 risk/proof policy pins -->
- thin safety kernel; risk low|standard|high independent of trust trusted|untrusted
- validate once, verify changes, attest final
- impact-selected proof during work; broad proof once at terminal readiness and explicit high-risk checkpoints
- mid-run nonblocking new/unresolved PR feedback; terminal waits for required checks
