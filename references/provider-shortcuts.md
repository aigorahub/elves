# Provider shortcuts

Elves ships five explicit provider shortcuts for focused tasks. They are optional and do
not change the native-first worker default, the supported-host policy, or landing authority.

| Intent | Claude Code | Codex / natural language | Runner |
|---|---|---|---|
| Fugu planning task | `/fugu [--deep\|--ultra\|--max] [--max-wait SECONDS] [--preflight] [--include PATH] <planning-task>` | `$elves fugu [--deep\|--ultra\|--max] [--max-wait SECONDS] [--preflight] [--include PATH] <planning-task>` | `run_fugu.sh` |
| Fugu repository review | `/fugu [--deep\|--cyber\|--ultra\|--max] [--max-wait SECONDS] [--preflight] review <scope>` | `$elves fugu [--deep\|--cyber\|--ultra\|--max] [--max-wait SECONDS] [--preflight] review <scope>` | `run_fugu.sh` |
| Manus web research | `/manus [--wide\|--fanout] …` | `$elves manus [--wide\|--fanout] …` | `run_manus.sh` |
| Grok Build headless task | `/grok <instructions>` | `$elves grok <instructions>` | `run_grok.sh` |
| Devin remote task | `/devin <instructions>` | `$elves devin <instructions>` | `run_devin.sh` |
| Oh My Pi headless task | `/omp <instructions>` | `$elves omp <instructions>` | `run_omp.sh` |

Resolve each runner from the **active Elves skill root**, keep the target repository as the working
directory, validate arguments, and execute only after the user explicitly invokes the matching
shortcut or states the same unambiguous intent. Never invent top-level slash commands for Codex.

## Windows platform contract

All five provider shortcut runners are Bash programs. On Windows, run the host, Elves, and each
shortcut inside WSL2. Native Win32 shortcut execution is not supported. Fugu, Grok, and OMP run
local provider processes over an Elves repository snapshot. They require a qualified Linux
`/usr/bin/bwrap` filesystem sandbox. Manus and Devin start remote provider work. Their shortcut
runners do not use `dispatch_external.py` and do not place the repository in the shared local
sandbox. Their Bash control programs still require WSL2 on Windows.

The external council lanes under Cobbler use `dispatch_external.py`. On Linux and WSL2, those lanes
remain unavailable when the recursive process-boundary gate cannot bind the child generation.
A successful `bwrap` probe does not make that separate council boundary ready.

## Route contracts

