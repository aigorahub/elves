---
version: "2.34.1"
---

# Elves: Codex repository adapter

This file is a **thin Codex adapter**, not a second workflow fork. The compact
**canonical workflow is `SKILL.md`** — every contract below is a pointer into it or into one authoritative
`references/` file, never a restatement. Differences here are **invocation surface only**;
workflow semantics, the safety kernel, landing policy, and acceptance identity are identical for
Claude Code and Codex (see `references/host-parity.md`).

The task-first user guide is published at `https://aigorahub.github.io/elves/`. This adapter and
`SKILL.md` remain authoritative when the guide is too short to cover an edge case.

## Cobbler

Use Cobbler via `$elves cobbler: <task>`, `$elves council: <task>`, or natural language
("Ask the Cobbler…"). Do **not** invent top-level Codex slash commands; Claude Code managed aliases
(`/cobbler`, `/setup-cobbler`, …) are Claude-specific surfaces. Full Cobbler protocol: SKILL.md
`## Cobbler`.

**Codex Goals** are optional host continuation plumbing (`references/codex-goals.md`) — distinct
from **Grok Build goal mode**, the optional worker capability that is a
capability-proven enhancement with a recorded one-packet fallback; Grok models come only from the
authenticated live catalog (`references/adaptive-worker-routing.md`).

## v2.24 run tools (host-neutral)

The v2.24 helpers — futile re-drive guard (`redrive`), learnings ledger (`learnings`),
observed-usage ledger (`usage`), salvage previews (`salvage`), and the continuity watchdog
manager (`continuity`) — are **host-neutral CLI helpers** with identical semantics on Claude
Code, Codex, Grok Build, and Oh My Pi: invoke them as
`python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" <verb> …` from any host. They are
advisory instruments (never landing, merge, credential, or routing authority), there are **no
per-host slash surfaces for them** — do not invent top-level Codex or Grok commands — and the
workflow contracts that mandate them (SKILL.md worker-failure recovery, labor completeness,
Skill Memory) apply to all four hosts unchanged. See the guide's "v2.24 run tools" section.

## Codex invocation (host-honest)

| Intent | Codex |
|--------|--------|
| Run Elves | natural language or skill load; not an invented top-level `/elves` |
| Cobbler | `$elves cobbler: <task>` or "Ask the Cobbler…" |
| Cobbler Mode | `$elves cobbler-mode` or natural "Cobbler Mode: on/off" |
| Setup | `$elves setup-cobbler` / `$elves setup-council` |
| Provider shortcut | `$elves fugu [--deep\|--ultra\|--max] [--max-wait SECONDS] [--preflight] [--include PATH] <planning-task>` / `$elves fugu [--deep\|--cyber\|--ultra\|--max] [--max-wait SECONDS] [--preflight] review <scope>`, `$elves manus [--wide\|--fanout] …`, `$elves grok <instructions>`, `$elves devin <instructions>`, or `$elves omp <instructions>` |
| Land PR | natural language; `\land-pr` / `/land-pr` when the host maps them |

### Provider subprocess capabilities map

For explicit provider-shortcut intent, follow SKILL.md **Provider shortcut protocols** and
`references/provider-shortcuts.md`. Resolve helpers from the active installed skill root; do not
assume `./scripts` belongs to the target repository and do not execute mappings blindly:

