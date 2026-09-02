---
name: omp
description: Bounded Oh My Pi (omp) provider shortcut via Elves. Use when the user says /omp or "use omp" for a one-shot task.
---
<!-- elves-managed-alias: claude-skill-alias v1 -->

# /omp

Resolve the runner from the **active Elves skill root** and keep the target repository as cwd:

```bash
"$ELVES_SKILL_ROOT/scripts/run_omp.sh" <task>
```

- CLI binary is **`omp`** (Oh My Pi), never `opm`.
- Read-only by default (`--approval-mode always-ask`). Set `ELVES_OMP_WRITE=1` only when the host independently authorizes writes.
- Optional model pin: `ELVES_OMP_MODEL=<provider/model>`.
- Uses a run-scoped `--profile` (no ambient host HOME / `~/.claude/tools` inheritance).
- Linux omits procfs and has no `/proc` view; it does not receive Fugu's synthetic Codex
  `/proc/self/exe` link.
- Never grants PR, merge, protected-ref, or landing authority.
- For trusted overnight labor, use the full-run `omp-cli` worker path instead of this shortcut.

Codex/Grok: `$elves omp …` or natural language — do not invent top-level Codex slash commands.

Read-only review snapshots omit oversized binary media instead of failing the whole review. Video,
audio, presentation, archive, image, font, and 3D binaries above the per-file limit are left out and
listed in the context manifest with path, byte size, and reason; the 16 MiB per-file limit is not
raised. Source, prose instructions, executable agent configuration, and `--include` paths still fail
closed and ask for a derived text, image, or transcript artifact.

omp is an optional review route, like Fugu. On any non-zero exit the runner prints one
directive line naming the reason
(`quota`, `authentication`, `catalog`, `runner`, `timeout`, or `provider`). Select another available
independent reviewer instead of stopping, record requested route, actual route, and fallback reason,
and do not claim a review ran when it did not:
`python3 "$ELVES_SKILL_ROOT/scripts/cobbler_agents.py" review-route --host claude-code --requested
omp --unavailable omp=<reason> --json`.
