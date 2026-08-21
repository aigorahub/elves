# Exact-session native-worker prewalk

## Promise

Elves **prewalk** is a trajectory property, not a richer handoff. One separate subscription-native
or separately qualified worker session receives the task packet once, explores the repository on a
guide route, creates a bounded
TODO, makes the first meaningful task edit, and writes a transition checkpoint. The outer
supervisor then resumes that exact session in that exact worktree on the execution route with only
`Continue.`. A new session that receives a summary or copied packet is a cold handoff and must not
be reported as prewalk.

The driver still owns staging, canonical run memory, protected refs, terminal review, PR state,
landing policy, and merge. Prewalk grants no new Git, credential, approval-bypass, PR, or merge
authority.

## Lifecycle and durable artifacts

```text
staged -> launching_prewalk -> prewalking -> transition_ready
       -> launching_execution -> executing -> complete
```

Transport-only execution failures add `execution_backoff` and resume the execution route after the
canonical 5m, 10m, and 20m delays. They never rerun the guide or consume substantive re-drive
budget. Terminal failures preserve the private state, one redacted follow log, and the assigned
worktree.

The guide mirrors its native TODO mechanism into private JSON under
`.elves/runtime/prewalk/<run>/`:

- `todo.json`: one or more ordered `PW-01` items, up to a configurable ceiling of 5–12 items
  (default 10), each with description, observable acceptance, validation, and status; at most one
  item is `in_progress`.
- `checkpoint.json`: the exact run/session identity, `first_meaningful_edit` or `task_complete`,
  TODO item, changed repository-relative paths, summary, and validation attempted.
- `session.json`: the exact safe worker-session identity captured or assigned by the supervisor.

