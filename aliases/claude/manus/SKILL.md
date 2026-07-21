---
name: manus
description: Launch bounded private Manus research, including Cobbler-managed Wide Research and deterministic reference fan-out. Use when the user types /manus.
disable-model-invocation: true
---

<!-- elves-managed-alias: claude-skill-alias v1 -->

# Manus Research

This is the Elves-managed Claude Code alias for `/manus <topic>` and the roster forms
`/manus --wide|--fanout --items-file <roster.json> …`.

Load the installed `elves` skill's **Provider shortcut protocols** and
`references/provider-shortcuts.md`. Resolve `scripts/run_manus.sh` from the active Elves skill root,
keep the target repository as the working directory, validate the arguments and `MANUS_API_KEY`,
and run it. Preserve private visibility, bounded waits, structured coverage, ignored manifests,
and duplicate-safe `--resume` behavior instead of improvising API calls. In `--wide` mode Cobbler
is the outer orchestrator: it accepts native Wide Research only after exact roster reconciliation,
repairs missing/duplicated items with deterministic fan-out, and synthesizes last.
