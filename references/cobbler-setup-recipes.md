# Cobbler External-Agent Setup Recipes

These recipes map common host tool mixes onto Cobbler roles **without source changes**. Labels:

| Label | Meaning |
| --- | --- |
| **verified** | Behaviorally exercised in this Elves repository's runtime fixtures |
| **experimental** | Documented shape; requires local qualification before write roles |
| **custom** | User wrapper or API-only path; capabilities must be proven per wrapper |

Public default: **native-only** (no setup, no keys, no external executables).

The `python3 scripts/...` forms below are source-checkout shorthand. From an installed Claude Code
or Codex skill, invoke the helper from the active Elves skill root while keeping the target
repository as the working directory; see [`runtime-helper-paths.md`](runtime-helper-paths.md).

Recipes beyond host-native Claude Code / Codex are **best-effort**. We have **not** fully tested
every work-driver matrix (OpenCode, Antigravity, Gemini CLI, OpenRouter models, Grok, …), and we
are **not** treating OpenCode/Antigravity as supported **main drivers**. Those paths **may or may
not work**. If a recipe fails or you harden an exotic config, **prefer a PR** with a fix, test, or
or open an issue with host/OS/command (no secrets):
https://github.com/aigorahub/elves/issues

## Operator commands

Claude Code:

- Primary: `/setup-cobbler` (also: “onboard models”, “update model routes”)
- Compatibility: `/setup-council`

Codex (not top-level slash commands):

- `$elves setup-cobbler`
- `$elves setup-council`
- Natural language: "Set up Cobbler external-agent preferences" / "onboard my models"

### Model onboarding (interview → apply → probe)

Same protocol on both hosts — see [`model-onboarding.md`](model-onboarding.md):

```bash
python3 scripts/cobbler_agents.py onboard plan --json
# host agent interviews user using the packet questions
python3 scripts/cobbler_agents.py onboard apply --json \
  --planning host-native \
  --implement host-native \
  --review claude-code \
  --force
python3 scripts/cobbler_agents.py onboard show --json
python3 scripts/cobbler_agents.py onboard probe --json
# optional paid check: onboard probe --json --smoke (host supplies real smoke)
```

### Apply-only / inventory (non-interactive)

```bash
python3 scripts/cobbler_agents.py setup --json --dry-run
python3 scripts/cobbler_agents.py setup --json \
  --implement grok-build \
  --review claude-code \
  --planning claude-code \
  --lightweight-review host-native
```

Local preferences land in ignored `.elves/models.toml`. Schema example:
`references/models.toml.example`. **Never stage** the local file. During Elves staging, the host
snapshots effective routes into the Survival Guide for reviewable provenance.

## Recipe: native-only (verified)

- All roles: `host-native`
- Setup optional
- No provider keys

## Recipe: Claude-only (verified shape)

- planning/review: `claude-code` or tier `claude-code-planning`
- implement: `host-native`, same Claude install, or labor tier `claude-code-labor`
- validate/synthesize: `host-native` (or Claude when your host is Claude Code)
- fallback: `host-native`
- Pin high vs labor model ids with `requested_model` on each profile in ignored `models.toml`

## Recipe: Claude high-plan / labor-implement (recommended split)

```bash
python3 scripts/cobbler_agents.py onboard apply --json \
  --planning claude-code-planning \
  --review claude-code-planning \
  --implement claude-code-labor \
  --force
```

Then set `requested_model` on each profile to the high-quality vs volume model your Claude install
exposes. Same idea works when the **host** is Claude Code (`host-native` implement) and only
review uses an external high model.

## Recipe: Advanced untrusted Grok writer lease

- Use this only when the run explicitly selects the stricter host-import lease. For ordinary
  optional Grok labor, prefer the trusted full-run / parked-driver recipe later in this guide.
- implement: `grok-build` under an **untrusted writer lease** with a detached registered worktree;
  the host audits and imports exact retained patch bytes, then owns validation, commit, and push