- **Fugu:** requires the official `codex-fugu` launcher and its configured Sakana credentials.
  Provider selection and task type are separate. Plain `/fugu <task>` (or `$elves fugu <task>`)
  performs a planning or analysis task without forcing P0-P3 findings or a clean-review verdict.
  The `review` subcommand
  selects the opinionated read-only review: host-generated branch/base/diff evidence, actionable
  P0-P3 findings with exact locations, and exactly `No actionable findings` when clean.

  Both modes use a disposable Git-enumerated snapshot containing policy-admitted tracked files and
  safe non-ignored untracked files. `--include <path>` records a host-selected exact file and
  requires that exact file to survive admission and copy; disappearance or rejection fails closed,
  and the manifest distinguishes requested from admitted paths. It does not override policy.
  Ignored dependency/cache/build trees, every `.env.*` and `*.env` credential-name variant, other
  credential names/suffixes, `.git`, `.elves`, executable agent configuration, symlinks, hard
  links, special files, files owned by another user, out-of-repository paths, and oversized context
  fail closed or remain excluded with bounded diagnostics. Source files cannot occupy the host-owned
  `_elves_context`, `_elves_review`, `_instruction_evidence`, or `_elves_transport` namespaces.
  Prose instruction files move to inert evidence paths. Context is limited to 20,000 files, 512 MiB
  total, and 16 MiB per file. The runner does not paste repository bodies into the prompt; putting
  a file in the snapshot therefore does not itself spend model context. Relevance belongs to the
  host/Fugu task; admissibility remains the safety kernel's decision.

  Every Fugu task is read-only. Fugu is limited to planning and review. The runner rejects
  `--write` before provider launch.

  Every mode requires Elves' qualified kernel filesystem sandbox (`sandbox-exec` on macOS or
  `bwrap` on Linux), isolated HOME/CODEX_HOME, an environment containing only runtime names plus
  the Sakana grant, and a Codex shell policy that does not forward that grant to model-run commands.
  Because macOS forbids nested `sandbox-exec`, Codex's documented externally-sandboxed mode is used
  only after the outer boundary is active. Linux omits procfs so model-directed commands cannot
  inspect the credential-bearing parent. The Linux lane supplies only a synthetic
  `/proc/self/exe` symlink to the qualified, narrowly mounted real Codex binary so Codex can resolve
  its own executable and configuration; no process directories or environments are mounted.
  Regular and deep calls use ephemeral one-shot sessions.
  Ultra uses a resumable session confined to the lane: it captures the exact `thread.started` id
  and reserves part of the hard wall limit for a no-more-tools synthesis turn on that exact id when
  exploration does not finish first. It never uses ambiguous `--last` state; raw events, the
  final-message output, and session state are destroyed with the lane. Ultra events cross a bounded
  host-owned pipe, and the final-message inode is opened once with no-follow semantics; host parsing,
  reads, and truncation never reopen provider-controlled names. A live monitor covers snapshot, HOME, tmp, and
  XDG writable state; defaults allow at most 20,000 additional filesystem entries, 256 MiB
  aggregate growth, and 64 MiB per file before the provider is terminated and the result rejected.
  After every provider phase settles, the monitor joins and a final descriptor-safe audit runs
  before any output is accepted.
  Traversal tolerates only benign ENOENT/rename races from disappearing temporary generations;
  permissions, ownership, unsupported types, and other audit failures remain fail-closed, and links
  are never followed. Every profile closes input, disables launcher notices/updates, and has a hard
  wall-clock limit. macOS read-only
  mode uses best-effort native-bound cleanup of observed processes; polling cannot prove recursive
  absence and is never process-containment authority. The supported profiles are:

  | Shortcut | Model / effort | Default wall limit | Use |
  |---|---|---:|---|
  | plain profile (host may choose after routing) | `fugu` / `high` | 10 minutes | routine planning or explicit review |
  | `--deep` | `fugu` / `xhigh` | 20 minutes | harder planning, analysis, or review |
  | `--cyber` | `fugu-cyber` / `xhigh` | 20 minutes | read-only security review or threat model |
  | `--ultra` | `fugu-ultra-v1.1` / `high` | 30 minutes total; at most 20 minutes exploring by default | compact high-stakes task with a reserved synthesis phase |
  | `--max` | `fugu-ultra-v1.1` / `max` | 60 minutes total; at most 20 minutes exploring by default | one narrow, high-stakes gate worth the deepest reasoning tier |

  This table is the **runner flag → model/effort map**. Plain regular Fugu is the default for a
  flagless call. The host may select `--cyber` only when the user asks for a security review or
  threat model after a successful Cyber call in the current session. Only a user-explicit
  `--cyber` request may establish that proof. A catalog entry does not prove account access.
  Otherwise, use regular Fugu. The user must explicitly select `--ultra` or `--max`. The host chooses task mode,
  profile, and `--include` context before launch. See **Host routing
  when the user says "use Fugu"** below. The runner does not score complexity; it only executes
  the selected profile.

  Sakana's Fugu-Ultra v1.1 release (2026-07-24) ships at the same price as v1.0 and changes two
  facts the shortcut depends on. The published catalog slug is now `fugu-ultra-v1.1`, and plain
  `fugu-ultra` — the only ultra slug older bundles listed — survives just as an accepted API alias.
  Because the runner hands the installed `fugu.json` to the isolated launcher, the `--ultra` lane
  resolves its model against that catalog instead of hard-coding one spelling: it prefers
  `fugu-ultra-v1.1`, accepts the equivalent `fugu-ultra` alias when a legacy bundle publishes only
  that, and otherwise keeps `fugu-ultra-v1.1` so the provider stays authoritative over its own
  aliases. `fugu-ultra-v1.0` is deliberately never selected — it is a different model, and silently
  running it would misreport the lane. And `max` is a genuinely distinct third effort level **on
  `fugu-ultra-v1.1` only** — `fugu`,
  `fugu-ultra-v1.0`, and `fugu-cyber` still accept `max` purely as a compatibility alias that maps
  to `xhigh`. `--deep` therefore keeps naming `xhigh` explicitly. A general invocation with no task
  is rejected; use `review` with no scope to review the current repository changes.

  **The `--max` lane.** v2.16.0 documented v1.1's third effort level but deliberately exposed no
  lane for it, on the reasoning that `--ultra`'s value is its reserved exact-session synthesis
  inside a bounded wall limit and a `max` lane would change the budget rather than the task shape.
  Field use since then argues the other way: `fugu-ultra` at `max` is worth the wall time for a
  single narrow, high-stakes gate — a proof step, a security-sensitive review, a decision that has
  to be right the first time — provided the prompt is narrow and the timeout is long. `--max`
  therefore keeps everything that makes `--ultra` useful (the same versioned model, catalog
  resolution, the reserved synthesis phase, the same context and audit rules) and changes only the
  effort level and the default wall budget, which doubles to 60 minutes. It is deliberately not the
  default for anything: at this tier the useful question is whether one specific answer is worth an
  hour, and a broad task is the wrong shape for it. Profiles remain mutually exclusive, so
  `--ultra --max` is rejected rather than silently resolved.

  Because `max` is real only on `fugu-ultra-v1.1`, a legacy bundle whose catalog publishes only the
  floating `fugu-ultra` alias will have the provider map `max` down to `xhigh`. That is the
  provider's documented compatibility behavior, not a silent Elves downgrade, and the lane still
  reports the effort it asked for.

  **Wall limits here are wall limits.** Sakana tooling elsewhere exposes a `--stream` timeout that
  is an idle/SSE timeout rather than a wall-clock bound, so a Max or Ultra call that keeps emitting
  heartbeats can run indefinitely under it and needs a separate cap. Every profile above is bounded
  by a hard wall-clock limit that covers exploration, the reserved synthesis phase, and cleanup;
  when it expires the lane is terminated and the result rejected. Raise it deliberately with
  `SAKANA_FUGU_MAX_WAIT_SECONDS` rather than assuming a stream setting will bound the call.

  **Claude Code-compatible Fugu endpoint.** Sakana now also fronts Fugu with Claude Code-compatible
  endpoints and a `claude-fugu` launcher alongside `codex-fugu`. Claude Code points at it through
  `ANTHROPIC_BASE_URL="https://api.sakana.ai"` plus `ANTHROPIC_AUTH_TOKEN` (a `fish_…` bearer
  token, **not** `ANTHROPIC_API_KEY`), and maps Anthropic tiers onto Fugu models:
  `ANTHROPIC_DEFAULT_OPUS_MODEL="fugu-ultra[1m]"`, `ANTHROPIC_DEFAULT_SONNET_MODEL="fugu[1m]"`,
  `ANTHROPIC_DEFAULT_HAIKU_MODEL="fugu[1m]"`, the access-gated
  `ANTHROPIC_DEFAULT_FABLE_MODEL="fugu-cyber[1m]"`, and `CLAUDE_CODE_SUBAGENT_MODEL="fugu[1m]"`.
  The `[1m]` suffix is that interface's 1M-context model naming and belongs only there; the
  `codex-fugu` lane keeps the bare catalog slugs above.

  This shortcut deliberately stays on `codex-fugu`. Elves' Fugu safety kernel — the disposable
  Git-enumerated snapshot, the isolated `CODEX_HOME`, the Codex shell policy that withholds the
  Sakana grant from model-run commands, and the externally-sandboxed mode — is qualified against
  Codex semantics, and none of it transfers to a different launcher by analogy. Operators may run
  `claude-fugu` directly as their own driver; that is a host choice outside this shortcut and
  outside Elves' audited lane. Sakana also documents cosmetic Claude Code mismatches that matter
  when reading a run: the six-stop effort slider (`low` through `ultracode`) collapses onto Fugu's
  `high`/`xhigh` boundary, so Elves' effort names are not authoritative on that route; Sonnet and
  Haiku both resolve to `fugu[1m]`, so the model picker shows duplicate rows; and session-header
  billing labels reflect API-token usage. The `claude-fugu` launcher does not auto-update, so new
  Fugu models reach it only after a manual update.
