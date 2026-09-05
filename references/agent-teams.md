# Driver and helper teams

One driver owns the plan, assignments, integration, and final result. Helpers work
on bounded tasks. They can use different model families. Lantern assigns work to
the driver and tracks the pack. It does not become a second repository driver.

Use natural requests such as:

> Brainstorm checkout improvements. Get independent proposals, then compare them.

> Ship checkout performance improvements. Give the driver database and frontend helpers.

The driver stages an Elves run and opens a draft PR at the first useful commit.
It preserves the current model, permission, worktree, review, and landing rules.
Team initialization records the canonical worktree path. All callback commands
check that path. Canonical session changes share a process lock with writer lane
registration, so concurrent updates cannot remove contributors. A discussion holds
that driver lock through both phases. Concurrent driver commands stop after a
bounded lock wait and can be retried at the next boundary. Scoped helper reports
use their own transport store and do not take the driver session lock.
A request to implement stops at a landable PR unless the user authorizes merge.

## Saved choices

Use the existing onboarding and model configuration. Team preferences refer to
configured profile names or existing role names. They never contain model slugs,
credentials, approval settings, or merge policy. For example:

```sh
python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" onboard plan --json
python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" preferences set team.proposer claude-code-planning --json
python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" preferences set team.critic review --json
```

The six role preferences are `lead`, `proposer`, `investigator`, `implementer`,
`critic`, and `reviewer`. The driver resolves saved roles through the same local
profile configuration used by council dispatch. Explicit run choices and repository
vetoes take precedence. An absent named profile blocks dispatch. It does not select
a substitute. Existing adapter qualification and fallback rules still apply.
Onboarding reports the saved choices. Update them with `preferences set`.
`team route --role ROLE` resolves any of the six roles for the driver through
the existing route policy. `--profile NAME` applies an explicit run choice.
The result is a dispatch specification, not a new agent process.

## Driver and helper records

The public entry point is `python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" team`.
Each team command accepts `--repo-root` and `--session`. New team, team-report,
and team-lanes commands return a JSON object with `ok` and a nested `result` on
success. Failures return `ok: false` and error details. JSON input files must be local,
bounded files. Keep them and credentials out of Git.

`team init --input driver.json` records version 1 team state in the canonical
session. Driver identity requires `kind`, `model`, and exact `session_id`. When
Herdr is present, also record actor, server, pane, and generation identity.
The generation is one shared coordination epoch for the run. Driver and helper
credentials must share the run ID, server ID, and generation. It is not a
separate pane or model session generation.
The driver enters the contributor ledger immediately.

`team add-helper --input helper.json` records `task_id`, a concrete `task`, `role`,
and `identity`. The default limit is three active helpers. `--max-helpers` accepts
one to eight. The driver queues excess work. Helpers cannot create more helpers.
Before launch, use `team helper-packet --task-id ID --output PATH` to build the
original kickoff packet. The helper assignment must include intent, build_on,
owned_surfaces, forbidden_surfaces, and acceptance. Add the helper's own `callback`
configuration when its route can reach the local transport. The generator checks
the registered run, task, exact helper identity, and driver return address. It
rejects the driver credential. It includes automatic progress, question, blocked,
and completion reporting instructions using the scoped `team-report` CLI. That
CLI does not read or mutate the driver session. Isolated routes without access
to the local transport return evidence through their existing adapter; the driver
publishes those reports. Include this block in the original worker packet, never
as an extra prewalk turn.

Launch through the existing qualified dispatch or worker adapter. Registration
alone does not start a process or prove that work ran.

`team helper-state --task-id ID --input result.json` checks the exact recorded
identity on each transition. States are assigned, running, waiting-peer, complete,
failed, and cancelled. The first running transition requires the original packet and its recorded
digest. Terminal states require evidence. A waiting peer must be a
registered helper. Cyclic peer waits fail. A parked driver remains assigned to its
worker. Reports do not make it available for a second task.

## Independent proposals and critique

```sh
python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" team brainstorm \
  --task 'Compare checkout performance changes. Read the code and docs.' \
  --roles planning,review --timeout 300 --json
```

This uses existing read only council dispatch. All initial proposals finish before
any critique starts. Critique receives the completed proposals as evidence. It
uses fresh dispatch executions on the same routes as the proposal lanes.
Without `--roles`, the saved proposer and critic routes supply the two proposal
lanes. Both routes then receive the critique task in fresh sessions. A failed
proposal phase does not start critique.
The driver produces the final recommendation with evidence and unresolved dissent.
The command validates lane count and freshness before it saves a discussion.
It saves its discussion identity before launch and records each completed
phase before the next phase starts. Retrying the same discussion blocks until the
driver reconciles the stored evidence and exact adapter sessions. After stopping
or resolving the recorded executions, `team discussion-resolve --discussion-id ID
--input resolution.json` can record `outcome: cancelled` with evidence. This keeps
contributors in the ledger. Use a new
`--discussion-id` only for a new authorized round.
The command records discussion results and observed contributor executions. Routes
that report a native session also enter that exact session in the contributor
ledger. Do not treat an execution ID as a resumable native session.