- Fugu planning task → `run_fugu.sh [--deep|--ultra|--max] [--max-wait SECONDS] [--preflight] [--include PATH] <planning-task>`; explicit
  review → `run_fugu.sh [--deep|--cyber|--ultra|--max] [--max-wait SECONDS] [--preflight] review <scope>`. Planning output follows the task instead
  of a forced review rubric; review retains read-only base/change evidence and ordered findings.
  **Host Fugu routing:** natural “use Fugu” without an explicit profile flag is host-routed. Before
  launch, choose planning vs `review <scope>`, plain / `--deep` / `--cyber` / `--ultra` / `--max`
  (profile locks model + effort; no free model slug), and
  optional `--include` paths; state one short `Fugu route: …` line; prefer the cheapest matching
  lane; explicit user flags always win. Plain regular Fugu is the default. The host may select
  `--cyber` only for explicit security review intent after a successful Cyber call in the current
  session. Only a user-explicit `--cyber` request may establish that proof. Otherwise, use regular
  Fugu. The user must explicitly select `--ultra`
  or `--max`. Host-native first for
  inventory/triage/greps; prefer `--max-wait` over automatic `--deep`; if any `--include`, run
  `--preflight` first (never gitignored paths); redirect to a log (never `| tail`); chat cancel does
  not stop the provider; harvest `Fugu partial salvage` from the log on timeout/crash before
  relaunch. The isolation snapshot is always on; the host only adds exact admitted
  context via `--include`, not a separate “minimal snapshot” mode. Full table:
  `references/provider-shortcuts.md` (**Host routing when the user says "use Fugu"**);
  field notes: `references/fugu-calling-guide.md`.
  All profiles receive a bounded policy-admitted tracked plus non-ignored-untracked snapshot. The host may
  select exact context, but the safety kernel rejects ignored/credential/operational/configuration
  paths (including both `.env.*` and `*.env` variants and reserved internal namespaces), unsafe
  file types, links, modes, races, and repository escapes. Exact includes must be admitted or fail.
  Fugu is limited to planning and read-only review. `--write` is rejected. Read-only macOS cleanup is
  best-effort and non-authoritative. No Linux procfs is mounted; only a synthetic `/proc/self/exe`
  link to the qualified real Codex binary is exposed. Codex external-sandbox mode runs
  inside the mandatory outer boundary. Profiles remain `fugu/high`, `fugu/xhigh` for `--deep`,
  `fugu-cyber/xhigh` for `--cyber`, `fugu-ultra-v1.1/high` for `--ultra`, and
  `fugu-ultra-v1.1/max` for `--max` (60-minute default
  wall budget, one narrow high-stakes gate); Ultra uses exact-session staged synthesis and bounded incremental
  event parsing through a host-owned pipe, pins final output to a no-follow descriptor, and runs a
  final descriptor-safe writable-state audit after settlement.
- Manus research → `run_manus.sh <topic>` for one private bounded task, or
  `run_manus.sh --wide --items-file <roster.json> [--file <source>] <goal>` for Cobbler-managed
  native-Wide-first research with exact coverage repair; use `--fanout` for deterministic
  one-task-per-item execution and `--resume <manifest>` for duplicate-safe continuation; new
  manifests are reserved before provider uploads, and ambiguous paid creates fail closed pending
  operator reconciliation
- Grok Build task → `run_grok.sh <instructions>` (headless, non-bypass permissions, disposable
  tracked-source snapshot in a required outer kernel sandbox, built-in inner `strict`, isolated `dontAsk`
  plus bypass lock, explicit `XAI_API_KEY`, a key-scrubbing tool shell, and no Linux procfs; no
  shared OAuth file)
- Devin task → `run_devin.sh <instructions>` (remote session, bounded wait, no default stored
  secret or knowledge grants; creation and polling share one hard wall-clock bound)
- Oh My Pi task → `run_omp.sh <instructions>` (optional headless worker shortcut under other hosts;
  never `opm`; omp is also a supported main driver via `~/.omp/agent/skills/elves`; run-scoped
  profile isolation; Linux omits procfs and has no Codex `/proc/self/exe` view)

Codex uses the `$elves` or natural-language forms above, not invented top-level `/fugu`, `/manus`,
`/grok`, `/devin`, or `/omp` commands. Explicit invocation authorizes the provider call and any associated
provider usage, but not merge, protected-ref, secret, or approval-bypass authority.

## Workflow pointers (SKILL.md owns every contract)

- **Default path:** one kickoff; **chat-to-work** stops at a landable PR, **chat-to-land** merges
  only with explicit authorization; the default worker is a separate
  subscription-native Codex/Claude worker using SKILL.md's exact same-model/lower-effort route map
  (plan-matched effort for unlisted routes), with no transferable parent/worker prompt-cache
  promise (SKILL.md, `references/adaptive-worker-routing.md`, and
  `references/e2e-chat-to-land.md`)
- **Landable is plan Acceptance with proof** — landing check:
  `python3 "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py" --session <session-path> --repo-root .`
  (session `plan_path` is authoritative; explicit `--plan` is only an equality assertion)
- **Project landing profiles:** a tracked `.elves/landing-profile.json` may add bounded,
  declarative exact-HEAD path co-change checks. Executable checks are unsupported; missing is
  neutral; present invalid or blocking-failed is red; live results are recomputed host-owned digest
  inputs that worker reports cannot override, and never authority. Host-owned
  observe/propose/promote/waive learning stays under `.elves/runtime/landing-profile/` with no
  auto-promotion (`references/project-landing-profiles.md`)
