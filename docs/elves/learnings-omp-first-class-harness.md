# Learnings — omp first-class harness

## Digest

- Prefer Devin-style stream-captured session IDs when a CLI lacks caller-assigned `--session-id`.
- Never map Elves prewalk to omp `--prewalk` (different product meaning).
- Isolate omp profiles away from host `~/.claude/tools` binary trees.

## Active learnings

- [L1] (expect: B0 decoder tests) omp `--mode json` first line is typically
  `{"type":"session","version":3,"id":"<uuid>",...}` — bind that id before trusting labor.
  Evidence: live probe 2026-08-09 on omp/17.2.12.
- [L2] (expect: isolation tests) omp discovers custom tools under `~/.claude/tools`; Claude Code
  may store full Node/npm trees there. Importing those paths runs npm with process argv.
  Evidence: local setup incident before this run.
- [L3] Elves forbids ambiguous resume tokens including `continue`; omp advertises `--continue` —
  adapter must never pass it.

## Retired learnings

(none)
