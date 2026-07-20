---
name: manus
description: Launch bounded, private Manus deep web research. Use when the user types /manus with a research topic.
disable-model-invocation: true
---

<!-- elves-managed-alias: claude-skill-alias v1 -->

# Manus Research

This is the Elves-managed Claude Code alias for `/manus <topic>`.

Load the installed `elves` skill's **Provider shortcut protocols** and
`references/provider-shortcuts.md`. Resolve `scripts/run_manus.sh` from the active Elves skill root,
keep the target repository as the working directory, validate the topic and `MANUS_API_KEY`, and
run it. The explicit shortcut authorizes task creation; preserve the runner's private visibility
and bounded wait instead of improvising an API request.
