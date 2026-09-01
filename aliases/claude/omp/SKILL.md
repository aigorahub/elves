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
