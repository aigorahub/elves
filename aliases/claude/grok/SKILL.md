---
name: grok
description: Run a bounded-permission headless Grok Build task. Use when the user types /grok or asks Grok Build to execute instructions.
disable-model-invocation: true
---

<!-- elves-managed-alias: claude-skill-alias v1 -->

# Grok Build Shortcut

This is the Elves-managed Claude Code alias for `/grok <instructions>`.

Load the installed `elves` skill's **Provider shortcut protocols** and
`references/provider-shortcuts.md`. Resolve `scripts/run_grok.sh` from the active Elves skill root,
keep the target repository as the working directory, validate the instructions and CLI, and run
it. Preserve the runner's headless `high`-reasoning, self-checking, non-bypass permission posture;
do not invent a model id or turn this shortcut into an Elves main-driver route. The Linux
boundary omits procfs and has no `/proc` view; it does not receive Fugu's synthetic Codex
`/proc/self/exe` link.