The runtime permits two to eight proposal lanes and one critique round. Each lane
has the configured timeout. There is no recursive fanout. The command performs
model calls only through the existing configured adapters. A route that lacks
qualified native host execution returns unavailable, rather than a fabricated
proposal. Live model availability and exact session resume still need the existing
route preflight. Agy retains its qualified plan mode and Boost review procedure.

## Optional Lantern reports

Standalone Elves needs no Lantern executable. The persistent peer inbox requires
Lantern protocol 1. The transport supports checkpoint pulls and has no automatic
model wake. Do not type messages into a working, blocked, unknown, or parked pane.

The driver configures `team configure-callback --input callback.json` with:

```json
{
  "protocol": 1,
  "executable": "/absolute/lantern/bin/team_mailbox.py",
  "state_dir": "/absolute/private/lantern/herd",
  "actor_credential": "<ABSOLUTE_ACTOR_CREDENTIAL_FILE>",
  "timeout_seconds": 10
}
```

Lantern exports `LANTERN_TEAM_MAILBOX` and `LANTERN_TEAM_STATE_DIR` when available.
The driver registers actors through Lantern and passes only each actor's own
credential. The configuration is driver owned. Worker reports cannot replace it.
Explicit configuration qualifies the endpoint and records a private local
authorization outside the checkout. A checked out session alone cannot execute
a callback. Failed qualification permits a corrected configuration. Callback
subprocesses receive a minimal environment without provider API keys.
Python callback executables run through the current Python interpreter. Full
Elves team and writer execution retains the existing platform support: macOS,
Linux, and Windows through WSL2. Native Windows Python is not a qualified Elves
execution host. Inside WSL2, use executable, state, and credential paths that the
WSL filesystem can resolve. Native Lantern transport tests do not qualify native
Windows Elves execution.
Commands use argument arrays, closed stdin, and a timeout of at most 60 seconds.

Use `team post --input message.json` for assignment, progress, question, answer,
decision, PR opened, review requested, review result, blocked, completion, or
cancellation reports. The protocol message has `schema_version`, `message_id`,
`run_id`, `task_id`, `recipient`, `kind`, and a JSON object `body`.
The sender stores the message ID and content before calling Lantern. Messages
are limited to 64 KiB. Expired, unresolved, or retired deliveries remain blocked
until the driver inspects and resolves the outcome. A timeout
keeps that ID. `team callback-status` lists pending IDs. `team retry --message-id ID`
reuses the exact message. A storage receipt proves storage only.

Call `team checkpoint --checkpoint NAME` after staging, at supported batch or
packet boundaries, before review, before readiness, and before landing. CLI names
are `after-staging`, `batch-boundary`, `packet-boundary`, `before-review`,
`before-readiness`, and `before-landing`. Full run prepare, review dispatch, and
final readiness also enforce the relevant checkpoint. A healthy or parked full
run blocks driver consumption. The existing exact session supervisor checks
process identity before a stored healthy flag blocks a checkpoint. Records from
a different start commit do not park the current driver. Do not add a packet to a prewalk transition.

Record the decision and external result first. Then use
`team consume --message-id ID --input result.json`. The adapter stores the result
before it acknowledges the transport receipt. Repeated delivery cannot erase that
result. Receipt expiry leaves an unresolved delivery. Inspect actual effects with
`team inspect --message-id ID` and the relevant external tool. Use `team reconcile
--message-id ID --outcome consumed` or `retry` only after that inspection. Never
repeat a launch, PR action, permission response, or integration because a prompt
or transport call timed out.

Messages carry evidence and requests. They do not grant authority, select a new
model, mark acceptance verified, or execute text. Keep secrets and full transcripts
out of message bodies. Same user local processes are not a separate security
boundary. Run callback receipts remain under `.elves/runtime/team-callbacks/`;
Lantern owns the persistent transport store outside the product repository. Resolve
all reports before removing the run checkout.

## Review and writer integration

Contributors include the driver, writers, investigators, proposers, and critics.
`review-route` detects a team session and requires `--reviewer-identity FILE`.
`team check-reviewer --input identity.json` rejects any contributor session.
Prefer another model family. A fresh agent of the same family is valid. Profile
selection alone is not proof that a review ran.

`team record-review --input review.json` records reviewer `identity`, exact `head`,
`clean: true`, and the absolute report `artifact` path. The driver verifies the
report first. Final readiness checks the session exclusion, commit, report digest,
and terminal helper states. New contributors invalidate the review. A changed
commit or changed report fails readiness. The reviewer reads code, docs, tests,
and the cumulative diff before discussing findings with authors.

Use `team-lanes` for persistent writer records and driver owned integration. Each
lane has a separate worktree, branch, base commit, exact session, owned paths, and
dependencies. Registration does not launch the writer. Existing qualified worker
adapters retain process ownership. `gate` checks actual Git history and ownership.
`integrate` checks again, stores a reservation, and creates a regular merge commit.
An interrupted integration requires explicit reconciliation. See
[Parallelves](parallelves.md) for the full command and state contract.