- review/planning: `host-native` or other independent lens
- Never use headless `--worktree --resume` as isolation on Grok Build `0.2.93`
- Sandbox: prefer `devbox` for detached commit handoff; `workspace` is not assumed commit-capable

## Recipe: Sakana / codex-fugu only (experimental)

- planning/review: `codex-fugu` or `codex-fugu-planning`
- implement: `host-native`; Fugu implementation routes are blocked
- Treat MCP OAuth warnings as optional-tool health, not inference failure

## Recipe: Fugu planning with host-native implementation

```bash
python3 scripts/cobbler_agents.py onboard apply --json \
  --planning codex-fugu-planning \
  --review codex-fugu-planning \
  --implement host-native \
  --force
```

The Fugu planning profile is pinned to regular `fugu/high`. Prefer host-native implementation, validation, and synthesis.

## Recipe: Google Gemini CLI / Antigravity CLI (plan/review; optional labor)

- **Not a supported Elves host.** Claude Code or Codex must still be the main driver (`host-native`
  for the loop). Optional-lens paths are **lightly tested / community-validated**. Prefer PRs when
  flags or behavior drift.
- Inventory: `agy` (Antigravity CLI; fallback `antigravity`) and/or `gemini` on PATH
- **Auth:**
  - `agy`: Google OAuth or GCP project (e.g. `aigora-explorations`); run `agy models` to verify
  - `gemini`: `GEMINI_API_KEY` (or Vertex/GCA env); headless needs `--skip-trust` or a trusted folder
- **Use for:** planning, independent review, scout (called *by* Claude Code / Codex)
- **Models — pin current Gemini generations.** Do not hardcode prestige names as public defaults, but
  **do** pin a *current* model in ignored `models.toml` when using Google routes. As of dogfood
  (2026-07): prefer **Gemini 3.1 Pro (High)** (or newer Pro) for plan/review; **Gemini 3.5 Flash**
  (High/Medium) for optional volume. Older 1.5/2.0 pins are stale — re-check `agy models` /
  Gemini CLI `-m` catalog after upgrades.
- **Profiles:**
  - `antigravity-cli` — preferred Google plan/review lens (`agy`)
  - `gemini-cli` — API-key plan/review lens
  - `antigravity-labor` — **experimental** implement labor via `agy` + Flash-class model
- **Implement with Antigravity (experimental, not Lane A):**
  - Lane A (`cobbler_agents implement prepare|launch|…`) remains **Grok Build–oriented**
  - You *may* set `implement = antigravity-labor` in local `models.toml` for role routing / one-shot
    packets, or host-launch:
    `agy --model "Gemini 3.5 Flash (High)" --dangerously-skip-permissions -p "…"`
  - Not host-import write-lease qualified; qualify tools/cost yourself; keep `host-native` validate
- Fallback: `host-native`
- Gemini CLI is transitioning into the Antigravity family; Elves adapters use headless
  `-p`/`--print` (not bare stdin)
- **Plan→review continuity (preferred → fallback):**
  1. **Preferred (most robust):** exact session/conversation id so the planner chat resumes for
     review — Gemini: `--session-id` / `--resume <uuid>`; Antigravity: `--conversation <uuid>`
     only (never `latest` / bare `--continue`). Store ids in the session registry / Survival Guide.
  2. **Fallback if no id:** repo documents the agent can read (plan, contract, execution log,
     Survival Guide, constitution, PR, `.ai-docs`). Do not invent ambiguous resume tokens.
  3. Either way, re-read plan + constitution; session memory does not replace documents.
- **Review bar for Google (and all) lenses:** completeness vs plan+contract, **constitution**
  deal-breakers, and **regressions** (indirect breakage), not only local correctness of the diff

```bash
# Plan/review with Antigravity + current Pro model pin (edit models.toml after apply)
python3 scripts/cobbler_agents.py onboard apply --json \
  --planning antigravity-cli \
  --review gemini-cli \
  --implement host-native \
  --force

# Optional experimental labor (not default overnight):
# python3 scripts/cobbler_agents.py onboard apply --json \
#   --implement antigravity-labor --force
```

