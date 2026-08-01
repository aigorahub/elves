# Provider shortcuts

Elves ships four explicit convenience routes for focused provider tasks. They are optional and do
not change the native-first worker default, the supported-host policy, or landing authority.

| Intent | Claude Code | Codex / natural language | Runner |
|---|---|---|---|
| General Fugu task | `/fugu [--deep\|--ultra\|--max] [--max-wait SECONDS] [--preflight] [--write] [--include PATH] <task>` | `$elves fugu [--deep\|--ultra\|--max] [--max-wait SECONDS] [--preflight] [--write] [--include PATH] <task>` | `run_fugu.sh` |
| Fugu repository review | `/fugu [--deep\|--ultra\|--max] [--max-wait SECONDS] [--preflight] review <scope>` | `$elves fugu [--deep\|--ultra\|--max] [--max-wait SECONDS] [--preflight] review <scope>` | `run_fugu.sh` |
| Manus web research | `/manus [--wide\|--fanout] …` | `$elves manus [--wide\|--fanout] …` | `run_manus.sh` |
| Grok Build headless task | `/grok <instructions>` | `$elves grok <instructions>` | `run_grok.sh` |
| Devin remote task | `/devin <instructions>` | `$elves devin <instructions>` | `run_devin.sh` |

Resolve each runner from the **active Elves skill root**, keep the target repository as the working
directory, validate arguments, and execute only after the user explicitly invokes the matching
shortcut or states the same unambiguous intent. Never invent top-level slash commands for Codex.

## Route contracts

- **Fugu:** requires the official `codex-fugu` launcher and its configured Sakana credentials.
  Provider selection and task type are separate. Plain `/fugu <task>` (or `$elves fugu <task>`)
  performs a general task and returns the requested analysis, design, investigation, or other
  deliverable without forcing P0-P3 findings or a clean-review verdict. The `review` subcommand
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

  General tasks are read-only by default. `--write` is valid only for a general task and requires
  independent implementation authority from the surrounding user request. It is enabled only when
  the qualified outer boundary is Linux bwrap with a PID namespace that proves recursive teardown;
  it fails before provider launch on macOS and any platform without that boundary. A qualified
  write changes the outer boundary from read-only to writable for the disposable snapshot only.
  After successful PID-namespace teardown, the host compares a pre-task digest-and-mode baseline
  with a second no-follow audit. Credential-bearing, protected/ignored/instruction, symlink,
  hard-link, special,
  unsafe-directory, unsafe-mode, over-count, or oversized output fails closed. Mode-only changes
  and new executable files are represented in the manifest; exported file bodies stay private at
  mode 0600 or owner-executable 0700. Accepted changed regular files and deletion records enter a
  fresh inert `/tmp/elves-fugu-handoff-*` bundle with a JSON manifest (at most 2,000 changed files
  and 64 MiB). The host checkout is never edited, and the handoff is never applied automatically.

  Every mode requires Elves' qualified kernel filesystem sandbox (`sandbox-exec` on macOS or
  `bwrap` on Linux), isolated HOME/CODEX_HOME, an environment containing only runtime names plus
  the Sakana grant, and a Codex shell policy that does not forward that grant to model-run commands.
  Because macOS forbids nested `sandbox-exec`, Codex's documented externally-sandboxed mode is used
  only after the outer boundary is active. Linux omits procfs so model-directed commands cannot
  inspect the credential-bearing parent. Regular and deep calls use ephemeral one-shot sessions.
  Ultra uses a resumable session confined to the lane: it captures the exact `thread.started` id
  and reserves part of the hard wall limit for a no-more-tools synthesis turn on that exact id when
  exploration does not finish first. It never uses ambiguous `--last` state; raw events, the
  final-message output, and session state are destroyed with the lane. Ultra events cross a bounded
  host-owned pipe, and the final-message inode is opened once with no-follow semantics; host parsing,
  reads, and truncation never reopen provider-controlled names. A live monitor covers snapshot, HOME, tmp, and
  XDG writable state; defaults allow at most 20,000 additional filesystem entries, 256 MiB
  aggregate growth, and 64 MiB per file before the provider is terminated and the result rejected.
  After every provider phase settles, the monitor joins and a final descriptor-safe audit runs
  before any output or handoff is accepted.
  Traversal tolerates only benign ENOENT/rename races from disappearing temporary generations;
  permissions, ownership, unsupported types, and other audit failures remain fail-closed, and links
  are never followed. Every profile closes input, disables launcher notices/updates, and has a hard
  wall-clock limit. Linux writable mode uses authoritative PID-namespace teardown. macOS read-only
  mode uses best-effort native-bound cleanup of observed processes; polling cannot prove recursive
  absence and is never handoff authority. If a writable boundary cannot be proven, the shortcut
  fails before provider launch. The supported profiles are:

  | Shortcut | Model / effort | Default wall limit | Use |
  |---|---|---:|---|
  | plain profile (host may choose after routing) | `fugu` / `high` | 10 minutes | routine general task or explicit review |
  | `--deep` | `fugu` / `xhigh` | 20 minutes | harder analysis, implementation, or review |
  | `--ultra` | `fugu-ultra-v1.1` / `high` | 30 minutes total; at most 20 minutes exploring by default | compact high-stakes task with a reserved synthesis phase |
  | `--max` | `fugu-ultra-v1.1` / `max` | 60 minutes total; at most 20 minutes exploring by default | one narrow, high-stakes gate worth the deepest reasoning tier |

  This table is the **runner flag → model/effort map**, not a claim that every bare invocation
  must stay on plain. Flagless `/fugu` / `$elves fugu` / natural-language "use Fugu" is
  **host-routed**: the host chooses task mode, profile (locks model + effort), write mode, and
  `--include` context before launch, preferring the cheapest matching lane. See **Host routing
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

