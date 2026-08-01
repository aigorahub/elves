# Structural-debt next-wave disposition (AIG-279 / #206)

Date: 2026-08-01

| Item | Disposition in v2.22 |
|------|----------------------|
| Secret-file deny-list union | **Shipped** (shared `context.SECRET_FILE_*`) |
| run_fugu heredoc extract | **Shipped** (`cobbler_runtime/fugu.py`) |
| Compaction P3/P4 | **Shipped** (operations-guide + prewalk) |
| Parallelves Phase 2 + runtime supervision | **Shipped** (`validate_lane_staging`, `LaneSupervisor`) |
| Tool-output compact layer | **Shipped** (`tool_output_compact`) |
| Bounded subprocess sweep (C-03) | Deferred — track separately if still hot after compact layer |
| Atomic session writes (C-04) | Deferred — existing storage helpers remain |
| run_grok wall budget (C-05) | Deferred — not blocking planning harvest |
| Remaining survey rows | Explicitly deferred; open only as new issues when scheduled |

Umbrella AIG-279 closes against this disposition: shipped items have code/tests;
deferred items are named, not silent.
