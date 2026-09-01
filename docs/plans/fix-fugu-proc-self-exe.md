# Plan: Restore Fugu Codex startup without procfs

## Mission

Allow the official `codex-fugu` launcher and Codex 0.149.1 to start inside the existing Linux
Fugu bwrap lane while preserving the lane's credential boundary. The lane must expose only the
self-executable identity Codex requires; it must not mount procfs or make process environments
available to model-directed commands.

This landing replays the unmerged `origin/fix/fugu-proc-self-exe` work onto current `main`
after v2.34.0. It keeps Cyber routing language, updates every host restatement, and leaves the
version bump for a follow-up after merge.

## Scope

### In scope

- The shared bwrap argv builder and the official Fugu shortcut's use of it.
- Fugu isolation tests for executable identity and proc-based environment isolation.
- Durable Fugu isolation documentation on every host restatement (SKILL, AGENTS, guide, README,
  provider-shortcuts, Claude `/fugu` alias).
- Grok and Oh My Pi Linux no-procfs wording stays accurate: those lanes omit procfs and do not
  receive a Codex `/proc/self/exe` view.

### Out of scope

- Full procfs or any relaxation of the outer kernel boundary.
- Raw/direct Fugu or Codex provider workarounds outside `run_fugu.sh`.
- Changes to global Codex/Fugu installation, credentials, or `~/.codex`.
- Version bump (operator request: review, merge, then bump).

## Batch 1 [B1]: Synthetic Codex self-executable view

- **Intent / why:** Restore official Codex startup without exposing the credential-bearing process
  tree through procfs.
- **Non-obvious rationale:** Codex 0.149.1 requires `readlink("/proc/self/exe")`; a regular bind at
  that pathname returns `EINVAL`, so the isolated view must resolve to the qualified, narrowly
  mounted real Codex executable while remaining an ordinary synthetic directory tree. Auto-apply
  from trusted `CODEX_FUGU_REAL_CODEX` because Fugu launches `codex-fugu`, not the real Codex.
- **Build On targets:** `wrap_argv_with_sandbox`, existing narrow executable-runtime mounts, and
  Fugu's existing `mount_proc=False` route.
- **Owned surfaces:** `scripts/cobbler_runtime/isolation.py`, Fugu isolation tests, and directly
  affected Fugu/Grok/OMP documentation restatements.
- **Forbidden surfaces:** credentials, global installs, unrelated worktrees, other branches/agents,
  procfs mounts, weakened tests, raw provider calls, protected refs, and a version bump in this PR.
- **Acceptance evidence:** focused unit/live bwrap tests, relevant regression tests, argv inspection,
  and host-doc restatements that keep Cyber and four-host invocation intact.
- **Failure modes / pitfalls:** confusing a regular bind with the symlink semantics required by
  `current_exe`, admitting an unqualified executable, accidentally combining the synthetic view
  with `--proc`, inventing a Grok/OMP Codex self-exe, or proving only preflight rather than
  construction.

**Acceptance criteria:**

- [x] B1-A1: A no-proc bwrap lane exposes `/proc/self/exe` as a symlink resolving to the exact
  qualified Codex executable, and construction fails closed for an invalid target or a request
  that also mounts procfs.
- [x] B1-A2: The resulting bwrap argv contains no `--proc /proc`, and live sandbox proof shows
  `/proc/<pid>/environ` is unavailable, including for the credential-bearing parent namespace.
- [x] B1-A3: Grok/OMP-style `mount_proc=False` without `CODEX_FUGU_REAL_CODEX` still omits `/proc`
  entirely.
- [x] B1-A4: Focused Fugu/isolation tests and the repository's relevant regression gate pass without
  weakening existing coverage.
- [x] B1-A5: Claude SKILL, Codex AGENTS, the public guide, README, provider-shortcuts, and the
  Claude `/fugu` alias all state the same Fugu Linux boundary, including Cyber.

## Master Acceptance

- [x] M-A1: Official Codex can start in the Fugu Linux lane with its executable/config discoverable
  and without a procfs mount.
- [x] M-A2: Automated evidence demonstrates that parent process environments and `SAKANA_API_KEY`
  are not exposed through `/proc`.
- [x] M-A3: Host restatements stay aligned. Version remains 2.34.0 until the post-merge bump.

## Non-Negotiables

- Never add `--proc /proc` to the Fugu lane or weaken its kernel isolation.
- Never expose credentials or host process environments to model-directed commands.
- Do not invent a synthetic Codex `/proc/self/exe` for Grok or Oh My Pi.
- Do not bump the skill version in this PR.

## Test Strategy

- **Primary gate:** focused isolation tests covering bwrap argv and a live synthetic `/proc` view
  when `/usr/bin/bwrap` exists.
- **Secondary gate:** affected provider-shortcut tests plus `scripts/verify_repo.py --ci`.
- **Durable docs:** Linux Fugu uses no procfs and provides only a synthetic Codex self-executable
  link. Grok Linux still omits procfs with no `/proc` view.
