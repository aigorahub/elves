# Plan: Automatic prewalk qualification

## Mission

Make exact-session prewalk usable on supported hosts without requiring operators to hand-create
qualification artifacts. A required prewalk launch runs a bounded live canary when matching cached
evidence is absent, proceeds only on complete continuity proof, and otherwise stops with a private
evidence artifact. An explicit experimental mode may proceed from advertised transport grammar
while retaining every runtime identity, worktree, packet-count, and transition check.

## Scope

### In scope

- Automatic version-and-route-bound qualification for required prewalk launches.
- A private qualification cache that lets later auto launches reuse successful proof.
- An explicit experimental prewalk request with honest state and diagnostics.
- Claude Code, Codex, and Grok Build host parity where their installed transport advertises the
  required exact-resume and route-override grammar.
- Runtime tests, repository consistency, user guide, reference docs, changelog, and release version.

### Out of scope

- Relaxing exact session identity, registered worktree binding, one-packet delivery, meaningful-edit
  validation, post-edit cold-fallback prohibition, Git authority, or landing authority.
- Making auto mode spend on a live canary without an explicit required request.
- Changing model catalogs, worker merge authority, or provider credentials.

## Batch 1 [B1]: Qualification runtime and host parity

**Coordinator-to-implementer handoff:**

- **Intent / why:** replace manual prewalk qualification with an automatic bounded launch-time gate.
- **Non-obvious rationale:** qualification uncertainty belongs before task launch, while trajectory
  identity remains enforced again during the real worker lifecycle.
- **Build On targets:** `prewalk.py`, `native_worker.py`, `host_profiles.py`, worker routing,
  preferences, and existing descriptor-safe artifact loaders.
- **Owned surfaces:** prewalk runtime, CLI, focused tests, contract docs, guide, changelog, versions.
- **Forbidden surfaces:** provider secrets, protected refs, merge bypass, unrelated workers.
- **Acceptance evidence:** focused lifecycle/routing tests, host-parity tests, full repository gate,
  Fugu review, clean PR checks, and verified installed bundles.
- **Failure modes / pitfalls:** packet replay, accepting help as proof under required mode, canary
  hangs, unbounded output, stale route evidence, false Grok launch readiness, or hidden fallback.
- **HEAD / run-doc paths / route-session identity / output format:** start
  `6030755790fa50b3d7de1cea4f03bf4751c25db6`; this plan is authoritative; host-native implementation
  on `codex/prewalk-auto-qualification`; final output is a landed merge commit and verified global
  installs.

**Acceptance criteria:**

- [x] B1-A1: Required mode automatically runs a hard-time-bounded live canary only when matching
  successful evidence is absent, and persists a private evidence artifact on success or failure.
- [x] B1-A2: A successful canary proves exact session continuity, route change, the same worktree,
  one logical stream, retained guide context, and one packet before real prewalk starts.
- [x] B1-A3: Failed or incomplete qualification stops required launch with the evidence path and no
  task worker launch.
- [x] B1-A4: Experimental mode is explicit and honestly reported, requires advertised exact resume
  and route override, and preserves all runtime trajectory and authority checks.
- [x] B1-A5: Codex, Claude Code, and Grok Build use the same qualification and runtime invariants,
  with host-specific invocation syntax covered by tests.
- [x] B1-A6: Docs, guide, changelog, and version metadata describe the shipped behavior consistently.

**Risk:** high. This changes the gate in front of a multi-process exact-session lifecycle.

**Affected surfaces:** prewalk runtime, native worker CLI and supervisor, worker routing, preferences,
host parity, tests, docs, guide, changelog, release metadata, installed bundles.

**Review focus:** canary bounds and evidence truth, exact-session identity, prompt-file transport,
Grok host behavior, experimental-mode honesty, and no authority expansion.

## Master acceptance

- [x] M-A1: A user can request required prewalk without manually preparing qualification evidence.
- [x] M-A2: Qualification failure stops before task launch and names durable private evidence.
- [x] M-A3: Experimental mode changes only the qualification threshold, not trajectory or authority
  enforcement.
- [x] M-A4: Claude Code, Codex, and Grok Build have equivalent user-visible semantics.
- [x] M-A5: The exact release tip passes full verification and Fugu review, has green PR checks, and
  is ready for landing and global installation.