Natural language such as "use Fugu", "ask Fugu", or `/fugu <task>` **without** an explicit
profile flag is **not** a request to always run bare `fugu/high`. The host agent (Claude Code or
Codex) must choose the lane before launch, then invoke `run_fugu.sh` with the matching flags.
`run_fugu.sh` itself does not score complexity: it only executes the profile the host selects.

**Always-true isolation facts.** Every successful Fugu launch uses a disposable
kernel-isolated Git-enumerated snapshot. That isolation snapshot is not optional and is not a
second product the host can skip. What the host *does* choose is (1) whether Fugu is the right
provider at all, (2) task mode, (3) profile (which locks model + effort + wall budget), (4) write
mode, and (5) extra context via `--include`.

Decide in this order, then state the choice in one short line before launch
(example: `Fugu route: general plain, default admitted snapshot, preflight ok`):

### Fugu economy (benefit without the hassle)

Fugu is paid wall time behind a fail-closed snapshot. Most host failures are **routing
mistakes**, not provider defects. Apply this economy before every launch:

1. **Host-native first.** Inventory, greps, CHANGELOG/TODO classification, ticket triage against
   main, and answers already visible in open files stay host-native. Do not spend a Fugu wall on
   work the driver can finish with `rg`/`git`/`gh` in under a minute.
2. **Narrow the packet before raising the profile.** One contested finding, one module, or one
   PR scope beats a 29-item backlog dump at `--deep`. Prefer a second plain call over one broad
   deep call.
3. **Default plain (`fugu` / `high`, 10m).** Upgrade only when the remaining question is multi-module
   design, security-sensitive correctness, or a true high-stakes gate. Do not treat "many files in
   the repo" as automatic `--deep`.
4. **Cap wall with `--max-wait SECONDS` before upgrading profile.** A tight plain task that needs
   12 minutes should use plain + `--max-wait 900`, not a 20-minute deep launch.
5. **Preflight before paid work when includes or write mode are non-trivial.**
   `run_fugu.sh --preflight …` validates launcher, profile, wall, write eligibility, and every
   `--include` path, then exits without calling the provider. Use it after drafting a non-obvious
   route, or when the host is unsure a path is admissible.
6. **Never `--include` gitignored paths.** Paths under ignored trees (for example `docs/audit/`)
   fail closed before launch. Put host notes at a non-ignored path (repo-root untracked file is
   fine) or rely on the default admitted snapshot.

1. **Should Fugu run?** Prefer host-native tools for trivial lookups the driver can answer from
   open files. Inside this section the user already named Fugu or an equivalent provider shortcut;
   use that explicit intent to run a bounded high-reasoning pass when the task is worth the paid
   call the user authorized (deep multi-file analysis, security-sensitive review, hard design
   tradeoff, compact high-stakes gate). Explicit provider intent authorizes the call and its usage,
   not merge or protected-ref authority. Do not invent an unprompted paid Fugu launch from this
   section alone. If the user named Fugu for a broad inventory, the host may still keep the first
   pass host-native and reserve Fugu for contested rows only (state that route).