### Host routing when the user says "use Fugu"

Natural language such as "use Fugu", "ask Fugu", or `/fugu <task>` without a profile flag uses
plain `fugu/high` by default. The host may select `--deep` when regular Fugu needs xhigh effort.
The host may select `--cyber` only for explicit security review or threat-model intent after a
successful Cyber call in the current session. Only a user-explicit `--cyber` request may establish
that proof. Otherwise, use regular Fugu. The user
must explicitly select `--ultra` or `--max`. Never upgrade to Ultra or Max from task complexity.

**Always-true isolation facts.** Every successful Fugu launch uses a disposable
kernel-isolated Git-enumerated snapshot. That **isolation snapshot is not optional** and is not a
second product the host can skip. What the host chooses is whether Fugu is needed, planning or
review mode, the allowed profile, and extra context via `--include`.

State one short `Fugu route: …` line before every launch.

#### One decision path (do this in order)

1. **Should Fugu run at all?** Host-native first for inventory, greps, CHANGELOG/TODO triage, ticket
   classification, and anything the driver can finish with `rg`/`git`/`gh` in under about a minute.
   Explicit "use Fugu" authorizes paid usage only when the host records a remaining planning or
   review question that needs high reasoning on a snapshot. It does **not** authorize
   merge or protected-ref work. If the user named Fugu for a broad inventory, do the first pass
   host-native and reserve Fugu for contested rows only (state that in the route line). Do not invent
   an unprompted paid Fugu launch from this section alone.

