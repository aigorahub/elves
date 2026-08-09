# Learnings — omp main driver run

## Digest

- Phase 1 (v2.25.0) is optional worker only; main driver is separate product surface.
- Fugu Ultra 2026-08-09: freeze skill path only from installed-binary probe; ordinary launch before parity claims.
- omp product `--prewalk` is not Elves prewalk.

## Active learnings

- [L1] (from Phase 1 + Fugu) Install root candidates start at `~/.omp/agent/skills/`; shadowing from Claude/Codex/`.agents` is real. (expect: B0.1 probe)
- [L2] `worker_routing.py` and `cobbler_agents.py` currently hard-limit hosts to Claude/Codex/Grok; a host_profiles row alone is insufficient. (expect: B1)
- [L3] `launch_ready=False` blocks ordinary single-phase native launch; release cannot claim main-driver parity without ordinary launch proof. (expect: B1-A7 / B4)

## Retired learnings

(none yet)
