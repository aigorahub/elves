# Provider shortcuts

Elves ships four explicit convenience routes for focused provider tasks. They are optional and do
not change the native-first worker default, the supported-host policy, or landing authority.

| Intent | Claude Code | Codex / natural language | Runner |
|---|---|---|---|
| Fugu repository review | `/fugu [--deep\|--ultra] <task>` | `$elves fugu [--deep\|--ultra] <task>` | `run_fugu.sh` |
| Manus web research | `/manus <topic>` | `$elves manus <topic>` | `run_manus.sh` |
| Grok Build headless task | `/grok <instructions>` | `$elves grok <instructions>` | `run_grok.sh` |
| Devin remote task | `/devin <instructions>` | `$elves devin <instructions>` | `run_devin.sh` |

Resolve each runner from the **active Elves skill root**, keep the target repository as the working
directory, validate arguments, and execute only after the user explicitly invokes the matching
shortcut or states the same unambiguous intent. Never invent top-level slash commands for Codex.

## Route contracts

- **Fugu:** requires the official `codex-fugu` launcher and its configured Sakana credentials. The
  runner starts the launcher at the target repository root so the reviewer can inspect project
  files directly. It uses a read-only sandbox, `never` approval policy, an ephemeral session,
  closed interactive input after the prompt, disabled launcher notices/updates, and a hard
  process-group wall-clock limit. The supported profiles are:

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
- **Manus:** requires `MANUS_API_KEY`. It creates a private `manus-1.6-max` task through
  `https://api.manus.ai/v2/task.create` with `x-manus-api-key`, then polls with a bounded timeout.
- **Grok:** requires the `grok` CLI. It uses documented headless single-prompt mode, `high`
  reasoning, self-checking, and `dontAsk`, which silently denies unapproved mutations. It does not
  invent a model id; the authenticated live Grok configuration selects the available model.
- **Devin:** requires `DEVIN_API_KEY`. It creates a remote session through the official
  `https://api.devin.ai/v1/sessions` API, includes the current origin/branch when available, and
  polls the documented session endpoint with a bounded timeout.

`SAKANA_FUGU_MAX_WAIT_SECONDS` can replace a profile's wall limit with another finite, positive
number of seconds. A timeout terminates the entire launcher process group and returns exit 124.
The runner intentionally does not use a direct API fallback: `codex-fugu` owns Sakana transport,
stream resilience, project instructions, and model-catalog compatibility. Official launcher
installation and command details are at
[`console.sakana.ai/get-started`](https://console.sakana.ai/get-started) and
[`SakanaAI/fugu`](https://github.com/SakanaAI/fugu/blob/main/docs/commands_details.md).

Project access means the provider-backed agent can read repository content. The prompt forbids
credential stores, `.env` files, authentication files, and secret output, but repositories should
still apply their own provider/data-governance policy before invoking this optional paid route.

`MANUS_MAX_WAIT_SECONDS=0` and `DEVIN_MAX_WAIT_SECONDS=0` provide create-and-return behavior. A
bounded local timeout does not cancel the remote task; the printed task/session URL remains the
follow surface. API base overrides exist only for hermetic testing and controlled proxies.

These routes can consume paid provider capacity. They never grant merge, protected-ref, secret,
or approval-bypass authority, and their output remains evidence for the supported Claude Code or
Codex driver to review.