In ignored `.elves/models.toml`, pin models explicitly, for example:

```toml
[profiles.antigravity-cli]
adapter = "antigravity-cli"
executable = "agy"
# requested_model = "Gemini 3.1 Pro (High)"   # plan/review — re-check agy models

[profiles.antigravity-labor]
adapter = "antigravity-cli"
executable = "agy"
# requested_model = "Gemini 3.5 Flash (High)" # experimental labor

[profiles.gemini-cli]
adapter = "gemini-cli"
executable = "gemini"
# requested_model = "gemini-2.5-pro"          # or current Gemini CLI model id
```

## Recipe: OpenCode as implement driver (orchestrated by Claude Code / Codex)

[OpenCode](https://opencode.ai) is an open-source terminal coding agent (TUI + `opencode run`
headless)—Claude Code–like, with **OpenRouter** and 75+ providers (Qwen, GLM, etc.).

### Main driver vs work driver

| Term | Who | OpenCode? |
| --- | --- | --- |
| **Main driver** (orchestrator) | Claude Code or Codex — owns canonical memory, protected refs, PR actions, final gates/review, any authorized merge, and Cobbler; host-native/legacy routes also own feature-branch commit/push | **No** (not the skill host) |
| **Work driver** (laborer) | Does the batch coding under that session | **Yes** — e.g. GLM 5.x via OpenRouter + OpenCode |

**Supported shape:** from Claude Code/Codex, set implement to OpenCode and pin an OpenRouter model:

```text
Main driver: Claude Code or Codex
  → implement prepare|launch (or onboard implement = opencode-labor)
  → Work driver: opencode run --auto --model openrouter/…/glm-…
  → Main driver: validate, review, push, PR
```

The exact registered trusted `branch_progress` full-run worker is the only feature-branch
commit/push exception. OpenCode labor in this bounded recipe does not receive that authority;
untrusted lease writers stay detached and host-imported.

**Exotic main driver:** running Elves *inside* OpenCode as the overnight orchestrator is
**unsupported / untested** — it may or may not work. Prefer PRs if you make that path real.

```bash
# Example: Codex/Claude Code orchestrates; OpenCode + GLM does the coding
python3 scripts/cobbler_agents.py onboard apply --json \
  --validate host-native --synthesize host-native \
  --implement opencode-labor --force
# .elves/models.toml → requested_model = "openrouter/<current-glm-slug>"
```

### Install / auth

```bash
curl -fsSL https://opencode.ai/install | bash
# or: npm install -g opencode-ai / brew install anomalyco/tap/opencode
export PATH="$HOME/.opencode/bin:$PATH"
opencode   # then /connect, or let OpenCode read OPENROUTER_API_KEY from the environment
# Credentials may also live in OpenCode auth/config storage; never commit them.
```

When attaching a review packet outside the repository, make the packet directory the OpenCode
working directory and put the positional message immediately after `run`:

```bash
opencode run "Review the attached packet; read-only." \
  --dir /tmp/elves-review \
  --agent plan \
  --model openrouter/qwen/qwen3-max \
  -f stat.txt -f commits.txt -f core.diff
```

Without the matching `--dir`, OpenCode may auto-reject external-file access yet still exit zero
after emitting only a preamble. Treat a missing substantive result as failure even when the
process exit code is zero. Both OpenCode's positional message and `--file` accept multiple values,
so keep the message immediately after `run`; otherwise a trailing message can be parsed as another
file. Implement labor already uses `--dir`, places the message before
`--file`, and adds `--auto` only on the explicitly write-capable path.

### Elves profiles

| Profile | Use |
| --- | --- |
| `opencode-cli` | Plan/review (headless `opencode run --agent plan`) |
| `opencode-labor` | **Implement work driver** (`opencode run --auto` + tools) |

