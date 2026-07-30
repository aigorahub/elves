# Host parity: Claude Code, Codex, and Grok Build

**Supported main drivers are Claude Code, Codex, and Grok Build.** All three share the workflow,
safety kernel, automatic required-mode qualification, explicit experimental mode, and exact-session
prewalk contract.

| Concern | Claude Code | Codex | Grok Build (host) |
|---------|-------------|-------|-------------------|
| Skill load | Project/global Agent Skill | Project/global Agent Skill | Claude-compat and/or native skill discovery |
| Primary invoke | `/elves`, natural language | `$elves`, natural language | natural language (no invented top-level slash map) |
| Cobbler | `/cobbler`, `/cobbler-mode` | `$elves cobbler: …`, natural chat | natural language |
| Setup | `/setup-cobbler` | `$elves setup-cobbler` | natural language / scripts |
| Provider shortcuts | `/fugu`, `/manus`, `/grok`, `/devin` | `$elves fugu|manus|grok|devin …`, natural chat | natural language; same runners from skill root |
| Land PR | `/land-pr` or `\land-pr` | natural language or alias | natural language |
| Continuation | optional | optional **Codex Goals** (seatbelt, not memory) | host session continuity; not Codex Goals |
| Native / host work | Separate custom/background session; supervised CLI uses safe mode and classifier-approved commits | Separate custom agent or sandboxed `codex exec`; narrow Git roots permit commits | Host-native Grok session or qualified/experimental two-phase worker |
| Exact-session prewalk | cached proof, automatic required canary, or explicit experimental mode | same | same |
| Visibility | Proven native agent view or exact private-log follow command | Proven native agent view or exact private-log follow command | Live session + run docs; same memory/landing ownership |
| Grok Build goal | proven enhancement or one-packet fallback (worker) | same (worker) | host-native path; goal mode is not a substitute for prewalk |
| Confidence-guided review | Attach terminal `review_context.review_prompt_block`, or derive the same table from native `Confidence:` trailers | Same machine-produced block/table and Final Readiness output section | Same contract when workers emit trailers/blocks |

Claude and Codex read safe worker preferences from the same XDG file and make the same
deterministic decision. Transport syntax differs; packet, authority, fallback, follow, and
terminal-review semantics do not. See [`adaptive-worker-routing.md`](adaptive-worker-routing.md).
When checking a route, pass `--host claude` from Claude Code and `--host codex` from Codex so any
native fallback uses the live driver's transport. Grok as **optional worker** under Claude/Codex
is unchanged. Native `~/.grok/skills` install remains optional (#88).

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

| Concern | Claude Code grammar | Codex grammar | Grok Build grammar | Shared requirement |
|---|---|---|---|---|
| Fresh identity | caller-generated `--session-id <uuid>` | capture `thread.started.thread_id` | caller-generated `--session-id <uuid>` | exact ID before transition |
| Guide route | `--model`, `--effort` | `--model`, `model_reasoning_effort` | `--model`, `--effort` | explicit guide model/effort |
| Resume | `--resume <uuid>` | `codex exec resume <id>` | `--resume <uuid>` | never `--continue`, `--last`, or latest |
| Resume route | model/effort flags with resume | route/sandbox/Git-root flags before `resume` | model/effort flags with resume | explicit execution model/effort |
| Worktree | supervisor CWD + narrow allowed roots | `-C` on create; supervisor OS CWD on resume | `--cwd` create; resume-sticky sandbox | exact registered worktree/branch |
| Stream | stream JSON | JSONL | streaming JSON | one redacted logical follow stream with phase labels |
| TODO/checkpoint | native mechanism plus private JSON mirror | native mechanism plus private JSON mirror | private JSON mirror is authoritative | same bounded provider-neutral schema |
| Instruction fidelity | version-bound behavioral evidence | same | version/build-bound behavioral evidence | honest `pruned`, `turn_scoped`, `retained_safe`, or `unsupported` |
| Git authority | safe mode, `auto` classifier, narrow roots | workspace sandbox, narrow roots | `--permission-mode auto`, narrow roots | no push/protected-ref/PR/merge authority |
| Failure | exact-session recovery | exact-session recovery | exact-session recovery | no post-edit cold fallback; same stable codes |

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
