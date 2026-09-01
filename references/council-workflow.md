# Cobbler Workflow (Council Compatibility)

Cobbler is the default coordination layer inside Elves. In an Elves run, Cobbler classifies the
work, routes agents/tools/skills, preserves useful dissent, and synthesizes the next action before
the loop moves forward. The user can also ask Cobbler once in chat; that one-off form returns a
fitted answer from direct analysis or independent lenses.

The `python3 scripts/...` form used later is source-checkout shorthand. From an installed Claude
Code or Codex skill, invoke the helper from the active Elves skill root while keeping the target
repository as the working directory; see [`runtime-helper-paths.md`](runtime-helper-paths.md).

This file keeps its `council-workflow.md` name for `v1.14.0` compatibility. In `v1.15.0+`, Cobbler
is the user-facing coordinator and default orchestration model. Council is the compatibility path
and gathering mechanism, not a separate product.

The hierarchy is: Elves executes, Cobbler coordinates, domain workflows specialize, and providers
route optional roles. Math is the first Cobbler-managed domain workflow. Its claim, source,
model-call, and human-verification ledgers are domain evidence artifacts, not a separate Council
ledger or a replacement for normal Elves run memory.

## Invocation Semantics

Host invocation depends on the agent surface:

- Claude Code primary: `/cobbler <task>`.
- Codex primary: `$elves cobbler: <task>` or natural language such as "Ask the Cobbler..."
- Claude Code compatibility: `/council <task>`, `/ec <task>`, and `/elves-council <task>`.
- Codex compatibility: `$elves council: <task>` and natural Council references.

Do not document Codex as having a top-level `/cobbler`, `/council`, `/ec`, or `/elves-council`
command unless the user's Codex install explicitly provides one.

These are documentation semantics for agent behavior. This repo does not ship a hosted parser or
runtime for slash commands.

## Modes

### Run Cobbler

Run Cobbler is the default coordination pattern inside an Elves run. Use it for non-trivial
planning, contract writing, risk calls, debugging, review synthesis, scout prioritization, and
final recommendations. The coordinator decides whether to act directly, delegate implementation to
worker agents, ask independent lenses for review/risk, or synthesize the evidence into the next
batch action.

The main coordinator owns canonical run memory, protected refs, PR actions, final gates,
cumulative independent review, any authorized merge, and final synthesis. Host-native and legacy
bounded routes also keep feature-branch commit/push in the host. The exact registered trusted
`branch_progress` full-run worker is the sole exception: it may commit and push only its assigned
feature branch while the host parks. Untrusted writer leases remain detached and host-imported.
Worker agents may edit the repo only when the active contract assigns implementation work;
read-only lens agents remain read-only for inspection, review, scouting, or dissent.

Run Cobbler reuses existing Elves memory surfaces. Do not create a separate council ledger for
ordinary software work.

Record only material outcomes:

- execution log: Cobbler recommendation, strongest dissent, evidence, and next action when it
  changes the plan, risk picture, or review queue;
- survival guide: live run-control, active compute, Stop Gate, or next-batch changes only;
- `.elves-session.json`: machine-readable batch status, continuation guard, or review-comment
  dispositions when needed;
- learnings: stable reusable lessons only after they are no longer just one-off run context.

If the Cobbler answer does not change the run, do not log it just to create ceremony.

Run Cobbler is not the same thing as full-run model routing. Run Cobbler coordinates the Elves
loop. Full-run model routing records phase preferences in the survival guide and execution log:
requested route, actual route, and material fallback reason for implementation, validation,
review, scouting, or synthesis. Keep those route notes in the existing Elves memory surfaces, not
in a separate council ledger.

### Cobbler Mode

Cobbler Mode is a thread-local convention for repeatedly chatting with the Cobbler without typing
the invocation on every prompt. It is not a third Cobbler behavior mode: follow-ups still classify
as direct answer, Quick Cobbler, direct implementation, or Run Cobbler.

- Claude Code: `/cobbler-mode` when the managed alias skill is installed.
- Codex: `$elves cobbler-mode` or natural language such as "Cobbler Mode: on".
- Exit: "Cobbler Mode: off" or "leave Cobbler Mode".

Cobbler Mode is current-thread conversation state, not durable run state. It does not create a
branch, PR, survival guide, execution log, Codex Goal, provider-backed council, or persistent
config entry by itself.

### Quick Cobbler

Quick Cobbler is the default one-off answer mode. It is always read-only and stateless: it may
recommend what an active Elves run should record, but it does not itself edit files or mutate run
state. If the user wants the result applied to a run, reclassify the follow-up as Run Cobbler and
let the coordinator record the material outcome in existing Elves memory. Use native subagents first:

- Codex subagents in Codex;
- Claude Code subagents in Claude Code;
- the same read-only analysis directly when subagents are unavailable.

Quick Cobbler should not edit files, create branches, open PRs, install packages, or mutate run
state. It inspects, thinks, and recommends.

### Two-stage cheap gate (optional pattern)

