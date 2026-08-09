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
OAuth). Example API key:

```bash
export GEMINI_API_KEY=…
# or ANTHROPIC_API_KEY / OPENAI_API_KEY / XAI_API_KEY for other models
```

## Trusted full-run (parked worker)

Host stages an Elves packet and launches `omp-cli` with:

- `omp --mode json --cwd <worktree> --profile elves-omp-<run> --model <id> --thinking <level> --approval-mode yolo @packet …`
- Session UUID captured from the first NDJSON `{"type":"session","id":…}` event
- Resume: `omp --resume <exact-uuid> …` only
- Forbidden: `--continue`, `-c`, latest/most-recent, omp `--prewalk` (not Elves prewalk)

Worker may edit and commit only the assigned feature branch in the registered worktree.
Host retains planning, run memory, PR, readiness, and merge.

## Isolation

- Always pass a run-scoped `--profile` so host agent roots are not ambiently reused.
- Do not wholesale mount host `HOME` or `~/.claude/tools` (Claude may store binaries there;
  omp would try to load them as custom tools).
- Grant only the provider env keys required for the pinned model.

## Shortcut

```bash
"$ELVES_SKILL_ROOT/scripts/run_omp.sh" "<task>"
```

Claude: `/omp …`. Codex/Grok: `$elves omp …` or natural language. Read-only by default;
`ELVES_OMP_WRITE=1` only when the host independently authorizes writes.
`ELVES_OMP_MODEL` pins a model. Finite wall: `ELVES_OMP_MAX_WAIT_SECONDS` (default 600).

## Non-goals

- omp as a main Elves driver (deferred)
- Elves exact-session prewalk host profile for omp (deferred)
- Requiring omp for native runs