2. **Task mode.** Default to planning or analysis. Use
   `review <scope>` only when the user asked for a review/audit/PR-diff with the P0-P3 contract.
   Scope narrowly (paths, PR, or "current changes"). Never unbounded whole-repo tours when the ask
   is focused.

3. **Profile.** Profiles are mutually
   exclusive; never pass two. Choose by **deliverable shape**, not by "how hard it sounds."

   | Signals | Choose | Model / effort | Default wall | On wall timeout |
   |---|---|---|---:|---|
   | Default for almost everything; first paid call; narrow Q&A that finishes inside the wall | plain (no flag) | `fugu` / `high` | 10m | killed; **nothing returned** |
   | After plain failed or returned a thin answer; multi-module planning that needs xhigh effort | `--deep` | `fugu` / `xhigh` | 20m | killed; **nothing returned** |
   | Explicit security review or threat model | `--cyber` | `fugu-cyber` / `xhigh` | 20m | killed; **nothing returned** |
   | User explicitly asks for Ultra | `--ultra` | `fugu-ultra-v1.1` / `high` | 30m | synthesis phase still runs |
   | User explicitly asks for Max | `--max` | `fugu-ultra-v1.1` / `max` | 60m | synthesis phase still runs |

   **Hard rules.** Explicit user flags always win. Only the host-selected Cyber exception may
   change the plain default. Do not pick `--deep` for backlog triage, issue
   classification, or CHANGELOG archaeology. Do not pick `--ultra`/`--max` for greps, renames, or
   single-file Q&A. Do not pick `--max` for broad multi-goal work; split the work. Prefer a
   **second plain call** over one broad deep call. Prefer plain + `--max-wait SECONDS` over
   automatic `--deep` when you only need more wall, not higher effort. A `--deep` run that dies
   at the wall spent its whole budget and returned nothing; that is worse than a narrower plain
   call or an `--ultra` report that reserves synthesis time. Field reports (2026 public use,
   Sakana/Codex operator notes, and Elves dogfood): Ultra/Max often take 20–60+ minutes and hit
   subscription limits mid-flight when prompts are open-ended; keep those lanes narrow. Day-1
   mistake: do not crank effort to max for everything. The host cannot pick an arbitrary model
   slug: the profile table is the map; Ultra/max resolve `fugu-ultra-v1.1` from the installed
   catalog (never silent `fugu-ultra-v1.0`).

4. **Write mode.** Fugu is limited to planning and read-only review. The runner rejects `--write`.

5. **Context and `--include`.** The default admitted snapshot already has policy-admitted tracked
   files and safe non-ignored untracked files. The runner does not paste file bodies into the
   prompt. Still put **path names and the success shape in the task string** so the model does not
   wander the tree. Add `--include PATH` only for host-selected files that must be admitted (fresh
   untracked notes, specific configs). **Never** include secrets, `.env*` / `*.env`, ignored trees
   (for example `docs/audit/`), `.git`, `.elves`, or executable agent config: fail closed with a
   remediation hint **before** the provider launches. Put host notes at a **repo-root untracked**
   path if you need a roster. **If any `--include` is present, run `--preflight` first** and only
   launch when `include_admitted` lists the path. Prefer a few exact includes over inventing a
   "minimal snapshot" product that does not exist.

