---
name: fugu
description: Run an independent, project-aware Sakana Fugu repository review through codex-fugu. Use when the user types /fugu or asks for a Fugu review.
disable-model-invocation: true
---

<!-- elves-managed-alias: claude-skill-alias v1 -->

# Fugu Repository Review

This is the Elves-managed Claude Code alias for `/fugu [--deep|--ultra] <task>`.

Load the installed `elves` skill's **Provider shortcut protocols** and
`references/provider-shortcuts.md`. Resolve `scripts/run_fugu.sh` from the active Elves skill root,
keep the target repository as the working directory, pass through the optional profile and task,
and run it. The runner uses the official `codex-fugu` launcher with project access, a read-only
sandbox, an ephemeral session, closed interactive input, and a hard wall-clock bound. It selects
regular `fugu/high` by default, `fugu/xhigh` with `--deep`, or `fugu-ultra/high` with `--ultra`.
Do not replace it with an improvised API request or remove its sandbox and timeout controls.
