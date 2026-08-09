# Worker packet — omp first-class harness (host-native implementer)

## 1. Intent / why

Implement Oh My Pi (`omp`) as an optional Elves parked full-run worker and thin provider
shortcut so overnight runs can delegate labor to omp under Claude/Codex/Grok drivers.

## 2. Non-obvious rationale

- Capture session UUID from JSON stream; do not invent `--session-id` if upstream lacks it.
- Never pass `--continue`.
- Do not treat omp `--prewalk` as Elves exact-session prewalk.
- Isolate profiles so host `~/.claude/tools` binaries are not loaded as custom tools.
- Keep Grok/Devin/host-native paths green; omp is optional and never a main driver in this run.

## 3. Build On targets

- `scripts/cobbler_runtime/adapters.py`, `schema.py`, `implement.py`, `full_run*.py`
- `capabilities.py`, `worker_routing.py`, `setup.py`, `onboard.py`, `provider_auth.py`
- Devin plan pattern: `docs/plans/devin-cli-worker-adapter.md`
- Grok worker docs: `references/grok-open-source-worker.md`
- Authoritative plan: `docs/plans/omp-first-class-harness.md`

## 4. Owned surfaces

Adapter/runtime, tests/fixtures, `run_omp.sh`, sync ship list, Claude alias, references,
SKILL/AGENTS pointers, CHANGELOG Unreleased, this plan’s acceptance evidence.

## 5. Forbidden surfaces

`main` merge, force-push, credentials in tree, global skill installs as product requirement,
weakening existing tests, granting worker merge/PR/protected-ref authority.

## 6. Acceptance evidence

Plan criteria B0-A* through B3-A* and M-A1..M-A4 with focused tests and docs.

## 7. Failure modes / pitfalls

- Silent fallback to `custom-cli`
- Ambiguous session resume
- Ambient HOME auth leakage
- Conflating product “prewalk” terms
- Breaking Grok/Devin fixtures

## 8. HEAD / run docs / output

- Branch: `feat/omp-first-class-harness`
- Worktree: `/Users/john/aigora/dev/elves-omp-first-class-harness`
- Start tip: `f53966679751819993dcb271f6343e3a656f0009`
- Plan / survival / learnings / execution log under `docs/plans` and `docs/elves`
- Output: commits with batch labels; summary of tests and residual risks