6. **Prompt shape (what current agent guides converge on).** Write one precise question or ranked
   review scope. Name all of: **goal**, **paths or surfaces**, **constraints / out of scope**,
   **done-when** (tests, build, or report shape), and **verification** the model can run or the
   host will re-check. For reviews: rank areas highest-value first, exclude findings the host
   already fixed, require ordered P0-P3 with `file:line` and an explicit "nothing at this level"
   when clean. Separate host-native research from the paid Fugu call: explore and thin the packet
   first, then launch. Ultra/max must stay tight. Do not re-force the review rubric on a general
   task. After settlement, treat Fugu findings as **leads**: re-read cited lines host-native before
   implementing. Longer field notes and the failed-vs-succeeded review dogfood:
   `references/fugu-calling-guide.md`.

#### Copy-paste route lines

```text
Fugu route: host-native only (no launch) — inventory/triage
Fugu route: planning plain, no include, wall 10m
Fugu route: planning plain --max-wait 900, no include
Fugu route: planning plain --preflight --include NOTE.md (launch only if admitted)
Fugu route: review main...HEAD plain, paths: scripts/foo.py tests/test_foo.py
Fugu route: review main...HEAD --deep (only after plain failed on this tip)
Fugu route: security review main...HEAD --cyber
Fugu route: review main...HEAD --ultra (user selected Ultra)
```

#### Wait, poll, capture, cancel, salvage, and cleanup (operational)

Wall limits are hard walls (not stream idle timeouts). While a launch runs:

- **Redirect to a file.** `run_fugu.sh … > fugu.log 2>&1`. Never pipe through `| tail` or
  `| head`: those buffer until the stream closes, so mid-run progress is invisible and a
  timeout often yields only a truncated exploration trace. Read the log live if needed.
- Do **not** treat "host stopped waiting on the log" as "Fugu stopped." The provider may keep
  burning until wall or exit.
- Prefer one long wait up to the profile wall (or `--max-wait`) over cancel/relaunch loops.
- Intermediate tool spam is normal until settlement. Exit 0 prints the clean final answer.
- **Timeout/crash salvage.** On wall timeout (124), provider crash, or incomplete Ultra
  synthesis, the runner prints any captured partial agent text between
  `--- Fugu partial salvage (…; incomplete) ---` markers on stdout when something usable was
  captured. The exit code stays non-zero. Hosts must harvest that text before relaunching so a
  paid call is not fully wasted. Empty salvage means the provider never emitted text: narrow
  the prompt or raise `--max-wait`, do not silent-escalate to `--max`.
- To stop spend, kill the `run_fugu.sh` / isolation / `codex-fugu` process group deliberately; do
  not assume chat cancel reaps the lane. Confirm with process listing if needed.
- On exit 2 with `isolation_requested_path_*`, fix the path or drop `--include`, then preflight
  again. Do not retry the same include.
- On exit 124 / wall timeout: first read salvage from the log. Then narrow the task or raise
  `--max-wait`. Use `--ultra` only if the user explicitly selected Ultra.
- **Cleanup.** Isolation lanes are removed on normal exit. Keep `fugu.log`. Delete inspected
  legacy write handoffs under `/tmp/elves-fugu-handoff-*` if an older runner left them. After a
  hard kill, remove only owned leftover `elves-iso-*` temp dirs with no live process. Details:
  `references/fugu-calling-guide.md` sections 7–8.

After settlement, report Fugu's answer or salvage and the route used.

### Review snapshot media policy (all harnesses and hosts)

Read-only review snapshots omit oversized binary media instead of failing the whole review. A
course repository with a 300 MB MP4, a 90 MB WAV, or a 40 MB PPTX used to fail the shared snapshot
before Fugu or Grok ever started; those files are now left out and the review runs.

- **Omitted:** video, audio, presentation, archive, image, font, and 3D binaries whose size is above
  the per-file limit. Classification is by extension only, so `notes.mp4.md` is prose, not media.