Before convening a full multi-lane council or a heavy optional pass (high-risk review add-on,
adversarial lens), a coordinator may run one small yes/no pre-check — "does this decision
actually need independent lanes, and what should they focus on?" — and skip the expensive pass
when the answer is no. The pre-check is advisory routing, never a vote, never evidence, and
never a substitute for the terminal review. Prefer it when council spend is material and the
need is uncertain; skip it when the phase already mandates a council.

## Provider-Backed Council (Optional Routing)

Provider-backed council is not a third Cobbler mode. It is optional routing for selected roles when
provider-backed council is enabled and safe context-sharing is allowed. It may use configured
external providers for broader model diversity, but normal Cobbler, `/council`, `/ec`,
`/elves-council`, and `$elves council: <task>` use must not require OpenRouter or any external
provider key. If provider-backed council is requested and providers are unconfigured, degrade
gracefully to native-subagent Cobbler and say what was unavailable.

See [`council-provider-config.md`](council-provider-config.md) for optional provider setup.

Optional model routing is role-scoped. A configured route such as `openrouter:<model-id>` is a hint
for one lens, not a new Cobbler mode and not proof that the routed model is right. If a configured
route cannot run, fall back to native subagents or direct read-only analysis and mention the
fallback in the fitted answer. During synthesis, resolve disagreement by evidence, repo facts,
tests, sources, and user constraints rather than model prestige.

## Coordinator Flow

```text
User question
  -> intent
  -> capability scan
  -> route and medium selection
  -> context packet
  -> execute agents/tools/skills
  -> collect evidence
  -> fit answer
  -> present/record
  -> reclassify if the evidence changes the task
```

Intent classifies the request before Cobbler commits to a path: direct answer, one-off advice,
implementation, review, release, research, or active-run coordination.

The capability scan is ordered and practical:

1. Read active run memory, repo docs, and relevant files.
2. Check available host skills, subagents, tools, apps, tests, and PR/check surfaces.
3. Check whether source freshness requires web or external source lookup.
4. Check optional configured provider routes only when provider-backed council is enabled.
5. Fall back to direct analysis when a capability is unavailable or would add noise.

Route and medium selection chooses both the work path and the output surface. The path can be
direct answer, read-only lenses, scoped worker agents, tools/tests/source checks, provider-backed
read-only roles, or normal Elves run coordination. The medium can be a chat answer, file edit, PR
comment, execution-log entry, `.elves-session.json` update, Elves Report, or another artifact the
host can actually produce.

The context packet is the bounded state each role receives: user intent, mode, work scope, relevant
files, run-state pointers, source freshness needs, available tools/skills, output medium,
constraints, and forbidden actions. Never include secrets, tokens, credentials, cookies, or private
payloads in a context packet.

When Cobbler executes agents/tools/skills, read-only lenses stay read-only and worker agents edit
only the assigned files or modules. The coordinator always owns canonical run memory, protected
refs, PR actions, final gates/review, any authorized merge, and synthesis. Host-native and legacy
bounded routes also keep feature-branch commit/push in the host; only the exact registered trusted
`branch_progress` full-run worker may commit/push its assigned feature branch. Untrusted writers
remain detached and host-imported.

Collect evidence means assembling role reports, file references, commands, test results, PR
comments, source links, changed files, risks, and dissent. Keep retrieved evidence separate from
inference.

Fit answer means returning one recommendation with the strongest dissent preserved. Present/record
means answer the user, and record only material Run Cobbler outcomes in existing Elves memory.

Reclassify when new facts change the request. A one-off Cobbler answer can become Run Cobbler. A
review can become scoped implementation. A release can become a blocker. Do not force the first
route after evidence says it is wrong.

For small questions, use two roles. For design, migration, release, or ambiguous risk questions,
use three. Use more only when the user asks or the problem genuinely needs domain breadth.

## Role Selection

Default role pool:

- `architect`: boundaries, coupling, architecture, long-term shape.
- `skeptic`: assumptions, regressions, security/product risks, failure modes.
- `implementation_analyst`: concrete files, sequencing, integration details.
- `tester`: validation, regression proof, observability, missing tests.
- `maintainer`: repo conventions, documentation, future-agent readability.
- `domain_scout`: unfamiliar domain, source discovery, adjacent techniques.

Useful defaults:

- Short/simple task: `implementation_analyst`, `skeptic`.
- Design/refactor/planning task: `architect`, `skeptic`, `maintainer`.
- Bug/debug task: `implementation_analyst`, `tester`, `skeptic`.
- Test/validation task: `tester`, `implementation_analyst`, `maintainer`.
- Docs/process task: `maintainer`, `skeptic`, `architect`.
- Research-heavy task: `domain_scout`, `skeptic`, plus the most relevant implementation or
  architecture role.

Explicit `--roles` overrides these heuristics.

## Independence Invariant

Role agents do not see each other's reports before synthesis. Give every role the same user
question, relevant context, and constraints, then collect bounded reports independently. This keeps
the council from turning into an echo chamber.

