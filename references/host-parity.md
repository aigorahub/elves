# Host parity: Claude Code, Codex, Grok Build, and Oh My Pi

**Supported main drivers are Claude Code, Codex, Grok Build, and Oh My Pi (omp).** All four share the workflow,
safety kernel, automatic required-mode qualification, explicit experimental mode, and exact-session
prewalk contract.

| Concern | Claude Code | Codex | Grok Build (host) | Oh My Pi (host) |
|---------|-------------|-------|-------------------|----------------|
| Skill load | `~/.claude/skills/elves` | `~/.codex/skills/elves` | `~/.grok/skills/elves` | `~/.omp/agent/skills/elves` |
| Primary invoke | `/elves`, natural language | `$elves`, natural language | natural language | natural language / skill load |
| Cobbler | `/cobbler`, `/cobbler-mode` | `$elves cobbler: …` | natural language | natural language |
| Setup | `/setup-cobbler` | `$elves setup-cobbler` | scripts | `sync --target omp` |
| Provider shortcuts | `/fugu` … `/omp` | `$elves fugu|…|omp` | same runners | N/A as host (omp is the host) |
| Land PR | `/land-pr` | natural language | natural language | natural language |
| Continuation | optional | optional Codex Goals | host continuity | host session continuity |
| Native / host work | Separate custom/background session; supervised CLI uses safe mode and classifier-approved commits | Separate custom agent or sandboxed `codex exec`; narrow Git roots permit commits | Host-native Grok session or qualified/experimental two-phase worker | Host-native omp session; separate native worker uses run-scoped `--profile` |
| Exact-session prewalk | cached proof, automatic required canary, or explicit experimental mode | same | same | same (omp product `--prewalk` is never Elves prewalk) |
| Visibility | Proven native agent view or exact private-log follow command | Proven native agent view or exact private-log follow command | Live session + run docs; same memory/landing ownership | Live session + run docs; same memory/landing ownership |
| Grok Build goal | proven enhancement or one-packet fallback (worker) | same (worker) | host-native path; goal mode is not a substitute for prewalk | n/a (not Grok) |
| Confidence-guided review | Attach terminal `review_context.review_prompt_block`, or derive the same table from native `Confidence:` trailers | Same machine-produced block/table and Final Readiness output section | Same contract when workers emit trailers/blocks | Same contract when workers emit trailers/blocks |

Claude and Codex read safe worker preferences from the same XDG file and make the same
deterministic decision. Transport syntax differs; packet, authority, fallback, follow, and
terminal-review semantics do not. See [`adaptive-worker-routing.md`](adaptive-worker-routing.md).
When checking a route, pass `--host claude` from Claude Code, `--host codex` from Codex,
`--host grok` from Grok Build, or `--host omp` from Oh My Pi so any native fallback uses the live driver's transport.
Grok as **optional worker** under Claude/Codex is unchanged. Native installs:
`sync_installed_skills.py --apply --target claude|codex|grok|omp`.

Provider shortcuts preserve the same route semantics and authority on both hosts; only Claude Code
installs the four slash aliases. Codex must use the main skill surface. See
[`provider-shortcuts.md`](provider-shortcuts.md). This includes Manus roster modes: Claude's
`/manus --wide|--fanout …` and Codex's `$elves manus --wide|--fanout …` reach the same runner,
coverage contract, manifest, and resume behavior.

The successful trusted full-run terminal response emits the host-neutral
`elves-worker-confidence-review-v1` context. Both hosts attach its `review_prompt_block` verbatim
before primary Final Readiness; native workers use the same shape derived from commit trailers.
Missing/partial signals retain full baseline review, while low confidence, reservations, hidden
reservation counts, and source conflicts require deeper attention. Neither host may use high
confidence to reduce review or gates.

## Exact-session prewalk parity

Normal prewalk is supported only through a behaviorally qualified supervised transport. Required
mode obtains that proof automatically when it is missing. Experimental mode is an explicit,
honestly reported acceptance of qualification uncertainty. Every host must provide the same
guide→meaningful-edit checkpoint→execution lifecycle and make the same user claim; syntax alone is
not parity.

| Concern | Claude Code grammar | Codex grammar | Grok Build grammar | Oh My Pi grammar | Shared requirement |
|---|---|---|---|---|---|
| Fresh identity | caller-generated `--session-id <uuid>` | capture `thread.started.thread_id` | caller-generated `--session-id <uuid>` | capture stream `type=session` `id` | exact ID before transition |
| Guide route | `--model`, `--effort` | `--model`, `model_reasoning_effort` | `--model`, `--effort` | `--model`, `--thinking` (`xhigh`/`max` kept) | explicit guide model/effort |
| Resume | `--resume <uuid>` | `codex exec resume <id>` | `--resume <uuid>` | `--resume <uuid>` | never `--continue`, `--last`, or latest |
| Resume route | model/effort flags with resume | route/sandbox/Git-root flags before `resume` | model/effort flags with resume | model/thinking flags with resume | explicit execution model/effort |
| Route vocabulary | installed help grammar | live `codex debug models` catalog per model | authenticated live catalog | installed help grammar (`xhigh`/`max` kept) | Elves stores no model names; unreadable catalog keeps the offline floor |
| Proof reuse | one canary per execution route, reused for any guide route | same | same | same | guide-phase quality checked per run, not by canary |
| Worktree | supervisor CWD + narrow allowed roots | `-C` on create; supervisor OS CWD on resume | `--cwd` create; resume-sticky sandbox | `--cwd` create and resume; stable worktree-derived `--profile` | exact registered worktree/branch |
| Stream | stream JSON | JSONL | streaming JSON | `--mode json` NDJSON | one redacted logical follow stream with phase labels |
| TODO/checkpoint | native mechanism plus private JSON mirror | native mechanism plus private JSON mirror | private JSON mirror is authoritative | private JSON mirror is authoritative | same bounded provider-neutral schema |
| Instruction fidelity | version-bound behavioral evidence | same | version/build-bound behavioral evidence | version-bound behavioral evidence | honest `pruned`, `turn_scoped`, `retained_safe`, or `unsupported` |
| Git authority | safe mode, `auto` classifier, narrow roots | workspace sandbox, narrow roots | `--permission-mode auto`, narrow roots | `--approval-mode yolo`, narrow roots | no push/protected-ref/PR/merge authority |
| Failure | exact-session recovery | exact-session recovery | exact-session recovery | exact-session recovery | no post-edit cold fallback; same stable codes |

