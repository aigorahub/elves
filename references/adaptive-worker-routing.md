# Adaptive subscription-native workers

Start with the user flow, not route vocabulary:

> “Implement this plan while I’m offline. Keep the PR unmerged.”

The live Claude Code or Codex driver classifies execution reasoning separately from review risk,
shows one worker recommendation, and asks at most one useful preference question. The default is a
separate worker on the subscription already in use. The worker receives the complete packet, the
driver exposes a capability-proven native agent view or exact follow command before parking, and
wakes for one cumulative terminal review. Worker completion never grants PR or merge authority.

## Small policy surface

Both hosts read the same versioned convenience file:

```text
${XDG_CONFIG_HOME:-~/.config}/elves/config.json
```

```json
{
  "version": 1,
  "worker": {
    "provider": "auto",
    "native_effort": "auto",
    "prewalk": "auto",
    "parallel": "off"
  }
}
```

Inspect or change it from the active installed skill root (commands shown with source-checkout
shorthand):

```bash
python3 scripts/cobbler_agents.py preferences show
python3 scripts/cobbler_agents.py preferences set worker.provider native
python3 scripts/cobbler_agents.py preferences set worker.provider grok
python3 scripts/cobbler_agents.py preferences set worker.prewalk required
python3 scripts/cobbler_agents.py preferences set worker.parallel auto
python3 scripts/cobbler_agents.py preferences reset
```

Writes are private and atomic. Safe unknown fields survive updates. Credentials and
merge/destructive/protected-ref/approval-bypass authority are rejected. Resolution is:

```text
repository safety veto > explicit run intent > repository defaults > global convenience > built-in default
```

Repository prohibition is always a veto. A current-run or global `provider=grok` is remembered
consent; repository `allow_grok=true` is not consent. Availability, preference, recommendation,
consent, and prohibition are separate facts.

## Deterministic recommendation

`route-worker` performs no model inference and reports provider, transport, model policy, effort,
review risk, provenance, fallback, optional driver-upgrade advice, advertised goal evidence, and
separately recorded behavioral verification:

```bash
python3 scripts/cobbler_agents.py route-worker --json \
  --host codex --execution-reasoning medium --review-risk high --probe-grok
```

Use `--host claude` when Claude Code is the live driver. The host value matters when an optional
provider falls back to the subscription-native worker.

An operator may bind a previously recorded terminal canary with
`--grok-goal-behavioral-evidence <artifact.json>` while using `--probe-grok`. The bounded JSON
artifact must validate against the exact installed version/build, canonical session, prompt digest,
successful exit, and matching terminal event. The help probe alone never sets goal mode, and an
invalid or incomplete artifact keeps the one-packet fallback.

“Inherit the driver model” means the exact observed model identity, not a cheaper sibling carrying
the same provider label. The worker route is always described as a `(model, effort)` pair:

| Live driver route | Default implementation-worker route | What changed |
|---|---|---|
| GPT-5.6 at `xhigh`/extra-high/`ultra` | same observed GPT-5.6 model ID at `medium` | effort only |
| GPT-4.8 Max/UltraCode | same observed GPT-4.8 model ID at `medium` | effort only |
| Claude Fable 5 at `max`/`ultra` | same observed `claude-fable-5` model ID at `low` | effort only |
| explicit or availability-driven Fable→Opus route | `claude-opus-4-8` at `medium` | model and effort; never call this inheritance |
| permitted Grok Build handoff | `grok-4.5` at `high` when present in the live catalog | cross-family; Composer 2.5 is retired |

These named defaults apply to a separate worker and to the execution phase of an exact-session
prewalk. An explicit user route still wins. Unlisted native routes use the plan's low/medium/high
execution classification. Permitted Grok workers prefer **`grok-4.5`** when the authenticated live
catalog returns it, at effort **`high`**. xAI retired Composer 2.5 (`grok-composer-2.5-fast`);
Elves never selects that identifier. An explicit catalog pin of any non-retired id still wins
when that exact id is returned live. The live driver itself is never downgraded. High review risk may advise a stronger
terminal-review driver without changing it in place.

## Optional exact-session prewalk route

The route decision represents guide and execution independently instead of overloading one worker
model/effort. It reports requested/actual prewalk mode, provenance, guide/execution transport,
model policy/model/effort, exact-resume and route-override capability, instruction fidelity,
fallback reason, and whether qualification made model calls (help probes always report false).

`worker.prewalk` accepts `off`, `auto`, and `required`. `auto` is conservative: only a behaviorally
qualified subscription-native exact-session transport may activate it, only for medium/high or
multi-step work; atomic low-reasoning work records a skip. External providers remain off unless
their trajectory semantics are separately qualified. `required` fails before launch rather than
silently becoming a packet handoff.

