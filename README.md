# Elves

![Elves - they work while you sleep](assets/elves-banner.jpeg)

Elves is an open-source Agent Skill for handing planned development or research work to a separate
worker without locking the run to one model provider. The capable Claude Code, Codex, or Grok Build
driver plans and reviews; a subscription-native (or optional external) worker implements; durable
run files let the work survive context compaction. You write the plan and own the merge decision.
The agent does the middle.

**Current release: v2.24.2**. See [`CHANGELOG.md`](CHANGELOG.md) for version history. Coined terms
are defined once in [`references/glossary.md`](references/glossary.md).

**New to Elves?** Use the [practical user guide](https://aigorahub.github.io/elves/) — especially
**[Paste this to your agent](https://aigorahub.github.io/elves/#agent-onboarding)** at the top.
That copy-ready block installs Elves for Claude Code, Codex, and/or Grok Build (whichever is
available) and orients you. The guide also covers the first run, worker choice, live progress,
review, and landing. This README is the repository reference: shell install, safety model,
operations, and an index into the detailed contracts under [`references/`](references/).

**Supported main drivers:** Claude Code, Codex, and Grok Build. All three are first-class hosts:
native skill install, doctor validation, automatic required-mode prewalk qualification, and
explicit experimental prewalk. Grok Build is also an optional *worker* under Claude/Codex when
permitted. Managed install targets: `claude` → `~/.claude/skills/elves`, `codex` →
`~/.codex/skills/elves`, `grok` → `~/.grok/skills/elves`.
See the guide FAQ
[I opened Grok Build and tried /elves](https://aigorahub.github.io/elves/#troubleshooting).

---

## Quick start

Prefer the agent paste in the guide if you already have a supported host open. Otherwise use the
shell one-liners below (Python 3.10+). First-time install needs an explicit host target; `--target
all` only updates hosts that already have an Elves skill root.

### Install (Claude Code)

```bash
ELVES_TMP="$(mktemp -d)" && git clone --depth 1 https://github.com/aigorahub/elves.git "$ELVES_TMP/elves" && python3 "$ELVES_TMP/elves/scripts/sync_installed_skills.py" --apply --target claude && rm -rf "$ELVES_TMP"
```

This installs `~/.claude/skills/elves/` plus eleven managed alias skills (`/cobbler`,
`/cobbler-mode`, `/council`, `/ec`, `/elves-council`, `/setup-cobbler`, `/setup-council`, `/fugu`,
`/manus`, `/grok`, `/devin`). The sync
helper creates missing aliases and updates only aliases carrying the Elves-managed marker. If it
finds a user-owned alias, it reports the conflict before changing the install and never
overwrites that alias.

### Install (Codex)

```bash
ELVES_TMP="$(mktemp -d)" && git clone --depth 1 https://github.com/aigorahub/elves.git "$ELVES_TMP/elves" && python3 "$ELVES_TMP/elves/scripts/sync_installed_skills.py" --apply --target codex && rm -rf "$ELVES_TMP"
```

Codex installs the main skill bundle only — no slash aliases. Use `$elves cobbler: <task>` or
natural language such as "Ask the Cobbler…".
Codex users should not need or expect a top-level `/cobbler` command. Do not invent top-level /cobbler.

### Install (Grok Build)

```bash
ELVES_TMP="$(mktemp -d)" && git clone --depth 1 https://github.com/aigorahub/elves.git "$ELVES_TMP/elves" && python3 "$ELVES_TMP/elves/scripts/sync_installed_skills.py" --apply --target grok && rm -rf "$ELVES_TMP"
```

This installs `~/.grok/skills/elves/` for native Grok Build discovery (first-class host, same
workflow contract as Claude and Codex). No Claude-style slash aliases. Invoke Elves via Grok Build
skill discovery or natural language.

### Optional provider shortcuts

Focused provider tasks do not require a full Elves run. Claude Code gets
`/fugu [--deep|--ultra|--max] [--max-wait SECONDS] [--preflight] [--write] [--include PATH] <task>` and
`/fugu [--deep|--ultra|--max] [--max-wait SECONDS] [--preflight] review <scope>`,
`/manus <topic>`, `/grok <instructions>`, and `/devin <instructions>`; Codex uses the equivalent
`$elves fugu|manus|grok|devin …` forms or natural language. Plain Fugu follows the requested
analysis, design, investigation, or other task; `fugu review` keeps the read-only P0-P3 review
contract. Both receive a bounded snapshot of policy-admitted tracked and non-ignored untracked
files. `--include` records an exact host-selected path but cannot override exclusions for ignored
trees, credentials, operational state, executable agent configuration, unsafe links/file types, or
repository escapes; the exact path must actually be admitted and copied, and gitignored includes
fail closed before the provider launches (use `--preflight` to check). Both `.env.*` and
`*.env` dotenv-name families plus host-owned internal namespaces are always excluded. General tasks
remain read-only unless the user independently authorizes implementation and the host selects
`--write`; that route additionally requires qualified recursive Linux bwrap PID-namespace
containment and is unavailable on macOS today. A qualified write exports a mode-aware audited inert
handoff that is never applied automatically. Live writable-state bounds tolerate benign temporary
subtree disappearance and fail closed on other audit errors. macOS read-only cleanup is best-effort,
not proof of recursive descendant absence.
Profiles remain regular `fugu/high`, `fugu/xhigh` with `--deep`, `fugu-ultra-v1.1/high` with
`--ultra`, and `fugu-ultra-v1.1/max` with `--max` for one narrow high-stakes gate on a 60-minute
default wall budget. Prefer plain first (first paid call is plain unless the user set a flag); use
`--max-wait` before automatic `--deep`; if any `--include`, run `--preflight` first; prefer
`--ultra` when a written report must survive exploration; redirect to a log (never `| tail`).
**Host Fugu routing:** when the user says “use Fugu” without an explicit
profile flag, the host agent chooses general vs review, plain / deep / ultra / max
(profile locks model + effort; no free model slug), write mode, and optional `--include` paths
before launch, states a short `Fugu route: …` line, and prefers the cheapest matching lane;
explicit flags always win. The isolation snapshot is always on; the host only adds exact admitted
context via `--include`. See `references/provider-shortcuts.md`
(**Host routing when the user says "use Fugu"**) and `references/fugu-calling-guide.md`.
Regular/deep calls are ephemeral; Ultra and max reserve synthesis time and resume only the
exact isolated session with further tools forbidden. Session state and raw events never leave the
lane; events cross a bounded host-owned pipe, final output remains pinned to a no-follow
descriptor, and every settled phase receives a final descriptor-safe writable-state audit. Codex's documented externally-sandboxed mode avoids an invalid nested macOS sandbox while
Elves' required outer boundary remains authoritative. Manus supports a normal private
task plus Cobbler-managed `--wide` and deterministic `--fanout` rosters, explicit `--file`
attachments, and duplicate-safe `--resume` that retries only known-failed steps; roster manifests
are validated and exclusively reserved before any upload. A durable pre-create marker prevents
resume from duplicating a paid Manus task when task-ID persistence was interrupted. Devin creates
a bounded remote task, including its creation request, without granting stored secrets or knowledge
by default. Grok uses
headless high-reasoning mode without approval bypass over a disposable tracked-source snapshot in
Elves' required outer kernel sandbox, plus Grok's built-in inner `strict` profile, provider-documented
isolated `dontAsk` settings, and bypass mode locked off. The shortcut requires an explicit
`XAI_API_KEY`; a dedicated Grok tool shell removes both supported key names before any
model-directed command runs, and the Linux boundary omits procfs to prevent parent-environment
inspection. It does not expose a shared OAuth file because Grok applies the same sandbox to
provider and tool reads. Fugu's Linux boundary likewise omits procfs around its credential-bearing
launcher. Manus requests nest empty connector, enabled-skill, and forced-skill lists under
`message`, so the wrapper grants no connector or forced-skill IDs explicitly; the documented API
still loads account-default enabled skills when `enable_skills` is empty, and this route therefore
does not claim skill isolation. See
[`references/provider-shortcuts.md`](references/provider-shortcuts.md) for requirements, auth
environment names, timeouts, and follow behavior.

### Per-project install

Clone into `.claude/skills/elves`, `.codex/skills/elves`, or `.grok/skills/elves` inside your repo
(remove the nested `.git`), or prefer `scripts/sync_installed_skills.py` over hand-maintaining a
second tree.

### Validate the install

```bash
# Claude Code:
python3 ~/.claude/skills/elves/scripts/install_doctor.py --startup
# Codex:
python3 ~/.codex/skills/elves/scripts/install_doctor.py --startup
# Grok Build:
python3 ~/.grok/skills/elves/scripts/install_doctor.py --startup
```

### Update or uninstall

```bash
# Update every host that already has Elves installed:
python3 /path/to/elves/scripts/sync_installed_skills.py --apply --target all
# Or update one host:
python3 /path/to/elves/scripts/sync_installed_skills.py --apply --target grok
# Uninstall: remove the skill root you installed (and Claude aliases only if you want them gone):
rm -rf ~/.claude/skills/elves ~/.codex/skills/elves ~/.grok/skills/elves
```

### First run

Write a plan (start from [`references/plan-template.md`](references/plan-template.md)), then say,
from your project:

> Implement docs/plans/my-feature.md as an elves run while I'm offline.

The driver stages the run (run docs, branch, dedicated worktree when other agents may touch the
repo, worker packet for delegable runs, preflight), launches the worker, reviews cumulatively,
and stops at a **landable PR** (chat-to-work). Merging happens only when you say so — an explicit
in-session authorization (chat-to-land) or the reviewed-landing command `\land-pr` / `/land-pr`.
See [`references/e2e-chat-to-land.md`](references/e2e-chat-to-land.md) and
[`references/kickoff-prompt-template.md`](references/kickoff-prompt-template.md).

For a machine-checked cold handoff, the session may opt into explicit handoff v1: exact state,
acceptance ownership, branch/HEAD, and a matching bounded Markdown or JSON packet capsule. The
ordinary v2.8 path remains advisory when this schema is absent. The capsule is not prewalk continuity proof.
See [`references/schema-and-acceptance.md`](references/schema-and-acceptance.md).

Projects with deterministic repository-specific landing rituals may track
`.elves/landing-profile.json`. Its declarative path co-change checks are evaluated at the exact
HEAD/base/merge-base and bound to a host-owned digest; schema v1 rejects executable checks and
never launches profile-directed processes. Missing profiles are neutral; profiles can block
readiness but never grant merge, tag, release, protected-ref, secret, connector, or posting
authority. Hosts may `observe` landings, `propose` candidates, explicitly `promote` into the tracked
profile, and apply exact-HEAD `waive` entries — with no auto-promotion. See
[`references/project-landing-profiles.md`](references/project-landing-profiles.md).

---

## Who implements

**Default: a subscription-native worker** on the live host (Claude Code, Codex, or Grok Build) in a
separate exact session — no external provider required. Optional work drivers when configured and
permitted: trusted Grok Build full-run under Claude/Codex, Devin CLI, or other adapters. Missing
optional provider access never blocks a native run. Repository `allow_grok=false` is an absolute
veto. The host owns packets, protected refs, final gates, PR, and merge — always. Details:
[`references/adaptive-worker-routing.md`](references/adaptive-worker-routing.md),
[`references/prewalk.md`](references/prewalk.md),
[`references/grok-open-source-worker.md`](references/grok-open-source-worker.md),
[`references/grok-implementer-launch-prompt.md`](references/grok-implementer-launch-prompt.md).
Parallel implementation lanes are optional and never the default: serial stays the default, and
`worker.parallel=auto` only recommends lanes when the deterministic width test passes; see
[`references/parallelves.md`](references/parallelves.md).

Trusted Grok implementation launches use `--always-approve` alone: Grok Build treats an explicit
`--permission-mode auto` as an override, so the two flags must not be combined.

Native delegation names both model and effort, and stays inside one model family. GPT-5.6
`xhigh`/extra-high/`ultra` hands off to the same GPT-5.6 model at `medium`; GPT-4.8 Max/UltraCode to
the same GPT-4.8 model at `medium`; Fable 5 `max`/`ultra` to the same Fable 5 model at `low`; Opus 5
`max`/`ultracode` to the same Opus 5 model at `high`. There is no Fable→Opus route — a Fable driver
hands off to `claude-fable-5` at `low` rather than crossing families. The one cross-family worker is
the opt-in Grok handoff, which prefers `grok-4.5` at explicit `high` when the live catalog returns
it. Composer 2.5 (`grok-composer-2.5-fast`) is retired and is never selected.

### Optional exact-session prewalk

Prewalk lets one worker orient on a guide model/effort, create a bounded TODO, make
the first real edit, and then resume the **same session in the same worktree** on the execution
route. The packet is sent once; the resume input is only `Continue.`. A new worker that receives a
summary is a normal cold handoff, not prewalk, and cold fallback is forbidden after an edit.

The safe preference is `worker.prewalk: "auto"`, while the launch CLI defaults to `off` for backward
compatibility. `auto` makes no qualification model calls and reuses only matching cached proof.
`required` automatically runs a 180-second, 1 MiB-bounded live canary when proof is absent. The
task worker starts only after session, worktree, stream, route-change, retained-context, and
packet-count checks pass; failure stops with a private evidence path. `experimental` explicitly
accepts qualification uncertainty after static grammar inspection, reports that status, and keeps
every real-run continuity and authority check. Claude Code, Codex, and Grok Build share these
semantics. Grok single-phase native-worker launch remains registry-gated. See the
[normative prewalk contract](references/prewalk.md) and
[host parity matrix](references/host-parity.md).

## Safety model

**The user owns whether Elves may merge.** The worker never merges; the driver merges only with
an explicit opt-in recorded in Run Control, and only with a regular merge commit after final
readiness — never a squash. Readiness (plan Acceptance with proof at the exact HEAD) and merge
authority are independent; **Landable is plan Acceptance with proof**, not green CI plus
`status: complete`.

**Thin safety kernel** (never weakened): exact plan/session/packet acceptance identity;
credential, origin, branch, worktree, ancestry, clean-tip, protected-ref, and redaction checks; no
worker merge/tag/protected-ref/PR/landing authority; test integrity; independent terminal review;
final CI.

The optional **continuity watchdog** stays outside the kernel's authority surfaces: an
operator-owned OS timer that Elves never activates itself, detect-and-report by default, and
every safety decision delegated to `full-run-prepare --resume` — it never resumes a terminal
run and holds no landing, merge, or credential authority
(`references/operations-guide.md`).

**Forbidden commands.** Never: `git reset --hard`, `git checkout .`, `git clean -fd`, force push,
rebase on shared branches, `rm -rf` outside scope, operating on another agent's checkout.

**One run owns one branch and one checkout.** Prefer a dedicated worktree when other agents may
touch the repo (`./scripts/preflight.sh --create-worktree <branch> --base origin/main`;
`--dry-run` first). The helper prints the branch, worktree path, base ref, and collision tripwire,
and does not reuse, delete, or repair existing worktrees. `START_TIP` is the collision tripwire:
any unexplained tip move is a collision and a Hard Stop.

**Worktree lifecycle.** Staging records the created worktree path in `.elves-session.json`;
after merge, the run's worktree is reclaimed with the separate gc helper
(`./scripts/preflight.sh --gc-worktrees`; report by default, `--apply` removes only clean, fully
merged, fully pushed worktrees; unregistered sibling directories are listed and never deleted).
Installed skill bundles ship `scripts/worktree_gc.py` with that helper (and
`scripts/provider_supervisor.py` for full-run provider supervision). Historical `docs/plans/` and
source-repo `docs/elves/` archives stay source-checkout only — never part of the installed skill.

**Unattended by construction.** Gates and helper subprocesses run with closed stdin and explicit
timeouts — a silent hang is a failure, not progress. Worker failures split into transient
(backoff and resume; never consumes the re-drive budget) and substantive (budgeted re-drives,
then split or host-native takeover). Workers keep an untracked progress ledger under
`.elves/runtime/` so recovery starts oriented. See SKILL.md's Worker failure recovery and
[`references/autonomy-guide.md`](references/autonomy-guide.md).

## What can go wrong

Overnight agent runs fail in predictable ways. Knowing the failure modes makes them preventable.

| Failure | What happens | Mitigation |
|---|---|---|
| **Machine sleeps** | Session stops silently. You wake up to 45 minutes of work instead of 8 hours. | `caffeinate` (macOS), `systemd-inhibit` (Linux), or run in cloud. Elves preflight warns you. |
| **Agent runs destructive git commands** | `git reset --hard` wipes hours of uncommitted work. This has happened to real users. | Elves explicitly forbids `git reset --hard`, `git checkout .`, `git push --force`, and `git clean -fd`. The survival guide template includes these as non-negotiables. |
| **Agent disables or weakens tests** | Agent comments out failing tests, weakens assertions, or shortens timeouts only to make the gate pass. You wake up to code that "passes" but is broken. | Elves forbids green-seeking test changes. Behavior-driven test updates are allowed when coverage is preserved or improved and the reason is recorded. |
| **Context compaction loses instructions** | Long sessions hit memory limits. The agent's conversation gets summarized, and safety instructions disappear. | Elves stores layered run memory on disk. Host-native/legacy routes re-read after host commits/pushes; a trusted full-run host stays parked and re-reads/reconciles once at terminal/safety wake. The Stop Gate plus `continuation_guard` keep continuation explicit. |
| **Interactive prompt stalls the session** | A tool asks for confirmation, a survey pops up, or `npm install` wants input. Nobody is there to click yes. | Elves surfaces the recommended non-interactive env vars during preflight, and the skill requires `--yes` flags plus tool-level survey suppression before unattended runs. Elves' own gates run with closed stdin and hard timeouts. |
| **Flaky tests block progress** | A test passes locally but fails intermittently. The agent loops trying to fix a non-bug. | The agent logs flaky tests in the execution log and moves on after 3 failed attempts on the same non-deterministic failure. |
| **Terminal closes (SSH disconnect)** | The SSH connection drops and the session dies. | Use `tmux` or `screen`. See the [operations guide](references/operations-guide.md). |
| **Agent drifts from the plan** | After many batches, the agent starts making changes that weren't in the plan. | Host-native/legacy routes re-read after host pushes; trusted full-run carries one complete packet and the parked host reconciles at terminal/safety wake. Plan hashes, durable lessons, and a live (not append-only) survival guide anchor decisions. |
| **Merge conflicts on push** | `git push` fails because the remote has diverged. The agent may rebase and lose work, or stall. | Elves instructs the agent to fetch and merge (never rebase on shared branches). If conflicts can't be resolved cleanly, the agent triggers a Hard Stop rather than risking data loss. |
| **Two agents share a branch/checkout** | Claude and Codex (or two runs) write to the same branch in the same directory and clobber each other's files or move the branch mid-run. | One run owns one branch and one checkout. Use `./scripts/preflight.sh --create-worktree <branch> --base origin/main` when agents share a repo. Only the exact registered trusted full-run session may advance its assigned feature branch to a verified descendant; every other tripwire move stops as a collision. |

Most of these are prevented by the preflight checks. Run preflight, fix the warnings, and most
overnight failures never happen.

---

## Configuration

### Persistent preferences

Copy [`config.json.example`](config.json.example) to `config.json` in your installed skill or
project-local skill when you want defaults to persist across sessions. Put new Cobbler preferences
under the top-level `cobbler` block. The legacy `council` block is for compatibility with older
projects; if both blocks are present, `cobbler` wins. Math preferences belong under `math`.
Shared safe worker convenience also lives at `${XDG_CONFIG_HOME:-~/.config}/elves/config.json`
via `cobbler_agents.py preferences show|set|reset`.

### Tool configuration

Tool-specific configuration lives in the survival guide under `## Tool Configuration` — the
agent's instructions stay with the session. Minimal example:

```markdown
## Tool Configuration

### Validation Gates
- lint: `npm run lint`
- typecheck: `npm run typecheck`
- build: `npm run build`
- test: `npm test`

### Review
- method: github-pr-comments
```

If you don't configure validation gates, Elves auto-discovers them from your project files
(`package.json`, `Makefile`, `pyproject.toml`, `Cargo.toml`, `go.mod`). Full examples:
[`references/tool-config-examples.md`](references/tool-config-examples.md).

### Batch sizing

The default batch size is what a team of 4 developers would accomplish in a 2-week sprint. Each
batch must be independently shippable: code, tests, docs, and passing review before moving on.
Override in your plan or survival guide:

```markdown
## Batch Sizing
- team-size: 2
- sprint-length: 1 week
```

### Review methods

| Tier | Method | Configuration |
|---|---|---|
| **Tier 1** | GitHub PR comments + built-in review | Default (zero config). |
| **Tier 2** | Custom review API | Set `method: custom-api` and `review-api-url` in survival guide. |
| **Tier 3** | Additional checks | Smoke tests, screenshot diffs, or any custom script returning 0/non-zero. |

The agent uses the highest tier you have configured. Persistent false positives (3+ cycles) are
dismissed with a written explanation in the execution log.

Worker confidence now actively guides the primary review on both Claude Code and Codex. Trusted
full-runs return a bounded machine-produced review block at terminal; native workers supply the
same information through `Confidence:` commit trailers. The reviewer starts with that triage,
deep-checks every reservation, low-confidence or conflicting area, and reports what it verified.
Missing signals fall back to the full baseline review, and high confidence never reduces gates or
review scope. See [`references/review-subagent.md`](references/review-subagent.md).

### Memory hygiene

Long runs clean up as they go: keep live docs concise, archive old execution-log entries, promote
durable lessons, stop idle resources, and write a reactivation handoff when a fresh thread would
be faster. Elves does **not** delete local app state, chat databases, installed skills, plugins,
or automations as part of a coding run. For explicit local maintenance, see the safe-maintenance
pattern in [`references/autonomy-guide.md`](references/autonomy-guide.md).

---

## Repository reference index

The compact canonical workflow is [`SKILL.md`](SKILL.md); [`AGENTS.md`](AGENTS.md) is the thin
Codex adapter (invocation surface only — same workflow, same safety). Each contract lives in
exactly one file below; other docs link instead of restating.

**Run lifecycle**
- [`references/plan-template.md`](references/plan-template.md) — how to write a plan (stable
  `B#-A#` acceptance ids)
- [`references/kickoff-prompt-template.md`](references/kickoff-prompt-template.md) — staging
  kickoff, including the worker packet and teardown expectations
- [`references/survival-guide-template.md`](references/survival-guide-template.md) — Run Control,
  Stop Gate, compaction recovery
- [`references/execution-log-template.md`](references/execution-log-template.md),
  [`references/learnings-template.md`](references/learnings-template.md) — run memory
- [`references/schema-and-acceptance.md`](references/schema-and-acceptance.md) — session schema,
  acceptance identity, worker packet at staging, work-driver spellings, landing/cleanup order
- [`references/landing-authority.md`](references/landing-authority.md) — readiness vs merge
  authority
- [`references/e2e-chat-to-land.md`](references/e2e-chat-to-land.md) — the end-to-end paths

**Delegation and providers**
- [`references/joyful-runs-contract.md`](references/joyful-runs-contract.md) — full-run operator
  contract (canonical code: `scripts/cobbler_runtime/canonical_contract.py`)
- [`references/adaptive-worker-routing.md`](references/adaptive-worker-routing.md) — who
  implements and why
- [`references/prewalk.md`](references/prewalk.md) — exact-session guide→execution trajectory,
  qualification, checkpoints, and recovery
- [`references/parallelves.md`](references/parallelves.md) — Cobbler-coordinated parallel
  implementation lanes: serial default, recommend-only width test, trunk -> lanes -> integration
- [`references/follow-mode.md`](references/follow-mode.md) — the parked driver's sanitized stream
- [`references/grok-open-source-worker.md`](references/grok-open-source-worker.md) and
  [`references/grok-implementer-launch-prompt.md`](references/grok-implementer-launch-prompt.md)
  — external workers
- [`references/model-onboarding.md`](references/model-onboarding.md),
  [`references/cobbler-setup-recipes.md`](references/cobbler-setup-recipes.md) — setup
- [`references/provider-shortcuts.md`](references/provider-shortcuts.md) — focused Fugu,
  Manus, Grok Build, and Devin command routes
- [`references/host-parity.md`](references/host-parity.md) — Claude Code / Codex parity
- [`references/project-landing-profiles.md`](references/project-landing-profiles.md) — tracked
  repository-specific exact-HEAD readiness checks

**Quality and proof**
- [`references/proof-and-review.md`](references/proof-and-review.md) — impact-selected proof,
  convergent review
- [`references/verification-patterns.md`](references/verification-patterns.md),
  [`references/validation-guide.md`](references/validation-guide.md) — gates
- [`references/review-subagent.md`](references/review-subagent.md) — independent review
- [`references/autonomy-guide.md`](references/autonomy-guide.md) — staying unattended
- [`references/operations-guide.md`](references/operations-guide.md) — sleep prevention, tmux,
  monitoring, notifications, SessionStart hook, daily briefing

**Domain workflows**
- [`references/math-workflow.md`](references/math-workflow.md) and the `references/math-*.md`
  family — the math research pack
- [`references/open-ended-guide.md`](references/open-ended-guide.md) — open-ended runs
- [`references/council-workflow.md`](references/council-workflow.md),
  [`references/council-prompts.md`](references/council-prompts.md),
  [`references/councilelves-launch-prompt.md`](references/councilelves-launch-prompt.md) — legacy
  Council surfaces (Council is a deprecated alias of Cobbler)

**Templates and reports**
- [`references/elves-report-template.html`](references/elves-report-template.html) — end-of-run
  report
- [`references/runtime-helper-paths.md`](references/runtime-helper-paths.md) — installed vs
  source-checkout helper paths

## Maintainers' gates (this repository)

```bash
# Elves source checkout:
python3 scripts/verify_repo.py --ci
# before operational-artifact cleanup, from a clean worktree:
python3 scripts/verify_repo.py --final-readiness \
  --session .elves-session.json
# after the narrow operational-artifact cleanup commit, on its clean current tip:
python3 scripts/verify_repo.py --ci --base-ref origin/main
test -z "$(git status --porcelain)"
```

These are maintainers' gates for this source checkout; the repo-only helper is not shipped in a
global skill install. Installed runs use their target project's gates plus the installed
`elves_landing_check.py` (see
[`references/runtime-helper-paths.md`](references/runtime-helper-paths.md)):

```bash
python3 "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py" \
  --session <session-path> --repo-root .
```

When the target tracks `.elves/landing-profile.json`, the landing check evaluates it automatically.
The standalone installed command is:

```bash
python3 "$ELVES_SKILL_ROOT/scripts/landing_profile.py" check \
  --repo-root . --base origin/main --json
```

Learning commands (`observe`, `propose`, `candidates`, `promote`, `waive`, `clear-waiver`) use the
same CLI. Only `promote` rewrites the tracked profile; runtime learning state stays under
`.elves/runtime/landing-profile/`.

Intentional source-checkout public-API breaks must be declared in the tracked
`api-break-approvals.json` for the exact `--version`. Every entry names one surface, a non-empty
reason, and a tracked in-repo plan. Strict verification rejects malformed, stale, untracked, or
plan-less approvals.

## File structure

```text
elves/
├── SKILL.md                  # canonical workflow (all hosts)
├── AGENTS.md                 # thin Codex adapter
├── README.md                 # this file
├── CHANGELOG.md              # version history (the only home of "vX adds…")
├── config.json.example       # persistent preferences
├── aliases/                  # managed Claude Code alias skills
├── guide/                    # published user guide (GitHub Pages)
├── references/               # one authoritative file per contract (see index)
├── scripts/                  # helpers + cobbler_runtime package
├── tests/                    # unittest suite (hermetic: fd-0 devnull guard)
└── .ai-docs/                 # durable architecture/conventions/gotchas
```

## Platform support

| Platform | File | Subagents | Notes |
|---|---|---|---|
| Claude Code | SKILL.md | Yes | Full feature set |
| Codex | SKILL.md | Varies | Use review subagents when available; otherwise do the review directly. `AGENTS.md` remains the repo-local Codex companion |
| Claude.ai | SKILL.md (zip upload) | No | Upload as skill |
| Any Agent Skills compatible | SKILL.md | Varies | Open standard |

## Philosophy

Convert idle hours into shipped code: try, check, feed back, repeat. Memory lives in files, not
chat. Root cause over band-aids; centralize over duplicate; extend over create; favor boring
technology. The human owns what is worth building and whether it merges — the agent owns the
middle.

## Contributing

Issues and pull requests are welcome. If you find a bug, have a feature idea, or want to add
support for a new platform or tool, open an issue to discuss it first.

When submitting a PR:
- Keep changes focused: one concern per PR.
- Update the relevant template or reference file if your change affects agent behavior.
- Test your change with at least one real overnight run if possible.
- For cross-file skill/doc changes, run:
  ```bash
  python3 scripts/check_repo_consistency.py
  ```

## Disclaimer

This software is provided "as is", without warranty of any kind, express or implied. Neither
Aigora nor John Ennis are liable for any claims, damages, or other liability arising from using
this software. That includes code changes, data loss, security incidents, infrastructure costs, or
anything else that happens. The [MIT license](LICENSE) already says this, but we want to be clear
about it here too.

Elves expects you to grant your AI agent the permissions it needs to run autonomously. That might
mean file system access, git push, GitHub CLI auth, shell command execution, or other tool
approvals depending on your platform. If the agent has to pause and wait for permission during an
unattended run, it'll stall. So the skill works best when you pre-approve what the agent will
need. You're granting those permissions at your own risk. Know what you're allowing before you
walk away.

There's nothing uniquely dangerous about Elves. It uses standard tools (git, GitHub, your existing
test suite) and it has safety measures (forbidden commands, test integrity rules, scoped rollback
refs). But no software is foolproof, and an agent running for hours with broad permissions can
make mistakes. Always review the PR before merging.

## License

MIT, see [LICENSE](LICENSE).

Copyright (c) 2026 Aigora.
