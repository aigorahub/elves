# Optional Oh My Pi (omp) worker

Oh My Pi is an optional autonomous worker. Native Claude Code, Codex, or Grok Build remains
the default main driver. omp never receives protected-ref, PR, merge, or final-acceptance authority.

## Name

- Product: **Oh My Pi**
- CLI: **`omp`**
- Adapter: **`omp-cli`**
- Never spell the CLI as `opm`.

## Install and authenticate

Install omp from the official Oh My Pi distribution, then authenticate a provider (API key or
OAuth). Set exactly one provider credential in the environment before a launch (for example
`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `XAI_API_KEY`), or complete the
provider OAuth flow omp documents for that model.

## Trusted full-run (parked worker)

Host stages an Elves packet and launches `omp-cli` with:

- `omp --mode json --cwd <worktree> --profile elves-omp-<run> --model <id> --thinking <level> --approval-mode yolo @packet …`
- Session UUID captured from the first NDJSON `{"type":"session","id":…}` event
- Resume: `omp --resume <exact-uuid> …` only
- Forbidden: `--continue`, `-c`, latest/most-recent, omp `--prewalk` (not Elves prewalk)

Worker may edit and commit only the assigned feature branch in the registered worktree.
Host retains planning, run memory, PR, readiness, and merge.

## Isolation

- Full-run and shortcut always use a run-scoped `--profile`.
- Shortcut: private HOME/XDG via `isolated_lane`; empty `~/.claude/tools` under that home.
- Full-run session capture reads supervisor-owned transport files only (never worker
  `events.jsonl` for provider identity); session id must be a UUID.
- Grant only the single provider key matching the pinned model.

## Shortcut

```bash
# Require ELVES_OMP_MODEL when more than one provider key is present.
# Grant only the single matching provider key name (for example GEMINI_API_KEY).
export ELVES_OMP_MODEL=google/gemini-2.5-flash
"$ELVES_SKILL_ROOT/scripts/run_omp.sh" "<task>"
```

Claude: `/omp …`. Codex/Grok: `$elves omp …` or natural language.

- Uses Elves `isolated_lane` snapshot (cwd is the disposable snapshot, not the live checkout).
- Projects **one** provider-matched API key only (from `ELVES_OMP_MODEL` family).
- Read-only: `ELVES_OMP_WRITE` is rejected; use parked `omp-cli` full-run for implementation.
- Validates `--mode json` stdout with `decode_omp_jsonl` when nonempty.
- Finite wall: `ELVES_OMP_MAX_WAIT_SECONDS` (default 600).


## Non-goals

- omp as a main Elves driver (deferred)
- Elves exact-session prewalk host profile for omp (deferred)
- Requiring omp for native runs
