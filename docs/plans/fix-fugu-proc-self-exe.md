# Plan: Restore Fugu Codex startup without procfs

## Mission

Allow the official `codex-fugu` launcher and Codex 0.149.1 to start inside the existing Linux
Fugu bwrap lane while preserving the lane's credential boundary. The lane must expose only the
self-executable identity Codex requires; it must not mount procfs or make process environments
available to model-directed commands.

## Scope

### In scope

- The shared bwrap argv builder and the official Fugu shortcut's use of it.
- Fugu isolation tests for executable identity and proc-based environment isolation.
- Durable Fugu isolation documentation needed to describe the synthetic self-executable view.
- A preflight and one tiny real read-only Fugu review smoke against throwaway scope.

### Out of scope

- Full procfs or any relaxation of the outer kernel boundary.
- Raw/direct Fugu or Codex provider workarounds outside `run_fugu.sh`.
- Changes to global Codex/Fugu installation, credentials, or `~/.codex`.
- The five `ds-*` worktrees, their `/workspace/ds-*-adoption` staging, other agents, PR landing,
  or merge.

## Batch 1 [B1]: Synthetic Codex self-executable view

- **Intent / why:** Restore official Codex startup without exposing the credential-bearing process
  tree through procfs.
- **Non-obvious rationale:** Codex 0.149.1 requires `readlink("/proc/self/exe")`; a regular bind at
  that pathname returns `EINVAL`, so the isolated view must resolve to the qualified, narrowly
  mounted real Codex executable while remaining an ordinary synthetic directory tree.
- **Build On targets:** `wrap_argv_with_sandbox`, existing narrow executable-runtime mounts, and
  Fugu's existing `mount_proc=False` route.
- **Owned surfaces:** `scripts/cobbler_runtime/isolation.py`, `scripts/cobbler_runtime/fugu.py`,
  Fugu isolation tests, and directly affected Fugu documentation.
- **Forbidden surfaces:** credentials, global installs, unrelated worktrees, other branches/agents,
  procfs mounts, weakened tests, raw provider calls, merge, and protected refs.
- **Acceptance evidence:** focused unit/live bwrap tests, relevant regression tests, argv inspection,
  preflight output, and a settled tiny official Fugu review log that proves Codex reached the model.
- **Failure modes / pitfalls:** confusing a regular bind with the symlink semantics required by
  `current_exe`, admitting an unqualified executable, accidentally combining the synthetic view
  with `--proc`, or proving only preflight rather than provider startup.
- **HEAD / run-doc paths / route-session identity / output format:** starts at
  `5d600bbc80c8c47cd17956a0a21abcc5e0a882ff` on `fix/fugu-proc-self-exe`; this plan is the
  acceptance source; host-native implementation; report branch, commits, tests, and startup result.

**Acceptance criteria:**

- [ ] B1-A1: A no-proc bwrap lane exposes `/proc/self/exe` as a symlink resolving to the exact
  qualified Codex executable, and construction fails closed for an invalid target or a request
  that also mounts procfs.
- [ ] B1-A2: The resulting bwrap argv contains no `--proc /proc`, and live sandbox proof shows
  `/proc/<pid>/environ` is unavailable, including for the credential-bearing parent namespace.
- [ ] B1-A3: Focused Fugu/isolation tests and the repository's relevant regression gate pass without
  weakening existing coverage.
- [ ] B1-A4: `$elves fugu --preflight review` succeeds and a tiny official `$elves fugu review`
  reaches Codex/model execution inside the sandbox rather than exiting on self-executable or config
  discovery.

**Docs likely touched:** this plan plus the authoritative Fugu isolation description.

**Risk:** `high` - the change sits on a credential-isolation boundary shared by external lanes.

**Caution:** Passing startup is insufficient unless the live lane still proves proc-based parent
environment reads impossible.

**Affected surfaces:** bwrap command construction, Fugu launch construction, isolation tests, Fugu
operator contract.

**Constitution impacts:** preserves the thin safety kernel; no authority, secret, or merge changes.

**Review focus:** exact executable qualification, bwrap option ordering, procfs absence, credential
non-observability, and whether non-Fugu callers retain current behavior.

**Focused tests:** `tests/test_dispatch_isolation.py`, affected provider-shortcut tests, and the two
requested official shortcut smokes.

**Depends on:** none.

## Master Acceptance

- [ ] M-A1: Official Codex starts in the Fugu Linux lane with its executable/config discoverable
  and without a procfs mount.
- [ ] M-A2: Automated and live evidence demonstrate that parent process environments and
  `SAKANA_API_KEY` are not exposed through `/proc`.
- [ ] M-A3: The feature branch contains only the planned fix, tests, and directly affected docs and
  remains unmerged for operator review.

## Non-Negotiables

- Never add `--proc /proc` to the Fugu lane or weaken its kernel isolation.
- Never expose credentials or host process environments to model-directed commands.
- Do not call Fugu to review this plan; use the shortcut only for the requested final smoke after
  the fix and focused tests are ready.
- Do not touch the five `ds-*` worktrees, `/workspace/ds-*-adoption` staging, or other agents.
- Do not merge.

## Test Strategy

- **Primary gate:** focused isolation tests covering bwrap argv and a live synthetic `/proc` view.
- **Secondary gate:** affected provider-shortcut tests plus the repository's full Python test gate
  when practical at terminal readiness.
- **E2E:** official preflight followed by one tiny read-only official Fugu review of a one-file docs
  change, captured to a log.
- **Durable docs:** state that Linux uses no procfs and provides only a synthetic Codex
  self-executable link.