- **Not omitted, still fail closed:** source, prose instructions, executable agent configuration,
  and any path named by `--include`. The failure carries a remediation that asks for a derived text,
  image, or transcript artifact (a transcript `.md`, an extracted slide outline, a downsampled
  still) committed next to the binary and requested instead.
- **The 16 MiB per-file limit is not raised.** Omission is a read-only review behavior, not a bigger
  budget. Writable lanes keep fail-closed behavior, because an omitted path would read as a deletion
  in the handoff audit.
- **Recorded:** the context manifest (`_elves_context/manifest.json`) lists each omitted path, byte
  size, category, reason, and remediation under `omitted_files`, plus `omitted_file_count`,
  `omitted_bytes`, and `omit_oversized_media`. The same entries appear as `status: "omitted"`
  diagnostics, and every runner prints the same omission block before launch.

### Fugu is optional: review route fallback

Fugu is one optional review route, not the review. When a route is unavailable because of quota,
authentication, catalog, runner, timeout, or provider failure, probe the supported review routes and
select another available independent reviewer instead of stopping.

1. Preserve an explicit user route when it works.
2. Otherwise select the first available independent optional provider (`fugu`, `grok`, `omp`,
   `council`), skipping the implementer so the review stays independent.
3. Prefer a supported native reviewer when no optional provider works.
4. Record requested route, actual route, and fallback reason.
5. Do not claim a review ran when it did not. A selected route is not a completed review.
6. Do not let optional-provider failure block the run while a qualified review route exists. Only a
   required review with no route at all blocks.

The optional runners print one directive line on any non-zero exit
(`… review route unavailable [<reason>]: select another available review agent …`). The host-neutral
selector is:

```bash
python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" review-route \
  --host claude-code --requested fugu --unavailable fugu=quota --available grok --json
```

`--host` is one of `claude-code`, `codex`, `grok-build`, `omp`. Reasons are `quota`,
`authentication`, `catalog`, `runner`, `timeout`, or `provider`. Exit `0` selected a route, `3`
reports no route without blocking, and `1` blocks only with `--required` and no route at all.

### Other provider route contracts

- **Manus:** requires `MANUS_API_KEY`. The ordinary form creates one private `manus-1.6-max` task
  through `https://api.manus.ai/v2/task.create` with `x-manus-api-key`, explicitly empty
  `message.connectors`, `message.enable_skills`, and `message.force_skills`, then polls with a
  bounded timeout. No connector or forced-skill IDs are explicitly granted. Manus documents that
  empty `enable_skills` loads account-default enabled skills, however, so the shortcut does not
  promise skill isolation. Roster forms add Cobbler-managed Wide Research or deterministic fan-out
  as described below.
- **Grok:** requires the `grok` CLI plus explicit `XAI_API_KEY` (or the legacy
  `GROK_CODE_XAI_API_KEY`). It uses documented headless single-prompt mode, `high`
  reasoning by default, and `dontAsk`, which silently denies unapproved mutations. The runner
  copies tracked source into a disposable snapshot and requires Elves' qualified outer kernel
  sandbox, which makes that snapshot read-only independently of Grok's profile merger. It constructs
  isolated HOME/GROK_HOME state, projects only the selected named key to Grok itself, and selects a
  dedicated shell that unsets both supported key names before every model-directed terminal command.
  Grok also runs its built-in inner `strict` profile for narrow reads and Linux child-network
  restriction; it does not add a custom read-deny profile because Grok implements that profile with
  a nested Linux bwrap that would recreate procfs. The outer snapshot policy removes credential and
  executable configuration paths instead. The
  runner writes `permissions.defaultMode: dontAsk` to isolated Claude-compatible settings (the
  similarly named CLI flag does not activate this mode) and locks bypass mode off in isolated Grok
  requirements. The required outer sandbox fails closed.
  Shared-file OAuth is deliberately unsupported by the shortcut: Grok applies the profile to
  provider authentication reads as well as model tools, so a file grant would expose the credential
  and a deny would prevent authentication. It
  does not invent a model id; the authenticated live Grok configuration selects the available
  model.
  The runner builds argv from the flags the installed Grok Build CLI advertises: an absent safety
  flag (isolated `--cwd`, inner `--sandbox strict`, headless `--single`, `--output-format`,
  explicit reasoning effort) fails closed, while a quality flag the installed version dropped is
  simply not passed. Auto-update is disabled through the isolated `[cli] auto_update` config key
  rather than a removed flag. Reasoning effort defaults to `high`; `ELVES_GROK_EFFORT` selects
  `low`, `medium`, `high`, or `xhigh`, and `ELVES_GROK_MODEL` pins a model only when the
  authenticated live catalog lists it. The runner reports the CLI version, effort, model, the
  authentication route the CLI itself names, and any omitted flags.