```bash
# Host is still Claude Code or Codex; OpenCode does implement labor
python3 scripts/cobbler_agents.py onboard apply --json \
  --validate host-native \
  --synthesize host-native \
  --planning host-native \
  --implement opencode-labor \
  --review host-native \
  --force
# Pin in .elves/models.toml:
#   requested_model = "openrouter/qwen/qwen3-max"  # re-check OpenRouter catalog
```

### Trusted Grok full-run lifecycle (primary)

One host-created launch rollback ref, one exact worker session, then a parked host:

```bash
python3 scripts/cobbler_agents.py implement rollback-ref --json \
  --run-id <run-id> --session-id <exact-uuid> --batch 0 \
  --head <start-head> --push

python3 scripts/cobbler_agents.py implement full-run-prepare --json \
  --session-id <exact-uuid> --branch <feature-branch> --start-head <start-head> \
  --worktree <path> --packet <packet.json> --adapter grok-build --model auto

python3 scripts/cobbler_agents.py implement full-run-launch --json \
  --session-id <exact-uuid> --grant-grok-auth --grant-github-push

python3 scripts/cobbler_agents.py implement full-run-await --json \
  --session-id <exact-uuid>

python3 scripts/cobbler_agents.py implement full-run-logs --json \
  --session-id <exact-uuid>

# Cancellation/recovery only; omit on normal successful completion.
python3 scripts/cobbler_agents.py implement full-run-stop --json \
  --session-id <exact-uuid>
```

After a healthy launch, the host reads bounded telemetry only and does not shadow worker batches.
The host creates no per-batch refs while parked; worker commit SHAs are internal rollback points.
Wake for terminal/safety conditions or actual exit, then perform one cumulative review.
`full-run-stop` is only for explicit cancellation or recovery of a live/wedged worker; it is not a
normal completion or close command.

`--grant-grok-auth` explicitly reuses a local Grok subscription login in trusted Lane A. The run
keeps isolated `HOME`/`GROK_HOME` state and exposes only the validated canonical owner-private
`auth.json` through Grok's native `GROK_AUTH_PATH`, so native locking and refresh-token rotation
operate on one file. Raw transcript tails are disabled for this route. API-key users should replace
it with `--grant-env XAI_API_KEY`; prefer that route for CI or untrusted lanes. Older or
unsupported binaries fail before spawn and must upgrade or use the API-key route. The
strategies are mutually exclusive, and no supported auth means launch fails before any provider
process starts. New sessions use the caller UUID through supported `--session-id`; models resolve
only from the authenticated live catalog. Proven headless `/goal` is an enhancement, while missing
goal behavior uses the recorded one-packet fallback. See
[`grok-open-source-worker.md`](grok-open-source-worker.md) for capability-check, follow, and recovery.

### Trusted Devin CLI full-run lifecycle

The Devin CLI route uses `swe-1-7-lightning` by default and `--print` as the non-interactive
transport (the TUI is not used under full-run supervision). It follows the same exact-session
contract as Grok. The host captures the provider session id on first launch and resumes with that
exact id.

```bash
python3 scripts/cobbler_agents.py implement full-run-prepare --json \
  --session-id <exact-uuid> --branch <feature-branch> --start-head <start-head> \
  --worktree <path> --packet <packet.json> --adapter devin-cli \
  --executable devin

python3 scripts/cobbler_agents.py implement full-run-launch --json \
  --session-id <exact-uuid> --grant-devin-auth --grant-github-push

python3 scripts/cobbler_agents.py implement full-run-monitor --json \
  --session-id <exact-uuid>

# Resume an interrupted run with the exact captured provider session id.
python3 scripts/cobbler_agents.py implement full-run-launch --json \
  --session-id <exact-uuid> --resume --grant-devin-auth --grant-github-push
```

