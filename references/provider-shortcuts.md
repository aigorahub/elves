# Provider shortcuts

Elves ships four explicit convenience routes for focused provider tasks. They are optional and do
not change the native-first worker default, the supported-host policy, or landing authority.

| Intent | Claude Code | Codex / natural language | Runner |
|---|---|---|---|
| Fugu Ultra file audit | `/fugu <file>` | `$elves fugu <file>` | `run_fugu.sh` |
| Manus web research | `/manus <topic>` | `$elves manus <topic>` | `run_manus.sh` |
| Grok Build headless task | `/grok <instructions>` | `$elves grok <instructions>` | `run_grok.sh` |
| Devin remote task | `/devin <instructions>` | `$elves devin <instructions>` | `run_devin.sh` |

Resolve each runner from the **active Elves skill root**, keep the target repository as the working
directory, validate arguments, and execute only after the user explicitly invokes the matching
shortcut or states the same unambiguous intent. Never invent top-level slash commands for Codex.

## Route contracts

- **Fugu:** requires the configured `codex-fugu` launcher. The runner pins Sakana `fugu-ultra`,
  `xhigh` reasoning, an ephemeral session, and a read-only sandbox. It passes the exact file path
  for direct inspection instead of copying file contents through shell-built JSON.
- **Manus:** requires `MANUS_API_KEY`. It creates a private `manus-1.6-max` task through
  `https://api.manus.ai/v2/task.create` with `x-manus-api-key`, then polls with a bounded timeout.
- **Grok:** requires the `grok` CLI. It uses documented headless single-prompt mode, `high`
  reasoning, self-checking, and `dontAsk`, which silently denies unapproved mutations. It does not
  invent a model id; the authenticated live Grok configuration selects the available model.
- **Devin:** requires `DEVIN_API_KEY`. It creates a remote session through the official
  `https://api.devin.ai/v1/sessions` API, includes the current origin/branch when available, and
  polls the documented session endpoint with a bounded timeout.

`MANUS_MAX_WAIT_SECONDS=0` and `DEVIN_MAX_WAIT_SECONDS=0` provide create-and-return behavior. A
bounded local timeout does not cancel the remote task; the printed task/session URL remains the
follow surface. API base overrides exist only for hermetic testing and controlled proxies.

These routes can consume paid provider capacity. They never grant merge, protected-ref, secret,
or approval-bypass authority, and their output remains evidence for the supported Claude Code or
Codex driver to review.