- **Devin:** requires `DEVIN_API_KEY`. It creates a remote session through the official
  `https://api.devin.ai/v1/sessions` API, includes the current origin/branch when available, sends
  empty `secret_ids` and `knowledge_ids`, and polls the documented session endpoint with each
  creation and poll request, including its bounded response-body read, interrupted at the same hard
  wall-clock deadline. A zero wait explicitly means create-and-return, so creation retains its
  standalone hard request timeout in that mode.

## Cobbler-managed Manus rosters

Use a roster when the research goal has independently checkable units such as one paper reference,
company, dataset, or jurisdiction per worker. Cobbler stays the outer orchestrator and Manus is a
bounded research subsystem:

```text
/manus --wide --items-file references.json --file draft.pdf audit every cited reference
/manus --fanout --items-file references.json audit every cited reference
/manus --resume .elves/runtime/manus/<manifest>.json
```

Codex uses the same arguments after `$elves manus` or an unambiguous natural-language request. A
roster is a JSON list of ids or an object containing an `items` list. An item may add bounded,
item-specific instructions:

```json
{
  "items": [
    {"id": "smith-2024", "instructions": "Verify the theorem attributed in section 2."},
    {"id": "lee-2025", "instructions": "Check the dataset size and license."}
  ]
}
```

`--wide` performs this transaction:

1. Create one private Max task with the exact roster, a request for native Wide Research, and a
   structured coverage schema.
2. Reconcile returned ids and reject missing, duplicated, failed, or malformed item results.
3. Create deterministic private repair tasks only for uncovered items, unless `--no-fallback` was
   requested.
4. Upload the validated per-item packet to a fresh synthesis task only after coverage is exact.

Manus documents Wide Research as automatically triggered; its public Task API does not document a
`wide_research` force switch, a create-child-subtask operation, or parent-linked enumeration of the
internal Wide workers. Therefore a prompt claiming “one subagent per reference” is a request, not
proof. The roster result is accepted only after Cobbler's structured coverage check. `--fanout`
skips the native attempt and guarantees one independently tracked top-level Manus task per roster
item, then creates one synthesis task. It is the predictable choice when task identity matters more
than letting Manus choose its internal topology.

The roster is capped at 250 items. Deterministic creates are spaced by 6.1 seconds by default to
respect Manus's documented 10-create-per-minute limit. Poll and create intervals must be at least
0.1 seconds, preventing accidental zero-delay request loops. Each create is recorded immediately in
an atomic mode-0600 manifest under the gitignored `.elves/runtime/manus/` directory. Explicit
manifest paths must remain inside that tree, are traversed component-by-component without following
symlinks, and may not already exist; the destination is exclusively reserved before any attachment
upload or provider task call.
Continue an existing record only through `--resume`. Resume paths have the same confinement.
`--resume` reuses successful or still-live ids and fills only unrecorded work. A known terminal
`error` is
archived in bounded `failed_task_attempts` history and only its failed repair, fan-out, or synthesis
step is recreated on an explicit resume. A synthesis failure emits the already validated per-item
rows before returning failure, so paid research is never hidden behind a failed final summary.

Any native, repair, or fan-out task that enters `waiting` returns control without starting new paid
work. Exit 4 means coverage remains incomplete with no task waiting, 3 means Manus is waiting, 1
means a remote task failed, and 124 means the local wait expired while recorded remote work may
still be live. Ambiguous connection/5xx failures on paid mutations are not automatically retried
because the public API documents no idempotency key; explicit pre-acceptance 425/429 responses may
back off safely. Idempotent reads retry bounded transient failures. API responses and presigned
upload responses use bounded reads under hard wall-clock alarms; a slow byte trickle cannot extend
the configured local deadline.