`--grant-devin-auth` validates and projects the host's canonical Devin CLI config/credentials into
the isolated worker `HOME`. The host looks for `config.json` under `XDG_CONFIG_HOME/devin` (or
`~/.config/devin`) and `credentials.toml` under `XDG_DATA_HOME/devin` (or `~/.local/share/devin`).
Each file must be a regular owner-only (mode `0o600`) file with no symlinks, link count one, and a
bounded size; invalid or missing files cause launch to fail before any provider process starts.
Launch then copies them into the isolated `HOME` with owner-only permissions. Resume revalidates the
same canonical source identity and rejects changed or missing credentials. `--grant-devin-auth` is
only valid for `--adapter devin-cli`; other adapters fail with an adapter mismatch. If Devin created
the credential file with broader permissions, run
`chmod 600 ~/.local/share/devin/credentials.toml` once before launch.

The feature-branch push route is separate from any worker provider login. With a canonical GitHub HTTPS origin,
`--grant-github-push` privately projects the authenticated host `gh` token into one isolated
launch-scoped Git credential helper. Alternatively grant exactly one of `GH_TOKEN` or
`GITHUB_TOKEN` by name. Elves never inherits the host HOME/Git config/SSH agent, stores no raw
token, binds explicit host `user.name` / `user.email` values into the isolated commit environment,
and rejects missing identity or unsupported network push transports before provider spawn.

The capability probe requires an exact native Mach-O/ELF Grok executable, runs it in an isolated
credential-free environment, binds its full safe ancestor chain through child pre-spawn, and
rejects replacement or scripts. The canonical
auth file and every ancestor must also pass owner, mode, link, and supported-platform ACL checks.

Hard external subprocess lanes require a recursive boundary acquired atomically with the child.
The current Python runtime cannot prove that boundary on Linux or macOS—even with bubblewrap—so
optional external routes fall back to the host-native lane and required routes block before
snapshot creation or spawn. Legacy bounded `launch --exec` and
`resume-batch --exec` have no qualified boundary on either supported OS and fail before spawn; use
their default print-only argv workflow or the separate trusted full-run route. Trusted full-run
remains an explicit same-user policy boundary and does not claim malicious-worker recursive
containment.

### Legacy bounded lifecycle (Grok or OpenCode)

```bash
# Grok Build Lane A (default adapter) — live catalog only; optional --check
python3 scripts/cobbler_agents.py implement prepare --json \
  --adapter grok-build \
  --model <live-model-id> \
  --session-id <uuid> \
  --worktree <path>

python3 scripts/cobbler_agents.py implement launch --json \
  --packet .elves/runtime/packets/batch-N.md \
  --session-id <uuid> \
  --cwd <worktree>
# Optional: --check (Grok post-work verify), --effort high
# See references/grok-implementer-launch-prompt.md (denylist note + community credit).

# OpenCode work driver
python3 scripts/cobbler_agents.py implement prepare --json \
  --adapter opencode-cli \
  --model openrouter/qwen/qwen3-max \
  --executable opencode

# Host prints argv. Legacy --exec currently fails closed before spawn because
# neither supported OS has a qualified recursive boundary for this direct path:
python3 scripts/cobbler_agents.py implement launch --json \
  --packet .elves/runtime/packets/batch-N.md \
  --session-id <exact-id-if-known>
```

**Session continuity:** prefer exact session id (Grok `--resume` / OpenCode `--session`; never bare
`continue`/`latest`). Capture OpenCode id via `opencode session list` after the first turn. If no
id, attach plan/docs in the packet. OpenCode create output has no authoritative session id until
that capture completes; never register a host-generated placeholder.

**Honesty:** work-driver and main-driver OpenCode configs are incomplete coverage; flags drift.
Not host-import write-lease qualified. Prefer PRs/tests that make OpenCode more robust under a
Claude Code/Codex main driver — or document honest failures.

## Recipe: all three subscription CLIs (experimental mix)

- planning: independent mix of host + claude-code + codex-fugu (read-only council)
- implement: grok-build child under one writer lease **or** labor-tier Claude/Codex
- review: fresh host + claude-code + codex-fugu (+ optional Gemini/Antigravity); **exclude** the
  implementer from independent quorum
