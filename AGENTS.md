---
version: "2.11.0"
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

## Codex invocation (host-honest)

| Intent | Codex |
|--------|--------|
| Run Elves | natural language or skill load; not an invented top-level `/elves` |
| Cobbler | `$elves cobbler: <task>` or "Ask the Cobbler…" |
| Cobbler Mode | `$elves cobbler-mode` or natural "Cobbler Mode: on/off" |
| Setup | `$elves setup-cobbler` / `$elves setup-council` |
| Land PR | natural language; `\land-pr` / `/land-pr` when the host maps them |

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
- **Helper paths:** `python3 scripts/...` is **source-checkout shorthand**; installed skills
  (`~/.claude/skills/elves` or `~/.codex/skills/elves`) resolve helpers from the
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

Supported main drivers are Claude Code and Codex only. If this skill is loaded inside **Grok Build**
as the orchestrator (Claude skill compat often surfaces it), **do not stage or run Elves** — refuse
and redirect to Claude Code or Codex. Grok remains an optional **worker** under a supported host.
Full wording: SKILL.md `## Supported main drivers (host check)`.

## Recovery (same as SKILL)

After compaction: survival guide (Stop Gate + Run Control) → `.elves-session.json` → learnings →
plan → execution log → `.ai-docs/manifest.md` → constitution. Resume the single next required
action immediately.

## Authoritative sources when this file and SKILL disagree

**`SKILL.md` wins** for workflow. This adapter wins only for Codex invocation wording. If you find
divergence, fix this file to re-point at SKILL rather than re-forking protocol text.

## Docs hygiene

Treat stale user-facing docs as **PENDING-DOCS** until updated (see SKILL.md).