The packet appears only on the guide turn and execution receives only `Continue.`. Static help
fixtures prove advertised create/resume/route flags but not conversation continuity or instruction
pruning. The current persisted-instruction transport activates only for behaviorally proven
`retained_safe`; `pruned` and `turn_scoped` remain schema states for future delivery mechanisms.
Consequently `auto` remains off for an unqualified installed version. `required` runs the bounded
live canary and either records exact-version-and-route proof or stops before task launch with
evidence. `experimental` proceeds only from advertised exact-resume and route-override grammar,
reports `exact_session_experimental`, and retains all real-run continuity checks. No host may
silently start a new session or claim behavioral qualification from static help.
See [`prewalk.md`](prewalk.md).

The host-profile registry also carries the `grok` prewalk arm.
`native-worker prewalk-capabilities --host grok --json` reports installed advertised grammar with
zero model calls, and `route-worker` accepts
`--probe-grok --grok-prewalk-qualification <artifact.json>` so evidence is bound to the installed
version/build. Required mode creates that artifact automatically after the shared canary passes.
The registry still rejects Grok single-phase native-worker launch, while qualified or explicit
experimental prewalk may enter the two-phase supervisor. `allow_grok=false` vetoes regardless of
evidence. This prewalk lane is non-yolo
(`--permission-mode auto`) and distinct from the trusted full-run lane; see
[`grok-open-source-worker.md`](grok-open-source-worker.md).

## Parallelves parity

The Parallelves contract (`references/parallelves.md`) has identical semantics on Claude Code and
Codex: serial default, recommend-only `auto`, the four-gate width test, and the
trunk -> lanes -> integration topology carry no host-specific behavior. The lanes tooling is
deterministic and host-neutral; both hosts invoke it the same way, and the planner's width test
runs through the same CLI's `lanes plan` subcommand:

```bash
python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" lanes plan --plan <path> --timings <json> --json
```

Per-lane worker launches introduce no new invocation grammar: the driver composes the existing
documented per-session full-run commands, one per lane, using each host's grammar exactly as
documented above and in [`adaptive-worker-routing.md`](adaptive-worker-routing.md). Lane workers
follow the same subscription-native default and optional-provider rules as any worker; nothing in
this section launches lanes at runtime.

## v2.24 run-tool parity

The v2.24 helpers (`redrive`, `learnings`, `usage`, `salvage`, `continuity`) have **identical
semantics on Claude Code, Codex, Grok Build, and Oh My Pi**: they are host-neutral CLI helpers invoked as
`python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" <verb> …` with the target repository as
the working directory, on every host. No per-host slash aliases exist for them and none should
be invented; Grok Build reaches them through natural language or direct CLI exactly like the
other hosts. Their honesty boundaries are host-invariant: advisory-only signals, never landing,
merge, credential, or routing authority; the continuity watchdog never activates OS timers on
any host; `HostProfile.reports_usage` records each transport's usage surface honestly, with
absence staying the literal `unobserved` everywhere.

## Do not confuse

- **Codex Goals** — host continuation plumbing for long Codex sessions. Not Grok.
- **Grok Build goal mode** — optional trusted-worker orchestration when capability-proven.
  `/goal status` uses the narrow auth projection and proves command resolution independently of
  catalog lookup and model inference. A validated terminal objective-canary artifact bound to the
  exact installed version/build, canonical session, prompt digest, successful exit, and matching end
  event is required for behavioral goal mode; otherwise the compatible one-packet fallback is
  recorded honestly without disabling an authenticated provider whose core launch capabilities and
  live catalog qualify.

Both hosts apply the same installed-binary capability ledger, caller-generated Grok session UUID,
narrow auth projection, catalog-only model selection, and sanitized streaming follower. See
[`grok-open-source-worker.md`](grok-open-source-worker.md).

## Canonical docs

| Doc | Role |
|-----|------|
| `SKILL.md` | Compact canonical workflow |
| `AGENTS.md` | Thin Codex repository adapter (not a second fork) |
| `README.md` | Operator documentation |
| `references/*` | Runtime, authority, follow, proof, schema details |

Native-only overnight runs require no Grok, OpenRouter, or other external provider.

## Oh My Pi dual role

Oh My Pi is a **supported main driver** (`omp` host; skill root `~/.omp/agent/skills/elves`) and an
optional parked full-run worker (`omp-cli`) plus `/omp` / `$elves omp` shortcut under Claude Code,
Codex, and Grok Build. The host prepares PR state and enforces readiness; the user owns merge
authorization; workers never land. Shortcut uses the
shared isolation snapshot and a single provider-matched API key. Elves prewalk is host-supervised;
omp product `--prewalk` is never Elves prewalk. See `references/omp-worker.md`.
