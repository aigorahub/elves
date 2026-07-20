---
name: devin
description: Start and boundedly follow a remote Devin development task. Use when the user types /devin with implementation instructions.
disable-model-invocation: true
---

<!-- elves-managed-alias: claude-skill-alias v1 -->

# Devin Remote Task

This is the Elves-managed Claude Code alias for `/devin <instructions>`.

Load the installed `elves` skill's **Provider shortcut protocols** and
`references/provider-shortcuts.md`. Resolve `scripts/run_devin.sh` from the active Elves skill root,
keep the target repository as the working directory, validate the instructions and
`DEVIN_API_KEY`, and run it. The explicit shortcut authorizes remote session creation, not merge or
protected-ref authority. Preserve the bounded wait and report the printed session/PR follow links.