- **Helper paths:** `python3 scripts/...` is **source-checkout shorthand**; installed skills
  (`~/.claude/skills/elves`, `~/.codex/skills/elves`, `~/.grok/skills/elves`, or `~/.omp/agent/skills/elves`) resolve helpers from the
  **active Elves skill root** while keeping the target repository as the working directory. An
  installed Elves bundle never requires a repo-only helper (`references/runtime-helper-paths.md`)
- **Stop control:** honor the **Stop Gate** and `continuation_guard`; no final response while
  stopping is disallowed
- **Handoff standard:** every worker packet carries intent/why, **Build On** targets,
  **owned surfaces**, **forbidden surfaces**, **acceptance evidence**, failure modes, and
  identity/output format — an incomplete handoff is a **blocking coordinator defect**; for
  delegable runs the consolidated packet is a staging deliverable recorded as
  `worker_packet_path`; an explicitly declared handoff-v1 session/capsule is strict and
  host-neutral (`references/schema-and-acceptance.md`)
- **Git history as operator UI:** subjects use
  `[<branch> · Batch N/total · Contract|Implement|Validate|Review|Close] <concrete outcome>`;
  **Forbid vague subjects** (anti-patterns: `[feat/auth · Batch 3/12] Updates`,
  `[feat/auth · Batch 3/12 · Implement] progress`); commit cadence and phase roles per SKILL.md
  (≥1 pushed non-Close slice before the single acceptance-backed Close; driver reconciles use
  Review)
- **Worker failure recovery:** transient provider errors back off and resume without consuming
  the re-drive budget; workers keep an untracked progress ledger under `.elves/runtime/`
  (SKILL.md Worker failure recovery)
- **Confidence-guided review:** attach the terminal full-run
  `review_context.review_prompt_block` verbatim, or derive the identical table from native
  `Confidence:` trailers; Claude Code/Codex semantics are identical
  (`references/review-subagent.md`; `references/host-parity.md`)
- **Parallel lanes (Parallelves):** serial default; `worker.parallel=auto` is recommend-only and
  nothing auto-launches (`references/parallelves.md`; SKILL.md Parallel lanes)
- **Prewalk:** exact-session guide→execution continuity only; a cold packet handoff is not prewalk,
  and post-edit cold fallback is forbidden (`references/prewalk.md`; SKILL.md Exact-session prewalk)
- **Worktree lifecycle:** One run owns one branch and one checkout; staging records
  `worktree_path`; post-merge teardown uses the separate gc helper
  (`./scripts/preflight.sh --gc-worktrees`)
- **Unattended:** gates and helper subprocesses run with closed stdin and explicit timeouts
  (`references/autonomy-guide.md`)
- **Public API surface snapshots:** optional regression evidence; `required: true` only by
  explicit survival-guide opt-in (SKILL.md)
- **Preferences:** safe worker convenience at `${XDG_CONFIG_HOME:-~/.config}/elves/config.json`;
  repository safety vetoes outrank everything

## Host check (Grok Build)

Supported main drivers are Claude Code, Codex, Grok Build, and Oh My Pi (omp). If this skill is loaded inside
**Grok Build** as the orchestrator, **stage and run Elves** under the normal workflow. Required
prewalk runs the bounded automatic qualification canary before task launch when matching proof is
absent; experimental prewalk accepts qualification uncertainty without relaxing runtime checks.
Grok remains an optional **worker** under Claude/Codex as well. Full wording: SKILL.md
`## Supported main drivers (host check)`.

## Recovery (same as SKILL)

After compaction: survival guide (Stop Gate + Run Control) → `.elves-session.json` → learnings →
plan → execution log → `.ai-docs/manifest.md` → constitution. Resume the single next required
action immediately.

## Authoritative sources when this file and SKILL disagree

**`SKILL.md` wins** for workflow. This adapter wins only for Codex invocation wording. If you find
divergence, fix this file to re-point at SKILL rather than re-forking protocol text.

## Docs hygiene

Treat stale user-facing docs as **PENDING-DOCS** until updated (see SKILL.md).

Runtime helpers (v2.22): `planning_harvest`, `tool_output_compact`,