The guide prompt states both artifact shapes literally, with one filled example each (#260). A
guide that has not read `prewalk.py` still has everything it needs, because a semantically correct
artifact in another dialect fails the transition and terminalizes the run *after* the guide turn
has already been paid for. Two bounds are normalized rather than enforced: a `summary` longer than
500 characters is truncated, and an absent or null `validation_attempted` becomes an empty list.
Everything else stays fail-closed. Leniency never fabricates evidence — a prose `validation`
string is not coerced into a `{command, exit_code}` record, because that would invent an exit code
the guide never observed — and it never touches identity, schema version, `PW-##` ordering, or the
literal `ready_for_execution_model: true` assertion.

Live qualification records the route it **observed**, not the route it requested (#258). The
canary derives `route_change` from provider evidence: when a host names the model it actually
resumed with, that name must match the requested execution model or qualification fails with
`prewalk_route_change_unqualified`. Codex publishes such a notice (an `item.completed` whose inner
item type is `error`, naming both the recorded and the resuming model) and publishes it only when
the model actually changes; Claude Code, Grok Build, and Oh My Pi publish nothing comparable
today. Absence of a signal is not evidence that an override was ignored, so it never fails closed
— the artifact records `route_change_evidence: unobserved` and an empty `observed_execution_route`
instead of claiming behavioural proof. No host publishes the reasoning level it actually used, so
observed effort is always null rather than copied from the request.

The model-free transition validator requires a clean registered start, unchanged branch/origin/
protected refs, a real source/test/product-documentation edit tied to the checkpoint, no forbidden
surface, and no `Close` commit. Runtime-only, plan-only, execution-log-only, empty, mismatched, or
out-of-worktree changes fail closed. A tiny atomic task may finish after the guide only when every
TODO item is complete and the checkpoint explicitly says `task_complete`; a zero guide exit alone
never means completion.

The version-3 private native-worker state records requested and actual mode, both phase routes,
capability and instruction-fidelity evidence, packet digest/count, status history, attempts,
session/worktree continuity, transition proof, bounded diagnostics, and fallback. Version-2
single-phase launch/status/follow remains supported.

## Modes and qualification

`prewalk` accepts `off`, `auto`, `required`, or `experimental`.

- CLI launch defaults to `off`, preserving existing single-phase behavior.
- The safe global convenience preference defaults to `auto` in
  `${XDG_CONFIG_HOME:-~/.config}/elves/config.json`.
- `auto` makes no qualification model calls. It activates on medium/high or multi-step work only
  when matching successful proof is cached for the exact installed version/build and the exact
  execution route. It skips clearly atomic low-reasoning work and records a fallback with the
  concrete reason.
- `required` automatically runs one bounded live qualification canary when matching cached proof is
  absent. The canary has a 180-second hard wall budget and 1 MiB combined output limit. It launches
  no task worker until exact resume, route change, same session, same worktree, one logical stream,
  retained guide context, and one packet all pass. Success is cached privately under
  `${XDG_CACHE_HOME:-~/.cache}/elves/prewalk/`; failure stops and names a private `.attempt.json`
  evidence artifact.
- `experimental` is an explicit operator acceptance of the uncertainty that remains after static
  grammar inspection. It requires advertised exact resume and route override. It does not claim
  behavioral qualification. The real worker still fails closed on exact session identity,
  registered worktree binding, stream identity, packet count, meaningful transition, forbidden
  paths, Git authority, and post-edit cold fallback.
- Claude Code, Codex, Grok Build, and Oh My Pi use the same mode semantics as hosts or eligible
  worker transports. Grok remains subject to provider consent, repository veto, live model catalog,
  and API-key requirements. Prewalk adds no credential or provider authority.

A cached canary qualifies one exact installed version/build and one exact **execution** route
(model and reasoning level). That is what the canary proves: this transport resumes one exact
session, and the model that resumes retains the guide phase's instructions across the resume.
Because neither property belongs to the guide route, the same proof covers any guide model and any
guide effort, and covers no other execution route. An upgrade, or a change of execution model or
execution level, triggers a new canary under `required`; `auto` falls back instead of spending.
Guide-phase quality is never assumed from a canary: the transition kernel checks the guide's TODO,
checkpoint, meaningful edit, session identity, and worktree binding on every run.

Both phase routes are validated against the installed host's own model catalog. Elves stores no
model names: a pin is accepted when the host publishes that reasoning level for that model, and a
host that publishes no catalog (or whose catalog cannot be read) keeps the conservative offline
vocabulary rather than guessing. On Codex the catalog comes from `codex debug models`, a local
read with no model call, cached for the process. `ELVES_CODEX_MODEL_CATALOG=<path>` points the
reader at a catalog file instead, for offline hosts and tests; an unreadable, oversized, or
unparsable file reports its reason and keeps the floor, and never widens a route.

Sakana's Claude Code-compatible Fugu endpoint does not change that. A Claude Code host pointed at
`https://api.sakana.ai` advertises the same `--resume <uuid>` grammar, but advertised grammar has
never been the qualifying evidence here: conversation continuity, worktree binding, stream
identity, and instruction fidelity belong to the serving gateway, and Sakana's are unproven by this
repository. Fugu is an external provider on that route and stays `off` under `auto`, exactly like
every unqualified provider. An explicit required-mode canary must prove the exact serving gateway
and route before use; Claude-shaped CLI syntax alone is never enough. Whenever a Fugu route is
pinned, for either phase or for an ordinary worker, name a current catalog slug: `fugu`,
`fugu-ultra-v1.1`, or `fugu-cyber`
on the `codex-fugu` lane, and the `[1m]` tier names on the Claude Code-compatible interface. Prefer
the exact versioned `fugu-ultra-v1.1` over the floating `fugu-ultra` alias: a route recorded in a
qualification artifact has to keep meaning one model, and an alias that follows the vendor's latest
ultra release does not.

Configure or inspect the preference from the active Elves skill root:

```bash
python3 scripts/cobbler_agents.py preferences set worker.prewalk auto
python3 scripts/cobbler_agents.py preferences show
```

Repository vetoes and explicit run intent outrank the global preference. The preference cannot
grant credentials or authority.

## Capability truth and instruction fidelity

Static `--help` output may establish only `advertised_exact_resume` and
`advertised_route_override_on_resume`. It cannot establish conversation continuity, worktree
binding, stream identity, or instruction pruning. The read-only probe makes no model calls:

```bash
python3 scripts/cobbler_agents.py native-worker prewalk-capabilities \
  --host codex --json
python3 scripts/cobbler_agents.py native-worker prewalk-capabilities \
  --host claude --json
python3 scripts/cobbler_agents.py native-worker prewalk-capabilities \
  --host grok --json
python3 scripts/cobbler_agents.py native-worker prewalk-capabilities \
  --host omp --json
```

The `--host grok` and `--host omp` probes are the same read-only shape: each parses installed
`--help`/`--version` grammar, makes zero model calls, and reports a concrete unavailable reason
when no installed binary exists. They never claim behavioral qualification.

A behavioral qualification artifact is bounded, mode-safe JSON bound to the exact host, transport, and version,
session, guide and continuation digests, successful create/resume exits, same worktree/session, a
guide-only fact observed after resume, one logical stream, no packet replay, the exact requested
guide/execution model and effort, whether qualification made model calls, and an explicit
instruction-fidelity result. Help-only probes report no model calls; a live behavioral artifact
records its actual call provenance. Reported fidelity states are:

- `pruned`: the temporary guide instruction is behaviorally proven absent after transition;
- `turn_scoped`: the instruction is proven to apply only to the guide process and is not rebuilt
  for the resumed process;
- `retained_safe`: exact trajectory is proven and the cooperative guide instruction is safe to
  retain; this is usable but is not a prefix-pruning claim;
- `unsupported`: no usable behavioral qualification; prewalk stays unavailable.

The current supervised CLI transport sends the cooperative guide instruction in persisted session
history, so this implementation activates only with `retained_safe` evidence. `pruned` and
`turn_scoped` remain explicit future transport states and must not activate this path without a
different, behaviorally proven instruction-delivery mechanism.

For the Grok Build transport the successful behavioral artifact is the
`grok_prewalk_qualification_canary` (schema version 1): a bounded (≤ 64 KiB), regular non-symlink
JSON file read
through a descriptor-bound (O_NOFOLLOW, fstat-identity) loader. It must carry exactly the required
fields binding host `grok`, transport `grok_build`, the exact installed version and build commit
reported by the installed binary, one canonical session UUID, both phase routes with model and
effort, successful create/resume exits, same-worktree/session/stream continuity facts, guide-only
fact retention, no packet replay, model-call provenance, and an explicit instruction-fidelity
result. Required mode creates this artifact only after every shared check passes. The loader
validates cached or explicitly supplied artifacts, and `retained_safe` remains the only normally
activating fidelity. Routing binds Grok evidence to the exact version/build reported by the
installed binary rather than trusting self-asserted identity. The registry still rejects Grok
single-phase native-worker launch; a qualified or explicit experimental two-phase prewalk spec is
the only path through this seam.

Provider cache tokens are telemetry only. Cache hits neither prove nor gate trajectory continuity.

## Host parity

| Concern | Codex | Claude Code | Grok Build | Shared requirement |
|---|---|---|---|---|
| Fresh identity | capture `thread.started.thread_id` | caller-generated UUID | caller-generated UUID via `--session-id` (create-only) | exact ID before transition |
| Guide route | `--model`, `model_reasoning_effort` | `--model`, `--effort` | `--model`, `--effort` | explicitly pinned |
| Exact resume | `codex exec resume <id>` | `--resume <uuid>` | exact `--resume <uuid>` | never `--last`/`--continue` |
| Resume route | flags before `resume`; OS CWD; `--model` and `model_reasoning_effort` apply on resume | model/effort with resume; supervisor CWD | model/effort with resume; supervisor `--cwd`; sandbox resume-sticky | explicit execution route, same worktree |
| Route vocabulary | live `codex debug models` catalog per model | installed help grammar | authenticated live catalog | no model names stored by Elves |
| Proof reuse | one canary per execution route, any guide route | same | same | identical rule on every host |
| Stream | JSONL | stream JSON | streaming JSON (no tool-call events; `sessionId` only on `end`) | one redacted logical follow log |
| Authority | workspace sandbox + narrow Git roots | `auto` classifier + narrow Git roots | `--permission-mode auto`, never yolo/always-approve | existing no-push/protected-ref checks |
| TODO/checkpoint | native mechanism + private JSON mirror | native mechanism + private JSON mirror | private JSON mirror is authoritative (installed `plan.json` persistence is vestigial) | bounded provider-neutral schema |
| Failure | exact-session recovery | exact-session recovery | exact-session recovery | no post-edit cold fallback |

Codex keeps sandbox and additional Git roots before the `resume` subcommand. Claude keeps
`--safe-mode --print --verbose --output-format stream-json --permission-mode auto`; prewalk never
uses `bypassPermissions`. The Grok lane never emits `--always-approve`, `--yolo`, or `dontAsk`.
Its single-phase native-worker route remains registry-gated; required or experimental prewalk
supplies the separate two-phase gate. Custom-agent surfaces that cannot change route while preserving the exact
session do not qualify; the supervised CLI transport is the parity surface.

## Launch and recovery

Required mode performs qualification automatically when matching proof is absent:

```bash
python3 scripts/cobbler_agents.py native-worker launch --json \
  --host codex --worktree <registered-worktree> --run-id <run-id> --packet <packet> \
  --prewalk required --guide-model <guide-model> --guide-effort high \
  --execution-model <execution-model> --execution-effort <route-default-or-override>
```

The execution effort is route-dependent, not a fixed `medium`: the grok route defaults to
`high`, and other routes keep their own defaults. Pass an explicit value only to override the
route default. A Grok qualification canary recorded at execution effort `medium` before the
`high` default fails `qualification_route_mismatch` and must be re-recorded at `high`.
The OMP route accepts `xhigh` and `max`. It passes these levels unchanged to `omp --thinking` in
both phases. The Codex route accepts whatever `codex debug models` publishes for the pinned model,
which currently includes `xhigh` and `max` on the frontier models and stops lower on others; a
model the catalog does not list, and a machine where the catalog cannot be read, keep the
conservative `low`/`medium`/`high` floor. A strong guide at a high level handing off to a cheaper
execution model at its own level is the intended shape of this lane. One canary per execution
route serves every guide route, so trying several guides costs nothing more.
OMP create and resume use one stable run profile. Isolated `--profile` state does not inherit host
OAuth. Auth preflight runs before any model call and before spec reports launch-ready: a matching
API key, or a paired loopback broker from the environment or from persistent `auth.broker`
settings. Incomplete, remote, or unhealthy broker settings fail closed. The broker token is never
printed. There is no per-profile login.
The guide packet enters as one private `@file` user message. The resume phase receives only the
continuation message as a positional input.

Use the same shape with `--host claude`, `--host grok`, or `--host omp`. A previously recorded artifact may still
be passed with `--prewalk-capability-evidence`. Existing `--model`/`--effort` keep their single-phase
meaning when prewalk is off; ambiguous mixed phase flags are rejected.

The packet is sent only on the guide turn. Normal transition is automatic and never wakes the
driver for approval. A failed guide gets one bounded exact-session guide recovery without packet
replay. Before any task edit, `auto` may record abandonment and start an explicitly fresh normal
worker; that result is not claimed as prewalk. After an edit, cold fallback is forbidden. Session
ID, worktree, branch, origin, protected-ref, artifact, or meaningful-edit mismatch fails closed
with a stable `prewalk_*` code and a bounded recovery hint.

The live canary runs in a temporary Git worktree, not the target checkout. Its guide reads a random
worktree file and retains a separate random guide fact. Before exact-session resume, the host
changes the file to an unknown second value. The continuation receives only `Continue.` and must
return both the retained guide fact and the new worktree value on the execution route. Structured
events must bind the same exact session in both phases. The host records booleans, route/version
identity, hashes, bounded redacted diagnostics, and packet count. It never stores model output or
the random facts. The real prewalk lifecycle checks the same trajectory properties again against
the task worktree.

## Compaction de-qualification (P4)

A **compaction event** (manual `/compact`, host auto-compact, or equivalent summary
boundary) inside a **qualified exact-session prewalk** invalidates that session's
`retained_safe` guide-fact guarantees for the remainder of the trajectory.

After such a compaction:

1. Treat continuation as **packet semantics** (cold facts from run docs), not as
   proven retained guide instructions.
2. Do **not** claim exact-session prewalk success for later batches on that session id
   unless the pair is **re-qualified** with a fresh canary bound to the post-compact
   session state.
3. Record `prewalk_fallback: prewalk_dequalified_by_compaction` (or equivalent) in
   route evidence.

This rule is normative for Claude Code, Codex, Grok Build, and Oh My Pi hosts.