`--file <path>` uploads only that explicit regular file through Manus's presigned file flow and
attaches its provider id to the task. Repeat it for multiple sources. Credential-like paths are
refused, including symlinks, common credential directories and filenames, and private-key/archive
suffixes such as `.key`, `.pem`, `.p12`, and `.pfx`; repository data-governance policy remains the
real gate. There is no implicit repository upload or project access. Provider file ids expire after
48 hours, so start or resume attachment-dependent fallback within that window. The manifest can
contain prompts, local attachment paths, provider ids, and research output, but never the API key;
it remains local and ignored.

Relevant official surfaces: [Wide Research behavior](https://help.manus.im/en/articles/11960169-what-is-wide-research),
[create a task](https://open.manus.im/docs/v2/task.create),
[upload a file](https://open.manus.im/docs/v2/file.upload),
[list task messages](https://open.manus.im/docs/v2/task.listMessages), and
[API rate limits](https://open.manus.im/docs/v2/rate-limits).

`SAKANA_FUGU_MAX_WAIT_SECONDS` can replace a profile's wall limit with another finite, positive
number of seconds. For Ultra only, `SAKANA_FUGU_ULTRA_EXPLORE_SECONDS` can replace the exploration
phase, but it must be finite, positive, and low enough that the dynamically reported cleanup and
synthesis reserves still fit inside the total. A timeout attempts bounded whole-group cleanup
inside that same wall budget. Exit 124 means the provider or phase timed out and group cleanup
reaped the launcher; exit 125 means cleanup authority or reap could not be proven without exceeding
the budget, so the shortcut fails closed instead of reporting an ordinary completed timeout.
The runner intentionally does not use a direct API fallback: `codex-fugu` owns Sakana transport,
stream resilience, project instructions, and model-catalog compatibility. Official launcher
installation and command details are at
[`console.sakana.ai/get-started`](https://console.sakana.ai/get-started) and
[`SakanaAI/fugu`](https://github.com/SakanaAI/fugu/blob/main/docs/commands_details.md).

Fugu project access is a policy-admitted tracked plus non-ignored-untracked snapshot; Grok remains
a tracked-source snapshot. Neither is the host checkout. Ignored dependency/cache/build trees,
`.git`, `.elves`, executable agent configuration, unsafe file types/links, and ordinary credential
stores remain absent and outside the kernel boundary. Both Linux boundaries omit procfs so
model-directed commands cannot inspect the credential-bearing parent environment. Fugu's Linux
lane adds only a synthetic `/proc/self/exe` symlink to the qualified real Codex binary; Grok's
Linux lane has no `/proc` view. On macOS, native
temp/cache traversal receives metadata-only `/var` access and a standalone Codex binary receives
only its active immutable versioned runtime; sibling host file data remains denied. Repositories
must still apply their provider/data-governance policy before invoking either optional paid route.

`MANUS_MAX_WAIT_SECONDS=0` and `DEVIN_MAX_WAIT_SECONDS=0` provide create-and-return behavior. In a
Manus roster mode the printed manifest, rather than “last task,” is the authoritative follow and
resume surface. A bounded local timeout does not cancel the remote task; the printed task/session
URL remains the ordinary follow surface. API base overrides exist only for hermetic testing and
controlled proxies.

These routes can consume paid provider capacity. They never grant merge, protected-ref, secret,
or approval-bypass authority, and their output remains evidence for the supported Claude Code or
Codex driver to review.


## Oh My Pi (`omp` shortcut / worker route)

- Runner: `scripts/run_omp.sh` (Claude `/omp`, Codex/Grok `$elves omp` or natural language).
- CLI binary is **`omp`** only (never `opm`). This shortcut is the **optional worker** path under
  Claude/Codex/Grok (adapter `omp-cli` for parked full-run labor). The host token **`omp`** is a
  supported main driver when the user opens omp with the managed skill root; do not confuse the
  two roles. See [`omp-worker.md`](omp-worker.md).
- Isolation: shared `isolated_lane` snapshot + single provider-matched API key via `ELVES_OMP_MODEL`.
- Read-only shortcut; `ELVES_OMP_WRITE` is rejected. Implementation labor uses full-run `omp-cli`.
