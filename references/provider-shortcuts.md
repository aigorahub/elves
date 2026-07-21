# Provider shortcuts

Elves ships four explicit convenience routes for focused provider tasks. They are optional and do
not change the native-first worker default, the supported-host policy, or landing authority.

| Intent | Claude Code | Codex / natural language | Runner |
|---|---|---|---|
| Fugu repository review | `/fugu [--deep\|--ultra] <task>` | `$elves fugu [--deep\|--ultra] <task>` | `run_fugu.sh` |
| Manus web research | `/manus [--wide\|--fanout] …` | `$elves manus [--wide\|--fanout] …` | `run_manus.sh` |
| Grok Build headless task | `/grok <instructions>` | `$elves grok <instructions>` | `run_grok.sh` |
| Devin remote task | `/devin <instructions>` | `$elves devin <instructions>` | `run_devin.sh` |

Resolve each runner from the **active Elves skill root**, keep the target repository as the working
directory, validate arguments, and execute only after the user explicitly invokes the matching
shortcut or states the same unambiguous intent. Never invent top-level slash commands for Codex.

## Route contracts

- **Fugu:** requires the official `codex-fugu` launcher and its configured Sakana credentials. The
  runner copies only tracked working-tree files into a disposable snapshot, moves prose agent
  instructions to inert evidence paths, and adds host-generated branch/diff context filtered to
  paths that survived that same snapshot policy. Safe tracked deletions are admitted by that policy
  even though no current file remains, while deleted credential/config paths stay suppressed. It then
  requires Elves' qualified kernel filesystem sandbox (`sandbox-exec` on macOS or `bwrap` on
  Linux), an isolated HOME/CODEX_HOME, an environment containing only runtime names plus the
  Sakana grant, and a Codex shell policy that does not forward that grant to model-run commands.
  It also uses Codex's read-only sandbox, `never` approval policy, an ephemeral session, closed
  interactive input after the prompt, disabled launcher notices/updates, and a hard process-group
  wall-clock limit. If the OS read sandbox cannot be proven, the shortcut fails closed. The
  supported profiles are:

  | Shortcut | Model / effort | Default wall limit | Use |
  |---|---|---:|---|
  | `/fugu <task>` | `fugu` / `high` | 10 minutes | routine repository review |
  | `/fugu --deep <task>` | `fugu` / `xhigh` | 20 minutes | harder correctness or security review |
  | `/fugu --ultra <task>` | `fugu-ultra` / `high` | 30 minutes | compact, high-stakes final audit |

  Sakana documents `max` as a compatibility alias for `xhigh`, not a separate effort level. The
  public shortcut therefore uses `xhigh` explicitly and does not market an Ultra/max lane. A
  legacy invocation containing one existing file still works, but the path is only a focus hint;
  the runner never copies file contents into the prompt. With no task, Fugu reviews the current
  repository changes.
- **Manus:** requires `MANUS_API_KEY`. The ordinary form creates one private `manus-1.6-max` task
  through `https://api.manus.ai/v2/task.create` with `x-manus-api-key`, explicitly empty
  `connectors`, `enable_skills`, and `force_skills`, then polls with a bounded timeout. Roster forms
  add Cobbler-managed Wide Research or deterministic fan-out as described below.
- **Grok:** requires the `grok` CLI plus explicit `XAI_API_KEY` (or the legacy
  `GROK_CODE_XAI_API_KEY`). It uses documented headless single-prompt mode, `high`
  reasoning, self-checking, and `dontAsk`, which silently denies unapproved mutations. The runner
  copies tracked source into a disposable snapshot and requires Elves' qualified outer kernel
  sandbox, which makes that snapshot read-only independently of Grok's profile merger. It constructs
  isolated HOME/GROK_HOME state, projects only the selected named key to Grok itself, and selects a
  dedicated shell that unsets both supported key names before every model-directed terminal command.
  Grok also runs its custom inner `strict` profile with child network and credential-file denies. The
  runner writes `permissions.defaultMode: dontAsk` to isolated Claude-compatible settings (the
  similarly named CLI flag does not activate this mode) and locks bypass mode off in isolated Grok
  requirements. Both outer and inner sandbox application fail closed.
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
number of seconds. A timeout terminates the entire launcher process group and returns exit 124.
The runner intentionally does not use a direct API fallback: `codex-fugu` owns Sakana transport,
stream resilience, project instructions, and model-catalog compatibility. Official launcher
installation and command details are at
[`console.sakana.ai/get-started`](https://console.sakana.ai/get-started) and
[`SakanaAI/fugu`](https://github.com/SakanaAI/fugu/blob/main/docs/commands_details.md).

Fugu's project access is the disposable tracked-source snapshot, not the host checkout: ignored
and untracked files, `.git`, `.elves`, executable agent configuration, and ordinary credential
stores are absent and outside the kernel read boundary. Grok intentionally works in the target
checkout for build tasks, but its strict sandbox confines reads to that checkout/system roots and
the custom deny list blocks common credential files inside the checkout. Repositories must still
apply their provider/data-governance policy before invoking either optional paid route.

`MANUS_MAX_WAIT_SECONDS=0` and `DEVIN_MAX_WAIT_SECONDS=0` provide create-and-return behavior. In a
Manus roster mode the printed manifest, rather than “last task,” is the authoritative follow and
resume surface. A bounded local timeout does not cancel the remote task; the printed task/session
URL remains the ordinary follow surface. API base overrides exist only for hermetic testing and
controlled proxies.

These routes can consume paid provider capacity. They never grant merge, protected-ref, secret,
or approval-bypass authority, and their output remains evidence for the supported Claude Code or
Codex driver to review.
