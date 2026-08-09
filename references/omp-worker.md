# Oh My Pi (omp): main driver and optional worker

Oh My Pi has **two** Elves roles. Keep the tokens distinct.

| Role | Token | When |
|------|--------|------|
| Main driver | `omp` (host) | User opens `omp`; Elves skill at `~/.omp/agent/skills/elves` |
| Optional worker | `omp-cli` adapter; `/omp` shortcut | Claude Code, Codex, or Grok Build drives; parks labor on omp |

The user owns merge authorization. Workers never receive protected-ref, PR, merge, or final-acceptance authority.

## Name

- Product: **Oh My Pi**
- CLI: **`omp`**
- Worker adapter: **`omp-cli`**
- Never spell the CLI as `opm`.
- Never resolve **`omp-cli` as a main host** token.

## Main driver (host)

Install Elves for omp:

```bash
python3 "$ELVES_SKILL_ROOT/scripts/sync_installed_skills.py" --apply --target omp
# root: ~/.omp/agent/skills/elves
# (source-checkout shorthand: python3 scripts/sync_installed_skills.py …)
```

Open `omp` and load the Elves skill like other hosts. Host owns staging, canonical memory, prewalk
supervision, PR preparation, and readiness. Native worker sessions use a **separate** run-scoped
`--profile` from the interactive host profile. Elves prewalk is the exact-session supervisor contract
in `references/prewalk.md`; **never** pass omp product `--prewalk` as Elves prewalk.

## Trusted full-run (parked worker under another host)

Host stages an Elves packet and launches `omp-cli` with:

- `omp --mode json --cwd <worktree> --profile elves-omp-<run> --model <id> --thinking <level> --approval-mode yolo …`
- Session UUID from typed NDJSON `{"type":"session","id":…}` (supervisor-owned capture)
- Resume: `omp --resume <exact-uuid> …` only
- Forbidden: `--continue`, `-c`, latest/most-recent, omp product `--prewalk`

Worker may edit and commit only the assigned feature branch in the registered worktree.

## Isolation

- Full-run and shortcut always use a run-scoped `--profile`.
- Shortcut: private HOME/XDG via `isolated_lane`; empty `~/.claude/tools` under that home.
- Full-run session capture reads supervisor-owned transport files only.
- Grant only the single provider key matching the pinned model.

## Shortcut

```bash
export ELVES_OMP_MODEL=google/gemini-2.5-flash
"$ELVES_SKILL_ROOT/scripts/run_omp.sh" "<task>"
```

Claude: `/omp …`. Codex/Grok: `$elves omp …` or natural language.

- Uses Elves `isolated_lane` snapshot.
- Projects **one** provider-matched API key only.
- Read-only: `ELVES_OMP_WRITE` is rejected; use parked `omp-cli` full-run for implementation.
- Finite wall: `ELVES_OMP_MAX_WAIT_SECONDS` (default 600).

## Non-goals

- Making omp mandatory for native Claude/Codex/Grok runs
- Using omp product `--prewalk` as Elves prewalk
- Self-granted merge/protected-ref authority for any omp path
