# Model Onboarding (Claude Code, Codex, Grok Build, and Oh My Pi)

Users need a clear way to **choose** which tools/models handle which jobs, **update** those
choices later, and **verify** they work. Elves does this as a **host-mediated** flow: the agent
interviews the user; the CLI inventories, stores preferences, and probes.

Native-only remains fully valid. Onboarding is optional. The ordinary implementation default is a
separate subscription-native worker on the current host account (Claude Code, Codex, Grok Build, or Oh My Pi);
the live main driver keeps planning and terminal review. Safe provider/effort convenience uses the
shared XDG preferences in [`adaptive-worker-routing.md`](adaptive-worker-routing.md). The ignored
`.elves/models.toml` remains the advanced per-repository profile map.

The `python3 scripts/...` forms below are source-checkout shorthand. From an installed Claude Code,
Codex, Grok Build, or Oh My Pi skill, invoke the helper from the active Elves skill root while the target
repository stays the working directory; see [`runtime-helper-paths.md`](runtime-helper-paths.md).

## Supported hosts (main drivers)

**Supported main drivers are Claude Code, Codex, Grok Build, and Oh My Pi (omp)** — the process that runs the skill
and owns staging, canonical run memory, protected refs, PR actions, final gates, cumulative review,
and merge. Host-native/legacy routes keep the per-batch loop in that driver. In trusted full-run,
the exact registered `branch_progress` worker may commit/push only its assigned feature branch while
the main driver parks. Untrusted workers remain detached and host-imported.

| Host | How to start onboarding |
| --- | --- |
| **Claude Code** (supported main driver) | `/setup-cobbler` or natural language: “set up my model routes” / “onboard models” |
| **Codex** (supported main driver) | `$elves setup-cobbler` or natural language — **not** a top-level Codex slash command |
| **Grok Build** (supported main driver) | natural language for the same intents; install root `~/.grok/skills/elves` (`--target grok`) |
| **Oh My Pi** (supported main driver) | natural language for the same intents; install root `~/.omp/agent/skills/elves` (`--target omp`) |

All four supported hosts follow the same operator CLI (`plan` → `apply` → `show` → `probe`) and the
same host-mediated protocol below. Do not invent different product rules per host. Grok may also
discover Elves via Claude skill compatibility when `~/.claude/skills/elves` is present. Grok remains
an optional **work driver** under Claude/Codex when permitted.

### Main driver vs work driver

| Term | Meaning | Default |
| --- | --- | --- |
| **Main driver** (orchestrator) | Runs Elves: skill, stage/start, Cobbler, canonical memory, protected refs, PR actions, final gates/review, merge, and either the host loop or parked supervisor | **Claude Code, Codex, Grok Build, or Oh My Pi** |
| **Work driver** (laborer) | Host-native/legacy batch labor, trusted full-run assigned-feature-branch labor, or untrusted detached labor under the main driver | host-native, or Grok / OpenCode / Antigravity / … |

**Yes — from inside the main driver you can assign the actual work to another tool.** Example: Claude
Code is the main driver; OpenCode is the work driver using GLM via OpenRouter
(`implement = opencode-labor`, `requested_model = openrouter/…/glm-…`). On the legacy bounded route,
the main driver prepares each packet, launches/resumes, validates, and reviews each return. On a
trusted full-run, it prepares one packet/session and parks until terminal/safety wake, then performs
one cumulative validation/review and lands only when the user's merge policy authorizes it.

Tools outside Claude Code, Codex, Grok Build, and Oh My Pi are **not** supported main drivers. Prefer a
supported host for validation, synthesis, canonical memory, protected refs, PR actions, final review,
and merge. Trusted assigned-feature-branch commit/push is the narrow full-run exception.

### Exotic main drivers (may or may not work)

Someone might try **OpenCode** or **Antigravity** (or similar) as the **main driver** — the process
that loads Elves and owns the overnight session. We are **not** designing for that right now and
have **not** dogfooded it. It **may or may not work**. Do not treat success stories or recipes as a
product guarantee. If you try it and care about the project: **prefer a PR** (skill load path,
headless loop, session recovery, docs) so others benefit.

### Work drivers and optional lenses (also incomplete coverage)