- validate/synthesize/document owner: host coordinator

Dated personal presets may name current models in a **project Survival Guide**, never as shipped
public defaults.

## Recipe: Codex wrapper inside Claude (custom)

- `custom-cli` profile pointing at your wrapper executable (for example CLIProxyAPI or a user alias)
- Qualify session/write capabilities before using implement
- Keep `host-native` fallback

## Recipe: OpenRouter models as planner / reviewer (smart multi-model)

Use OpenRouter when you want **other strong models** (Qwen, GLM, DeepSeek, etc.) as independent
**plan/review/scout** lenses. Native host remains Claude Code or Codex. Missing key → skip OR
lanes; never block overnight Elves.

### In-repo lens (preferred)

`scripts/openrouter_lens.py` is the Cobbler `custom-cli` wrapper:

- Reads Cobbler JSON envelope on stdin **or** `--prompt` / `--prompt-file`
- Calls OpenRouter chat completions with `OPENROUTER_API_KEY` (never prints the key)
- Returns a **custom-json-envelope** role report for Cobbler dispatch
- **Session continuity (preferred):** `--session-id <uuid>` stores turns under
  `.elves/runtime/openrouter-sessions/` (gitignored). Reuse the same id for plan→review.
- **No session id:** pass plan/contract/constitution with `--context-file` (repeatable) or put
  paths in the Cobbler packet `relevant_files` so the model still sees repo documents
- Prompt/context paths must resolve inside the checkout; sensitive credential/key paths are
  rejected, and attached content is redacted before network transmission or session persistence

```bash
# One-shot review (dogfood)
set -a && source .env.local && set +a
python3 scripts/openrouter_lens.py \
  --model qwen/qwen3-max \
  --role review \
  --prompt-file docs/plans/your-plan.md \
  --context-file docs/constitution.md \
  --new-session

# Resume same chat for review (use session_id= printed on stderr)
python3 scripts/openrouter_lens.py \
  --model qwen/qwen3-max \
  --session-id <exact-uuid> \
  --role review \
  --prompt "Review batch 3 for completeness, constitution, regressions." \
  --context-file docs/plans/your-plan.md
```

### Onboard apply-ready profiles

| Profile | Purpose |
| --- | --- |
| `openrouter-lens` | Generic OR plan/review — set `requested_model` to any current OpenRouter id |
| `or-qwen-max` | Qwen-class plan/review preset (example slug `qwen/qwen3-max` — re-check catalog) |
| `or-glm` | GLM-class plan/review preset (example slug `z-ai/glm-5` — re-check catalog) |

Bare `openrouter` remains **apply-blocked**. Pin **current** model slugs in ignored models.toml;
do not treat example ids as permanent prestige defaults.

```bash
python3 scripts/cobbler_agents.py onboard apply --json \
  --review or-qwen-max \
  --planning openrouter-lens \
  --force
# Then edit .elves/models.toml:
#   [profiles.or-qwen-max]
#   requested_model = "qwen/qwen3-max"   # or newer OpenRouter id
```

### Context rules (same as Google)

1. **Preferred:** exact `session_id` so the planner chat resumes for review
2. **Fallback:** repo documents the agent can read
3. **Never:** `latest` / `continue`
4. Review bar: completeness + constitution + regressions, not only local diff correctness

Optional Survival Guide:

```yaml
cobbler-provider-backed-enabled: true
cobbler-provider-backed-optional-env:
  - OPENROUTER_API_KEY
```

Rules:

- Env var **name** only in docs/config: `OPENROUTER_API_KEY`
- Do **not** stage keys; do not print them
- OpenRouter is for **breadth** (many models, one key), not the default overnight implementer
- Do not claim OpenRouter can edit a coding worktree without a separate qualified write path

## Recipe: Meta Muse Spark 1.1 as planner / reviewer (experimental)