2. **Task mode.** Default is **general** (analysis, design, investigation, implement-plan, other
   deliverable). Use `review <scope>` only when the user asked for a review, audit, or PR/diff
   findings with the P0-P3 contract. Scope the review narrowly (paths, PR, or "current changes")
   rather than an unbounded whole-repo tour when the ask is focused.

3. **Profile (model is locked to the profile).** Profiles are mutually exclusive; never pass two.

   | Signals | Choose | Model / effort |
   |---|---|---|
   | Small, local, low-stakes; quick design sketch; light review of a small diff; most analysis | plain (no flag) | `fugu` / `high` |
   | Multi-module design with real tradeoffs; medium review that already failed plain; implementation analysis where xhigh is required | `--deep` | `fugu` / `xhigh` |
   | Compact high-stakes question that benefits from explore then reserved synthesis (security-sensitive review, hard correctness gate) | `--ultra` | `fugu-ultra-v1.1` / `high` |
   | One narrow decision that must be right the first time, prompt already tight, worth up to ~60 minutes | `--max` | `fugu-ultra-v1.1` / `max` |

   **Hard rules.** Explicit user flags (`--deep`, `--ultra`, `--max`, or plain) always win: never
   upgrade or downgrade them. Prefer the cheapest lane that still matches the ask. Do not pick
   `--max` for broad multi-goal work; split the work or stay at deep/ultra. Do not pick `--ultra`
   or `--max` for routine greps, renames, or single-file Q&A. Do not pick `--deep` for backlog
   triage, issue classification, or CHANGELOG archaeology. The host cannot pick an arbitrary
   model slug: the profile table is the model map, and Ultra/max still resolve `fugu-ultra-v1.1`
   from the installed catalog (never silent `fugu-ultra-v1.0`).

4. **Write mode.** Default **read-only**. Pass `--write` only when (a) the surrounding user request
   independently authorizes implementation edits, (b) the task is general (not review), and
   (c) the platform is qualified Linux bwrap with a PID namespace. On macOS, omit `--write` and
   say so if the user asked for edits.

5. **Context selection (not a second snapshot product).** The default admitted snapshot already
   includes policy-admitted tracked files and safe non-ignored untracked files. The runner does not
   paste file bodies into the prompt, so breadth of admission is not the same as prompt-token cost;
   relevance still belongs to Fugu and to host path hints. Add `--include PATH` for exact
   host-selected files that matter and might otherwise be easy to miss (fresh untracked notes,
   specific configs that are admitted). Never try to include secrets, `.env*` / `*.env`, ignored
   dependency trees, `.git`, `.elves`, or executable agent config: the safety kernel rejects them
   and exact includes that cannot be admitted fail closed **before** the provider is called, with a
   remediation hint. Prefer a few exact includes over inventing a parallel "minimal snapshot" mode
   that does not exist. When unsure, run `--preflight` first.

6. **Prompt shape.** Write a concrete task string (or review scope) that matches the chosen lane:
   narrow for ultra/max, fuller for deep when the surface area is real. Do not re-force the review
   rubric on a general task. Prefer one precise question over a multi-section audit dump.

After settlement, report Fugu's answer and the route used. Never auto-apply a write handoff.

- **Manus:** requires `MANUS_API_KEY`. The ordinary form creates one private `manus-1.6-max` task
  through `https://api.manus.ai/v2/task.create` with `x-manus-api-key`, explicitly empty
  `message.connectors`, `message.enable_skills`, and `message.force_skills`, then polls with a
  bounded timeout. No connector or forced-skill IDs are explicitly granted. Manus documents that
  empty `enable_skills` loads account-default enabled skills, however, so the shortcut does not
  promise skill isolation. Roster forms add Cobbler-managed Wide Research or deterministic fan-out
  as described below.
- **Grok:** requires the `grok` CLI plus explicit `XAI_API_KEY` (or the legacy
  `GROK_CODE_XAI_API_KEY`). It uses documented headless single-prompt mode, `high`
  reasoning, self-checking, and `dontAsk`, which silently denies unapproved mutations. The runner
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
model-directed commands cannot inspect the credential-bearing parent environment. On macOS, native
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