Even as a **work driver** or plan/review lens under Claude Code/Codex, we have **not fully tested**
every configuration of:

- OpenCode (`opencode-cli` / `opencode-labor`) + OpenRouter model matrix
- Antigravity (`agy`) + model tiers
- Gemini CLI headless flags / auth modes
- OpenRouter thin lens + every provider/model slug
- Muse, AlphaEvolve, Grok implement edge cases

Adapters and recipes exist so people can try them. Expect rough edges, version drift, and gaps.

### Testing honesty and contributions

What we design and dogfood against: **Claude Code, Codex, Grok Build, or Oh My Pi as main driver**, mostly
**host-native** labor, with selective checks on a few optional paths when credentials allow.
Optional and exotic routes (OpenCode, Antigravity CLI, Gemini CLI, OpenRouter panels, Muse,
AlphaEvolve, work-driver matrices) are documented so people can try them, but they **have not been our focus**, and **many have not been heavily** tested — including cases without maintainer
subscriptions or installs.

We are **not** thinking hard about every exotic main-driver or work-driver matrix right now.
**Contributions welcome** — that is how the project gets more robust.

If something does not work:

1. **Prefer a PR** with a fix, clearer error, recipe note, or test (especially exotic CLIs and
   work-driver combos we cannot exercise daily).
2. Or **open an issue** with main driver (Claude Code / Codex / Grok Build / other), work driver if
   any, OS, command, and what failed (**no secrets**).