**Reference pattern:** geometry-exploration `tools/meta_tools.mjs` + preset `meta-muse-spark11`
(+ research lane `meta-muse-spark11-research`), orchestrated through the same multi-model review
panel as Gemini/Grok/OpenRouter lanes.

When the user has a Meta Model API key:

| Item | Value used in the reference project |
| --- | --- |
| Env | `META_API_KEY` (fallback name accepted: `MODEL_API_KEY`) |
| Base URL | `https://api.meta.ai` (override: `META_API_BASE_URL`) |
| Model id | **`muse-spark-1.1`** (pin the catalog id; do not assume `muse-spark-latest`) |
| Endpoint | Responses API (`/v1/responses`) with structured `input_text` |
| Typical preset | high/xhigh reasoning, large max output tokens, long timeout for hard prompts |
| Role | independent brainstorm / plan critique / review lane — **not** sole authority |

Operator shape:

```bash
# Direct (after project provides a meta_tools-style wrapper)
node tools/meta_tools.mjs \
  --model muse-spark-1.1 \
  --reasoning-effort xhigh \
  --prompt-file path/to/packet.md \
  --max-output-tokens 32768 \
  --timeout-ms 1200000

# Via named preset on a multi-model panel
node tools/review_panel.mjs \
  --prompt-file path/to/review.md \
  --models meta-muse-spark11 \
  --min-success 1
```

Cobbler integration:

- Capability scan: if `META_API_KEY` (or `MODEL_API_KEY`) is present **and** a Meta wrapper exists,
  offer Muse as an optional planning/review lens.
- Config route hint: `meta:muse-spark-1.1` or a `custom-cli` profile whose executable is the Meta
  wrapper.
- Missing key / empty key / wrapper missing → native fallback; never block ordinary Elves.
- In mixed panels, one provider’s failure must not decide the whole run (use `min-success` /
  quorum, same idea as geometry’s proof swarm).

Local `.elves/models.toml` sketch (ignored; never stage):

```toml
[profiles.muse_spark]
adapter = "custom-cli"
executable = "node"   # or a shell wrapper around tools/meta_tools.mjs
# extra_args would point at tools/meta_tools.mjs + --model muse-spark-1.1 …
notes = "META_API_KEY; muse-spark-1.1; read-only plan/review; native fallback"

[roles.planning]
profile = "muse_spark"
required = false
fallback_chain = [
  { profile = "host-native", reason = "no META_API_KEY or Meta wrapper" },
]

[roles.review]
profile = "muse_spark"
required = false
fallback_chain = [
  { profile = "host-native", reason = "keep review available without Meta" },
]
```

## Recipe: Google Cloud AlphaEvolve (math evolutionary search; experimental)

Optional **math-module** tool for generating high-quality numerical examples and counterexample
signals. Not a chat lane and not a proof engine. Full operating rules:
[`math-alphaevolve.md`](math-alphaevolve.md).

- Requires project-owned runner + deterministic local evaluator (geometry-exploration shape:
  `tools/alphaevolve_<task>.py` + independent replay)
- Auth: short-lived **gcloud service-account impersonation**; no service-account keys in the repo
- Role slot: `evolutionary_search` / route `alphaevolve:<task-id>`
- Promote only after independent local replay; ledger as numerical signal
- Missing GCP / runner → skip; never block native math Discovery Sprint

## Recipe: future Google / Antigravity tools (custom)

- Add a `custom-cli` profile with your executable
- Run doctor/setup inventory; mark capabilities unknown until probed
- Do not hardcode future model names into Elves source

## Usage and model refresh

- Observed tokens/cost may be recorded when harnesses expose them
- `remaining_quota` is **unknown** unless explicitly provided — never invent limits from token counts
- Optional warning thresholds belong in local preferences when the user sets them
- Newly discovered models require **manual** acceptance; setup/doctor may recommend with a discovery
  date, not a permanent "best model" table

## Safety

- Never print credentials
- Never stage `.elves/models.toml` or secret values
- Never make setup mandatory for ordinary native Elves
- Commit/push/PR remain host operations under Elves rules
