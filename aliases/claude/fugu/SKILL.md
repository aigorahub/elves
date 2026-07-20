---
name: fugu
description: Run an independent, read-only Sakana Fugu Ultra audit of one file. Use when the user types /fugu or asks for a Fugu review.
disable-model-invocation: true
---

<!-- elves-managed-alias: claude-skill-alias v1 -->

# Fugu Ultra Review

This is the Elves-managed Claude Code alias for `/fugu <file>`.

Load the installed `elves` skill's **Provider shortcut protocols** and
`references/provider-shortcuts.md`. Resolve `scripts/run_fugu.sh` from the active Elves skill root,
keep the target repository as the working directory, validate the one file argument, and run it.
The runner is read-only and pins `fugu-ultra` at `xhigh`; do not replace it with an improvised curl
request or a different model spelling.