For `provider=grok` that separate qualification is a valid `grok_prewalk_qualification_canary`
artifact, passed with `--probe-grok --grok-prewalk-qualification <artifact.json>`. The live probe
binds the artifact to the exact installed version/build; the artifact's own identity fields are
never accepted as proof of what is installed. A valid artifact qualifies behavioral evidence but
does not open the separate registry launch gate. While `launch_ready` is false, `prewalk auto`
falls back with
`prewalk_capability_unavailable:grok_prewalk_unqualified:launch_feature_gate_closed` and actual
mode `off`, and `prewalk required` fails before launch with the same reason. Missing, mismatched,
or non-`retained_safe` evidence uses its own concrete reason. `allow_grok=false` remains an
absolute veto regardless of any evidence. The release-honesty rule extends to external providers:
no release may claim Grok prewalk availability or behavioral qualification while the arm is
feature-gated and unqualified for launch.

Inspect the installed grammar without inference:

```bash
python3 scripts/cobbler_agents.py native-worker prewalk-capabilities --host codex --json
python3 scripts/cobbler_agents.py native-worker prewalk-capabilities --host claude --json
python3 scripts/cobbler_agents.py native-worker prewalk-capabilities --host grok --json
```

Static help establishes advertised flags only. Actual prewalk additionally requires exact-version
behavioral evidence for one session/worktree/stream, route change, guide-only fact retention, no
packet replay, and honest instruction fidelity. The current persisted-instruction delivery path
activates only for proven `retained_safe`; `pruned` and `turn_scoped` remain future transport states.
With no qualifying evidence, the built-in `auto` preference honestly resolves to actual mode `off`;
the probe makes zero model calls. See the normative [`prewalk.md`](prewalk.md) contract.

When Grok Build is explicitly permitted and silently qualifies:

- prefer `grok-4.5` when the authenticated live `grok models` catalog returns it; otherwise use a
  non-retired live default (never `grok-composer-2.5-fast`);
- pass `--effort high` by default because `high` is Grok Build's highest supported effort; an
  explicit operator effort override remains authoritative;
- never invent an unavailable model: an explicit identifier (including `grok-4.5` or
  `grok-code-fast-1`) is valid only when the authenticated live catalog returns that exact
  identifier;
- missing install, auth, live catalog, supported session grammar, consent, or another core launch
  capability records an honest native fallback with a concrete reason;
- goal support is separate: behaviorally verified headless `/goal` enhances the launch, while an
  otherwise qualified provider uses the recorded one-packet prompt fallback when goal is absent.
  Help text alone proves only an advertised entrypoint.

The installed executable is launch authority; upstream source is semantic reference only. See
[`grok-open-source-worker.md`](grok-open-source-worker.md) for the complete optional-worker path.

## Host transports, same contract

| Concern | Claude Code | Codex |
|---|---|---|
| Fresh identity | caller-assigned UUID | capture `thread.started.thread_id` |
| Exact resume | `--resume <uuid>` | `codex exec resume <thread-id>` |
| Worktree | native isolated worktree or supervisor CWD | `-C` on create; supervisor OS CWD on resume |
| Model | inherit unless explicitly pinned | inherit unless explicitly pinned |
| Effort | `--effort <level>` | `model_reasoning_effort=<level>` |
| Unattended commit | Claude `auto` classifier; `acceptEdits` is not commit-capable | workspace-write sandbox plus narrow Git roots |
| Visibility | capability-proven native agent view or private follow log | capability-proven native agent view or private follow log |

Build an inspectable CLI-fallback launch specification with `native-worker spec --host claude|codex
--worktree <path> --effort <level> --model <observed-current-model> --json`. Native custom agents
inherit the live model. A supervised CLI child cannot safely infer a parent invocation override, so
the host must supply the observed current model (or an explicit routed model) and the command pins
it. Every path uses a separate session, never uses `--last`, and never claims a cross-session cache
handoff.

The supervised Claude transport uses `--safe-mode --print --verbose
--output-format stream-json` and `--permission-mode auto`. Current Claude requires `--verbose` for
that streaming combination. `acceptEdits` can apply file edits but cannot approve the Bash calls
needed for an unattended commit, so Elves does not describe it as commit-capable. Claude's `auto`
classifier supplies the approval boundary without using `bypassPermissions`; the stripped child
environment still disables network Git push, and terminal Git-contract checks constrain the result
to the assigned feature branch. A Claude version without this grammar fails visibly rather than
silently falling back to edit-only behavior.

`native-worker launch` supervises the child and tees redacted structured stdout/stderr into a
mode-0600 per-run follow log. It returns an exact `native-worker follow --run-id <id>` command
before the driver parks; `native-worker status` reports the bound PID, session, worktree,
visibility state, commit mode, and exit status. When a child exits nonzero before emitting any
provider event, status also includes a bounded redacted stderr tail so launch grammar and
authentication failures are diagnosable without opening the raw follow log. A spec with neither a
proven host view nor a follow log reports `visibility_ready=false` and
`visibility_mode=commit_only`.

## Cache and authority limits

Exact worker resume preserves provider conversation continuity. Provider-side prompt caching may
also report cached tokens. Neither host exposes a supported cache object that Elves can export from
the driver and inject into another process or model; a session ID is not such an object. Cache hits
are opportunistic telemetry, never launch or acceptance gates.

Preferences cannot grant credentials, unattended approval bypass, destructive commands, protected
refs, PR operations, or merge. A trusted assigned worker may advance only its registered feature
branch when the packet grants that narrow authority. The driver retains canonical run memory,
terminal proof/review, PR state, landing policy, and merge.
