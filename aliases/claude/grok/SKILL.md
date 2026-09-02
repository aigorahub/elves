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
it. Preserve the runner's headless non-bypass permission posture and its `high` reasoning default;
do not invent a model id or turn this shortcut into an Elves main-driver route.
The runner builds argv from the flags the installed Grok Build CLI advertises: an absent safety
flag (isolated `--cwd`, inner `--sandbox strict`, headless `--single`, `--output-format`,
explicit reasoning effort) fails closed, while a quality flag the installed version dropped is
simply not passed. Auto-update is disabled through the isolated `[cli] auto_update` config key
rather than a removed flag. Reasoning effort defaults to `high`; `ELVES_GROK_EFFORT` selects
`low`, `medium`, `high`, or `xhigh`, and `ELVES_GROK_MODEL` pins a model only when the
authenticated live catalog lists it. The runner reports the CLI version, effort, model, the
authentication route the CLI itself names, and any omitted flags. The Linux
boundary omits procfs and has no `/proc` view; it does not receive Fugu's synthetic Codex
`/proc/self/exe` link.

Read-only review snapshots omit oversized binary media instead of failing the whole review. Video,
audio, presentation, archive, image, font, and 3D binaries above the per-file limit are left out and
listed in the context manifest with path, byte size, and reason; the 16 MiB per-file limit is not
raised. Source, prose instructions, executable agent configuration, and `--include` paths still fail
closed and ask for a derived text, image, or transcript artifact.

Grok is an optional review route, like Fugu. On any non-zero exit the runner prints one
directive line naming the reason
(`quota`, `authentication`, `catalog`, `runner`, `timeout`, or `provider`). Select another available
independent reviewer instead of stopping, record requested route, actual route, and fallback reason,
and do not claim a review ran when it did not:
`python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" review-route --host claude-code --requested
grok --unavailable grok=<reason> --json`.