Issue tracker: [github.com/aigorahub/elves/issues](https://github.com/aigorahub/elves/issues).

## Operator CLI

```bash
# 1) Interview packet (inventory + env *names* present + purpose questions)
python3 scripts/cobbler_agents.py onboard plan --json

# 2) After the user answers, write ignored local preferences
python3 scripts/cobbler_agents.py onboard apply --json \
  --planning host-native \
  --implement host-native \
  --review claude-code \
  --scout host-native \
  --force

# 3) Show current map
python3 scripts/cobbler_agents.py onboard show --json

# 4) Structural probe (no tokens)
python3 scripts/cobbler_agents.py onboard probe --json

# Optional: request live smoke (host must supply a real smoke; never print secrets)
python3 scripts/cobbler_agents.py onboard probe --json --smoke
```

Equivalent flags also exist on `setup` for apply-only use.

**Never stage** `.elves/models.toml`. Never paste API key values into chat, TOML, or the Survival
Guide. Env var **names** only.

## Purpose → route catalog

| Purpose | Default | Typical optional routes |
| --- | --- | --- |
| Planning / design | host-native | `claude-code-planning`, `codex-fugu-planning`, Gemini CLI, Antigravity CLI |
| Implementation (labor) | host-native | `claude-code-labor`, `codex-fugu-labor`, grok-build, devin-cli |
| Independent review | host-native | planning-tier Claude/Codex, Gemini CLI, Antigravity CLI, OpenRouter, Muse |
| Lightweight review | host-native | labor-tier Claude/Codex, Gemini CLI |
| Scout / discovery | host-native | Gemini CLI, Antigravity CLI, OpenRouter, Muse |
| Validation ownership | host-native | host-native only preferred |
| Synthesis | host-native | host-native only preferred |
| Math evolutionary search | off | alphaevolve (when gcloud + project runner exist) |

`host-native` means the **current supported host** (Claude Code, Codex, Grok Build, or Oh My Pi) owns that
work — not Antigravity, Gemini CLI, or another optional tool.

### Within-family model tiers (Claude and Codex)

You can use a **stronger model for planning/review** and a **cheaper/faster model for implement
labor** without switching product families:

| Profile | Adapter | Typical use |
| --- | --- | --- |
| `claude-code-planning` | claude-code | Plan + independent review |
| `claude-code-labor` | claude-code | Batch implement volume |
| `codex-fugu-planning` | codex-fugu | Plan + independent review |
| `codex-fugu-labor` | codex-fugu | Batch implement volume |

After `onboard apply`, edit ignored `.elves/models.toml` and set `requested_model` on each tier
profile to the model ids **your** Claude/Codex install supports. Elves does not ship prestige
model ids as public defaults.

Example shape (machine-local only):

```toml
[profiles.claude-code-planning]
adapter = "claude-code"
# requested_model = "…"   # high-quality plan/review

[profiles.claude-code-labor]
adapter = "claude-code"
# requested_model = "…"   # labor implement

[roles.planning]
profile = "claude-code-planning"

[roles.review]
profile = "claude-code-planning"

[roles.implement]
profile = "claude-code-labor"
```

Same pattern with `codex-fugu-planning` / `codex-fugu-labor`.

Sakana now publishes Claude Code-compatible Fugu endpoints and a `claude-fugu` launcher in
addition to `codex-fugu`, so the same subscription can back either host family. Point Claude Code
at `ANTHROPIC_BASE_URL="https://api.sakana.ai"` with `ANTHROPIC_AUTH_TOKEN` (a `fish_…` bearer
token, not `ANTHROPIC_API_KEY`) and map the tiers with `ANTHROPIC_DEFAULT_OPUS_MODEL`,
`ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`, the access-gated
`ANTHROPIC_DEFAULT_FABLE_MODEL`, and `CLAUDE_CODE_SUBAGENT_MODEL`; the exact `[1m]` model names
are in [`provider-shortcuts.md`](provider-shortcuts.md). Two consequences are worth knowing before
you route work there. Anthropic tier names stop describing the model, so `claude-code-planning` and
`claude-code-labor` become Fugu tiers rather than Claude tiers, and a route snapshot recorded on
that host names Fugu models. Effort names also stop being authoritative: Sakana maps Claude Code's
six-stop slider onto Fugu's `high`/`xhigh` boundary, so the adaptive same-family effort ladder is
cosmetic on that route. Both are honest-reporting concerns, not blockers. Elves' own `/fugu`
shortcut stays on the separately audited `codex-fugu` lane regardless.

### Google subscription CLIs (optional plan/review only — not main drivers)

| Route | Executable (typical) | Recommended purposes |
| --- | --- | --- |
| `gemini-cli` | `gemini` (API key; `--skip-trust` headless) | planning, review, scout |
| `antigravity-cli` | `agy` (fallback `antigravity`) | planning, review, scout — pin latest Gemini (e.g. 3.1 Pro) |
| `antigravity-labor` | `agy` | **experimental** implement labor — pin Flash-class (e.g. 3.5 Flash); not Lane A |
| `openrouter-lens` | `scripts/openrouter_lens.py` | OpenRouter plan/review — any `provider/model` via `requested_model` + `OPENROUTER_API_KEY` |
| `or-qwen-max` / `or-glm` | same lens | Named OR presets for strong Qwen/GLM-class plan/review (pin current slug) |
| `opencode-cli` | `opencode` | OpenCode TUI/agent (Claude Code–like); plan/review via `run --agent plan`; OpenRouter etc. |
| `opencode-labor` | `opencode` | OpenCode **implement** labor (`run --auto`); pin `provider/model`; exact `--session` preferred |

Official installers commonly place `agy` in `~/.local/bin` and OpenCode in
`~/.opencode/bin`. Elves checks those installer directories as well as inherited `PATH`, so an
already-running Codex or Claude Code host can probe and launch a newly installed CLI without a
restart. A new ordinary terminal still needs its shell profile reloaded.

### Session continuity (plan → review)

**Preferred (most robust):** exact session/conversation id so the same chat that planned can review
with its full planning thread. Document-only context is the fallback when no id exists.

External chats are **not** one-shot throwaways when the same lens plans and later reviews:

1. At planning, create or capture an **exact** session/conversation id (Gemini:
   `--session-id` / listed UUID; Antigravity: conversation UUID after first turn).
   OpenCode and Antigravity creation cannot preallocate an authoritative id: treat the id as
   unavailable until the provider reports it, then register that exact value.
2. Store it in the session registry / run memory (never paste secrets).
3. At review, resume with that **exact** id only — forbid `latest`, bare `--continue`, or “most
   recent”.
4. Even with a session id, still load plan + constitution + regression surfaces from the repo —
   session memory supplements documents; it does not replace them.

**If there is no session id** (missing, lost after compaction, or one-shot lens): do **not** invent
`latest`/`continue`. Fall back to **repo documents the agent can read**:

- plan file, batch contract / execution log, Survival Guide, constitution (if present),
  relevant `.ai-docs` / PR body

Order of preference: **exact session id (best) → repo documents (required fallback) → never
ambiguous “latest/continue”.**

Google is consolidating coding-agent surfaces around **Antigravity** (Gemini CLI transitions into
that family). Treat both as optional **subscription CLIs** when installed and the **host is still
Claude Code, Codex, Grok Build, or Oh My Pi**.

**Not a supported Elves host.** Do not treat Antigravity or Gemini CLI as the main overnight driver.
Support for them as the primary runtime is not our focus. As **optional lenses**, they are
**best-effort and lightly tested** (including cases where the maintainer has no subscription to
verify live). If you use them and hit a wall, **prefer a PR**.

**Cost guidance:** usually **not** cost-effective as the main overnight implement engine. Prefer
host-native or labor-tier Claude/Codex (or optional Grok implement) for bulk batch coding; use
Gemini/Antigravity as independent plan/review lenses when you already pay for the subscription.

## Host agent protocol

When the user asks to onboard, reconfigure models, or “which model should do what”:

1. **Plan**
   Run `onboard plan --json`. Do not invent inventory.

2. **Interview**
   Walk `questions[]` from the packet. For each purpose, show available options (respect
   `available_hint`: missing CLI or env name → say so). Offer **host-native** first.
   If they want OpenRouter / Muse, confirm the env **name** is set (key already in environment or
   ignored `.env.local`) — never ask them to paste the secret into chat.

3. **Apply**
   Run `onboard apply` with the chosen routes. Prefer host-native fallbacks (default).

4. **Probe**
   Run `onboard probe --json`. Report pass / warn / fail. Fix or re-choose failing routes.

5. **Optional live smoke**
   Only if the user wants a paid check: run a **tiny** real completion per external route (host
   tool), then re-run probe or record smoke evidence. Never print credentials. Default is
   structural probes only.

6. **Update later**
   Same flow. `onboard show` first, then re-interview **changed** purposes only.
   `onboard apply` **merges** into existing `.elves/models.toml` roles (unspecified flags keep
   prior values). Pass `--reset-roles` only when you intentionally want unspecified roles reset
   to host-native. Use `--force` when overwriting a TOML that has unknown sections.

7. **Staging snapshot**
   During Elves staging, paste effective routes into the Survival Guide so the PR shows provenance
   without committing machine-local TOML.

## What probe checks

| Kind | What |
| --- | --- |
| **Structural** | host-native always; configured role profiles → resolved executable (from `models.toml` `[profiles.*]`, recipe, or inventory) on PATH **or, for relative paths like `scripts/openrouter_lens.py`, under the repo root** + `--help`; env **names** for OpenRouter/Meta (process or `.env.local` name scan); gcloud for AlphaEvolve hint |
| **Live smoke** | Opt-in; requires host-provided real model response; empty/fake smoke does not count |

Probe never invents remaining quota and never prints secrets.

## Math / Muse / OpenRouter / AlphaEvolve

These are **optional upgrades** on top of native:

- **OpenRouter** — review/scout breadth when `OPENROUTER_API_KEY` is set + a **custom-cli wrapper**
  profile (see recipes). Bare `onboard apply --review openrouter` is **rejected** (`apply_blocked`).
- **Meta Muse Spark 1.1** — plan/review when `META_API_KEY` or `MODEL_API_KEY` is set + wrapper.
  Bare `meta-muse` apply is **rejected**.
- **AlphaEvolve** — math `evolutionary_search` when gcloud + project runner exist. Configure via
  Survival Guide / math docs, not as an onboard role flag.

`onboard plan` may still *mention* these when env names or gcloud are present (`apply_ready: false`).
Probe can check env name presence / gcloud; dispatch needs a real wrapper executable recorded under
`[profiles.<name>]`.

See [`math-alphaevolve.md`](math-alphaevolve.md), [`math-provider-config.md`](math-provider-config.md),
[`cobbler-setup-recipes.md`](cobbler-setup-recipes.md).

## Related

- CLI setup (non-interview): `python3 scripts/cobbler_agents.py setup …`
- Doctor inventory: `python3 scripts/cobbler_agents.py doctor --json`
- Recipes: [`cobbler-setup-recipes.md`](cobbler-setup-recipes.md)
