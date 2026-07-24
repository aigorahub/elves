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

## Modes and actual default

`prewalk` accepts `off`, `auto`, or `required`.

- CLI launch defaults to `off`, preserving existing single-phase behavior.
- The safe global convenience preference defaults to `auto` in
  `${XDG_CONFIG_HOME:-~/.config}/elves/config.json`.
- `auto` activates only for a behaviorally qualified subscription-native exact-session transport
  on medium/high or multi-step work; it skips clearly atomic low-reasoning work and records an
  honest fallback.
- `required` fails before launch if exact resume, route change, worktree/stream binding, or usable
  instruction fidelity is unqualified.
- External providers remain off unless their trajectory semantics are separately qualified. The
  Grok Build arm exists behind exactly that gate: it is feature-gated, unqualified, and actually
  off. An operator-authorized live canary can establish version-bound `retained_safe` behavioral
  evidence, but qualification does not itself open the separate registry launch gate. Analogy to
  a native host never qualifies an external provider.

The initial release therefore normally reports actual mode `off`: read-only installed-help probes
show advertised grammar, but no host — Codex, Claude, or Grok — is behaviorally qualified by this
repository. No paid qualification is implicit.

Sakana's Claude Code-compatible Fugu endpoint does not change that. A Claude Code host pointed at
`https://api.sakana.ai` advertises the same `--resume <uuid>` grammar, but advertised grammar has
never been the qualifying evidence here: conversation continuity, worktree binding, stream
identity, and instruction fidelity belong to the serving gateway, and Sakana's are unproven by this
repository. Fugu is an external provider on that route and stays `off` under `auto`, exactly like
every other unqualified provider; a Claude-shaped CLI is an analogy, and an analogy to a native
host never qualifies an external provider. Whenever a Fugu route is pinned — for either phase, or
for an ordinary worker — name a current catalog slug: `fugu`, `fugu-ultra-v1.1`, or `fugu-cyber`
on the `codex-fugu` lane, and the `[1m]` tier names on the Claude Code-compatible interface. Prefer
the exact versioned `fugu-ultra-v1.1` over the floating `fugu-ultra` alias so a route recorded in a
qualification artifact keeps meaning one model.

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
```

The `--host grok` probe is the same read-only shape: it parses installed `grok --help`/`--version`
grammar, makes zero model calls, and reports a concrete unavailable reason when no installed grok
binary exists. It never claims behavioral qualification.

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

For the Grok Build transport the behavioral artifact is the `grok_prewalk_qualification_canary`
(schema version 1): an operator-recorded, bounded (≤ 64 KiB), regular non-symlink JSON file read
through a descriptor-bound (O_NOFOLLOW, fstat-identity) loader. It must carry exactly the required
fields binding host `grok`, transport `grok_build`, the exact installed version and build commit
reported by the installed binary, one canonical session UUID, both phase routes with model and
effort, successful create/resume exits, same-worktree/session/stream continuity facts, guide-only
fact retention, no packet replay, model-call provenance, and an explicit instruction-fidelity
result. The loader validates artifacts; it never fabricates them, and `retained_safe` remains the
only fidelity eligible to activate here as well. Routing accepts the artifact only alongside
`--probe-grok`, binding it to the exact version/build reported by the installed binary rather than
trusting self-asserted artifact identity. Even valid behavioral evidence cannot mutate
`launch_ready`; the maintainer-owned registry launch gate must be opened separately after the
launch path is complete. No live artifact has been recorded, `launch_ready` remains false, and
Grok prewalk is unqualified for launch.

Provider cache tokens are telemetry only. Cache hits neither prove nor gate trajectory continuity.

## Host parity

| Concern | Codex | Claude Code | Grok Build (feature-gated, unqualified) | Shared requirement |
|---|---|---|---|---|
| Fresh identity | capture `thread.started.thread_id` | caller-generated UUID | caller-generated UUID via `--session-id` (create-only) | exact ID before transition |
| Guide route | `--model`, `model_reasoning_effort` | `--model`, `--effort` | `--model`, `--effort` | explicitly pinned |
| Exact resume | `codex exec resume <id>` | `--resume <uuid>` | exact `--resume <uuid>` | never `--last`/`--continue` |
| Resume route | flags before `resume`; OS CWD | model/effort with resume; supervisor CWD | model/effort with resume; supervisor `--cwd`; sandbox resume-sticky | explicit execution route, same worktree |
| Stream | JSONL | stream JSON | streaming JSON (no tool-call events; `sessionId` only on `end`) | one redacted logical follow log |
| Authority | workspace sandbox + narrow Git roots | `auto` classifier + narrow Git roots | `--permission-mode auto`, never yolo/always-approve | existing no-push/protected-ref checks |
| TODO/checkpoint | native mechanism + private JSON mirror | native mechanism + private JSON mirror | private JSON mirror is authoritative (installed `plan.json` persistence is vestigial) | bounded provider-neutral schema |
| Failure | exact-session recovery | exact-session recovery | exact-session recovery | no post-edit cold fallback |

Codex keeps sandbox and additional Git roots before the `resume` subcommand. Claude keeps
`--safe-mode --print --verbose --output-format stream-json --permission-mode auto`; prewalk never
uses `bypassPermissions`. The Grok column is advertised-and-registry grammar only: the arm is
feature-gated off, `launch_ready` is false, and this lane never emits `--always-approve`, `--yolo`,
or `dontAsk`. Custom-agent surfaces that cannot change route while preserving the exact
session do not qualify; the supervised CLI transport is the parity surface.

## Launch and recovery

After qualification, the phase-explicit CLI shape is:

```bash
python3 scripts/cobbler_agents.py native-worker launch --json \
  --host codex --worktree <registered-worktree> --run-id <run-id> --packet <packet> \
  --prewalk required --guide-model <guide-model> --guide-effort high \
  --execution-model <execution-model> --execution-effort <route-default-or-override> \
  --prewalk-capability-evidence <qualification.json>
```

The execution effort is route-dependent, not a fixed `medium`: the grok route defaults to
`high`, and other routes keep their own defaults. Pass an explicit value only to override the
route default. A Grok qualification canary recorded at execution effort `medium` before the
`high` default fails `qualification_route_mismatch` and must be re-recorded at `high`.

Use the same shape with `--host claude`. Existing `--model`/`--effort` keep their single-phase
meaning when prewalk is off; ambiguous mixed phase flags are rejected.

The packet is sent only on the guide turn. Normal transition is automatic and never wakes the
driver for approval. A failed guide gets one bounded exact-session guide recovery without packet
replay. Before any task edit, `auto` may record abandonment and start an explicitly fresh normal
worker; that result is not claimed as prewalk. After an edit, cold fallback is forbidden. Session
ID, worktree, branch, origin, protected-ref, artifact, or meaningful-edit mismatch fails closed
with a stable `prewalk_*` code and a bounded recovery hint.

Live canaries for Codex, Claude, and Grok are a separate operator-authorized rollout phase. They
must prove the same session/worktree, route change, guide-only fact retention, no packet replay,
stream identity, and honest instruction fidelity before `auto` can activate for that exact
installed version. The Grok lane additionally requires a separate reviewed change to open its
registry launch gate; a canary artifact cannot make that policy change. The operator canary
procedure for the Grok lane is in
[`grok-open-source-worker.md`](grok-open-source-worker.md).