The coordinator may share the final synthesis back to the user, and may show individual reports
only when the user asks for `--verbose`, `--show-reports`, or `--json`.

## Parallel Read-Only Dispatch (operator runtime)

Elves ships a standard-library parallel dispatcher at `scripts/cobbler_runtime/dispatch.py` with the
thin CLI entry point `python3 scripts/cobbler_agents.py council`.

Rules:

- Lanes launch **concurrently** (`asyncio.create_subprocess_exec`, `shell=False`). Sequential
  launch is not a council.
- Every lane receives the same redacted context packet (task, role, mode, scope, relevant files,
  plan/run pointers, date/HEAD, output schema, evidence needs, forbidden actions).
- Child environments are minimal: strip API-key/token/cloud/git credential env **names** by default
  and report stripped names never values.
- Task text is never interpolated into a shell string; prompts/packets are file paths under ignored
  `.elves/runtime/council/<run-id>/` with restrictive permissions.
- Exit code zero is not success by itself — structured role-report JSON must validate.
- Stderr warnings (for example stale MCP OAuth noise) do not fail inference when the report is valid.
- One optional lane failure must not erase successful independent reports.
- Host synthesis remains the only fitted-answer step (`host_synthesis_only`).

### Quorum policy

- `target_quorum` is **advisory**. If optional fallbacks still leave fewer successful independent
  reports, continue with host synthesis, record a confidence drop, and do **not** label the result
  `council_verified`.
- `required_quorum` is valid only when the phase is explicitly `required=true` in the project
  Survival Guide. It counts successful independent reports (including a fresh host-native lane),
  tolerates individual optional lane failures while the count is met, and **blocks** after
  recovery/fallback when it is not met.
- Required lane failures block even if optional peers succeeded.

### Council command result contract

The council command reports one aggregate `status` in JSON and human output:

- `success`: one or more valid independent reports exist. The command exits 0.
- `blocked`: a required lane or required quorum failed. The command exits 1.
- `unavailable`: no valid review report exists, but the phase is optional. The command exits 3.

An unavailable council is not a successful or clean review. The host can perform the documented
native fallback because this state is non-blocking. Argument parsing errors continue to use exit
status 2.

### Lightweight review (utility, not a council vote)

`python3 scripts/cobbler_agents.py lightweight-review` runs a **single** bounded ephemeral
read-only dispatch. It:

- may use a cheaper/faster profile from config;
- remains read-only and cannot perform git/PR mutations;
- cannot close a high-risk review;
- is **not** a default independent council vote and does not participate in council quorum.

Use it for quick utility checks. High-risk or merge-readiness review still needs the independent
council (or explicit host review) with the configured quorum policy.

## Role Report Shape

Each role returns a bounded report:

```yaml
role:
verdict:
confidence:
key_findings:
evidence:
risks:
recommended_actions:
open_questions:
```

Optional machine fields used by the runtime parser:

```yaml
actual_model:
requested_model:
```

Keep reports brief. Evidence should cite files, commands, PR comments, docs, or source material
when available. If a role lacks enough context, it should say so directly. When `requested_model`
is set, a mismatched `actual_model` fails that lane's structured validation.

## Fitted Answer Shape

The synthesizer returns one user-facing answer:

```text
Recommendation
Why this fits
Strongest dissent
Risks
Next move
Confidence
```

The recommendation comes first and takes a position. The strongest dissent is not a vote tally; it
is the objection, uncertainty, or verification gap that should affect the user's decision. The
`Next move` should be concrete enough for a user to act on without reading raw role reports.

For `--json`, use stable structured keys, but keep the default human-facing headings above.

## Non-Goals

- Do not copy vendor identity, policy, persona, or safety framing.
- Do not make Quick Cobbler require OpenRouter, `OPENROUTER_API_KEY`, or any external provider.
- Do not let Quick Cobbler edit files or mutate run state.
- Do not frame Cobbler as a non-default add-on or a tool that runs only when explicitly invoked;
  Cobbler-first coordination is the default run model.
- Do not create a separate PR, branch, survival guide, execution log, or ledger for ordinary
  council calls.
- Do not run multi-turn debate by default. Role agents work independently; the synthesizer
  reconciles them.
- Do not dump raw reports by default. Return one synthesized recommendation unless the user asks
  for verbose output.

## Done Criteria

A Cobbler response is useful when it:

- answers the user's actual question;
- names the aliases or mode only when relevant;
- runs a capability scan before routing non-trivial work;
- sends a context packet with scope, constraints, evidence needs, and forbidden actions;
- chooses the output medium before synthesis;
- shows one recommendation before caveats;
- preserves the strongest dissent or verification gap;
- gives a concrete next move;
- can reclassify when evidence changes the task;
- keeps one-off Quick Cobbler answers read-only; if the user asks for implementation, reclassifies
  the task as direct implementation or Run Cobbler before any edits;
- scopes any Run Cobbler worker edits to assigned files and keeps git/memory ownership with the
  coordinator;
- records material Run Cobbler decisions in existing Elves memory surfaces.
