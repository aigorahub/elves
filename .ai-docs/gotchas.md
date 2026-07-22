# Gotchas

- This repo is documentation-heavy, so regressions usually show up as drift between `SKILL.md`,
  `AGENTS.md`, templates, README, and changelog rather than broken code execution.
- `README.md` repeats concepts from the skill files and often lags unless it is updated as part of
  the same batch.
- A morning checkpoint, return time, or delivery target can look like a natural stopping point, but
  it is not a stop condition unless the survival guide explicitly says it is a hard stop.
- Clean commits, green CI, a good summary, or user silence can also look like permission to stop.
  They are not. Use the `Stop Gate` and `continuation_guard`, not vibes.
- "The remaining work is a lot for one turn" and "this is a natural place to check in" feel like stop
  signals but are exactly the rationalizations the Pre-Final Guard exists to defeat. The volume of
  remaining work is the reason the run exists, not a reason to stop.
- Two agents (e.g. Claude and Codex) in the same working tree on the same branch will overwrite each
  other's files and move the branch out from under each other mid-run. One run owns one branch and
  one checkout; use a dedicated `git worktree` per run when agents share a repo, record the branch
  tip at staging as a collision tripwire, and stop on every move except the narrow trusted case:
  the exact registered full-run session advanced its assigned feature branch to a descendant of the
  last observed tip and the supervisor verified its process fingerprint and protected refs
  unchanged.
- The survival guide can silently rot into an append-only history log if updates get stacked at the
  bottom. Rewrite the live sections in place and keep chronology in the execution log.
- Paid pods, remote jobs, and long-lived local services become invisible quickly unless `Active
  Compute` is updated after every host push and resource change. During trusted parked full-run,
  consume bounded worker events and update host memory at wake/exit instead of on every worker push.
- A parked host that runs the normal per-batch review/memory/PR loop is not parked; it recreates the
  token and latency tax delegation is meant to avoid. Route before the loop, create one host-owned
  `b0` launch ref, then use bounded telemetry until terminal/safety wake. Worker commit SHAs are
  internal rollback points; workers never create refs.
- Isolating HOME also hides Grok's OAuth login. A real full-run must explicitly grant
  `XAI_API_KEY` or use `--grant-grok-auth`, which keeps private per-run Grok state but points
  Grok's native `GROK_AUTH_PATH` at the validated canonical owner-private `auth.json`. Do not copy
  OAuth state: refresh-token rotation can invalidate the host copy and strand the only fresh token.
  Shared OAuth is trusted-Lane-A-only and requires an installed native Grok binary whose auth and
  launch capabilities pass the isolated probes. Require a native Mach-O/ELF artifact, bind its full
  safe ancestor chain in a credential-free environment, reject scripts, and reject permissive ACLs
  on either the executable/auth file or any ancestor;
  stop-artifact authentication is not a hard privilege boundary against that same-user worker.
- `.elves-session.json` is ignored by default in the repo baseline, but live Elves runs may need to
  force-add it so the branch carries structured session state during the run.
- `.elves/landing-profile.json` is the deliberate exception to the ignored `.elves/*` runtime
  tree. Do not broaden that exception: observations, candidates, sessions, and private prewalk
  checkpoints remain untracked. A present invalid profile fails closed; a missing profile is
  neutral. Schema v1 rejects executable/argv shapes; repository consistency and release checks
  stay host-run ordinary verification rather than profile subprocesses.
- Local project installs can quietly shadow global installs. When behavior differs from what the
  user expects, check `scripts/install_doctor.py --doctor` before assuming the upgrade failed.
- PR review automation only becomes useful once the branch is pushed and the PR exists. Opening the
  PR late starves the review loop.
- This repo has no package-managed lint/typecheck/build pipeline. Use
  `python3 scripts/verify_repo.py --version 2.10.0` as the canonical aggregate proof command, plus
  `--final-readiness --session <session-path>` for live landing readiness.
- Provider wording drifts easily. Normal Cobbler and ordinary Elves must not require OpenRouter.
  Math may show `openrouter:<model-id>` as an optional role route, but default config should keep
  `math-required-env: []` unless a project survival guide explicitly opts in.
- `status: complete` in `.elves-session.json` is self-certified unless paired with per-batch
  `acceptance: [{id: "B#-A#", criterion, met, evidence}]`. New plans use stable `B#`, `B#-A#`,
  and branch-level `M-A#` ids. `B0` and `B1` are equally valid starts; do not reserve or prefer
  either. Bare `- [ ] B0-A1: criterion` and bracketed `- [ ] [B0-A1] criterion` rows are equivalent.
  Legacy rows receive deterministic document-order aliases. Green CI
  plus complete flags is not landable; plan
  Acceptance with proof is. Less-disciplined models especially tend to close god-file / split
  batches on structure or regex lock tests alone.
- Acceptance drift should fail in staging, not after an unattended worker finishes. Parse the
  authoritative plan before launch, emit a targeted replacement for malformed stable-id rows, and
  require the session and packet id-to-criterion mappings—and the plan/session batch sets—to match
  it. Missing, extra, duplicate, or text-mismatched rows or batches are launch blockers. Explicit
  empty legacy or stable Acceptance sections also fail early. Use installed
  `acceptance_contract.py validate`; its `sync-session --write` action is explicit and refuses to
  erase or rewrite evidenced rows.
- Multi-batch "close remaining" commits can make unfinished work look shippable. Prefer one batch
  per close commit; otherwise require separate Validate sections per batch id and run
  `scripts/elves_landing_check.py` before Final Readiness.
- Vague commit subjects (`Updates`, `progress`, `WIP`, bare `fixes`) hide operator progress in
  GitHub/GitKraken. Prefer phase-aware subjects and push mid-batch slices, not one opaque dump.
- Incomplete coordinator-to-implementer packets are coordinator defects. Do not expect a context-poor
  worker to reconstruct intent, Build On targets, or forbidden surfaces from chat memory.
- `.elves/models.toml` is local and ignored. Staging it or treating personal model IDs as public
  defaults reintroduces provider lock-in. Use `references/models.toml.example` as the reviewable
  schema and snapshot effective routes in the Survival Guide.
- Python 3.11+ supplies stdlib `tomllib`; Elves' bundled `cobbler_runtime.toml_compat` parser keeps
  the supported local-models subset working on Python 3.10. Unsupported TOML syntax still fails
  closed instead of being silently ignored.
- `python3 scripts/cobbler_agents.py validate-config --json` and `doctor --json` never launch paid
  model turns and must not mutate the repo.
- Council lanes must launch in parallel. Sequential fan-out is not independence and fails the
  wall-clock overlap tests in `tests/test_cobbler_agents_dispatch.py`.
- Exit code 0 is not inference success. Structured role-report JSON must validate; actual-model
  mismatches fail the lane when a requested model was set.
- Strip secret env **names** from child processes and never log secret values. Allowlisting a
  secret-looking name must not reintroduce it.
- `lightweight-review` is a utility lane, not a council vote. It cannot close high-risk review or
  satisfy independent review quorum by itself.
- `target_quorum` degrades with a confidence drop; `required_quorum` only applies when the phase is
  explicitly `required=true` and blocks when unmet after fallback.
- Never use bare `--resume`, `--continue`, or `--last` for session selection. Exact session IDs only.
  Canonical disk state (plan/Survival Guide/session registry) outranks chat memory.
- A driver session ID is not a transferable cache handle. Preserve the exact worker session when
  resuming, but never promise that a separate native/Grok worker inherits the driver's prompt/KV
  cache or hidden state.
- Prewalk is stricter than exact resume in isolation: it requires one worker session and worktree
  across guide and execution routes, one packet send, a bounded TODO, a validated real task edit,
  and minimal continuation. A new worker with a summary or copied packet is a cold handoff, never
  prewalk. Help text proves only advertised grammar; do not enable `auto`, claim instruction
  pruning, or accept post-edit cold fallback without exact-version behavioral evidence. Preserve
  the dirty worktree and stable `prewalk_*` diagnostic on failure.
- `scripts/consistency_policy.py` phrase-pins many normative sentences in `SKILL.md`, `README.md`,
  `AGENTS.md`, `CHANGELOG.md`, and `references/*`. Editing a pinned sentence without updating its
  pin (or adding a pinned phrase the doc does not contain) fails
  `check_repo_consistency.py`. Work doc-first: edit the doc, run the checker, fix pins, repeat —
  after every touched file, not once at the end — and keep the pin change in the same commit as
  the sentence it pins.
- Do not confuse explicit handoff v1 with prewalk. Declaring session `handoff` makes cold-handoff
  state, ownership, branch/HEAD, and the matching bounded packet capsule strict; omitting it keeps
  the v2.8 advisory packet-path behavior. Neither Markdown nor JSON capsule proves same-session
  guide→execution continuity.
- Grok parent→worktree child lineage uses a **new** child UUID. Headless `--worktree --resume` on
  Grok Build 0.2.93 is broken (retains source CWD); fail closed without verified CWD/worktree
  registration, then resume the discovered child exactly from that worktree.
- Grok Build 0.2.101 treats explicit `--permission-mode auto` as higher precedence than
  `--always-approve`; do not emit both for a trusted implement run. The conflict can terminate the
  first permission round-trip as `Cancelled` while the process still exits zero, so monitor the
  bounded terminal stream category as well as the exit record.
- `remaining_quota` is `unknown` unless a harness explicitly sets `quota_known`. Never invent limits
  from token counts, and never treat unknown as zero.
- Unexpected model/CWD/parent/worktree drift blocks write reuse; expected HEAD/plan digest change
  yields rehydration, not silent continuation on stale assumptions.
- Only one external writer lease may be live. Dirty, branch-attached (when detached required), HEAD
  mismatch, or unregistered worktrees fail closed at prepare.
- Never bare-cherry-pick worker commits. Export binary patches, `git apply --check --index` on the
  host, then create sanitized host commits that record source worker SHAs.
- Grok write profile forbids headless `--worktree --resume` as isolation (especially 0.2.93). Resume
  the exact child from a registered detached worktree CWD under a `devbox` (or equivalent) sandbox.
- A `workspace` sandbox linked worktree must not be assumed commit-capable; leases force
  `detached_commits_permitted=false` for that profile.
- Ref/remote/config/hook mutations, out-of-scope paths (including `.elves/` and run docs), symlink
  escapes, push attempts, and process leaks fail the post-turn audit even when the file diff looks right.
- Setup is optional. Never stage `.elves/models.toml` or paste API keys into TOML/chat/Survival Guide.
  Codex has no top-level `/setup-cobbler` slash — use `$elves setup-cobbler` or natural language.
  OpenRouter/API-only routes are optional read-only breadth unless a wrapper qualifies write/isolation.
- Process groups, pidfds, ancestry polling, and inherited markers are not recursive containment: a
  double-forked `setsid` child can escape between scans. A pidfd opened only after asyncio returns
  the child is also too late to prove atomic generation binding. Hard external council routes
  therefore fail before snapshot creation or spawn on Linux and Darwin; optional routes fall back
  native and required routes block. Legacy bounded `--exec` has no qualified boundary on either
  supported OS and fails before spawn. Trusted full-run remains a separate same-user policy lane
  and must not be described as malicious-worker recursive containment.


## v2.1.0 full-run note

Trusted Grok full-run uses one session, feature-branch progress, parked-monitor driver, and bounded events. Untrusted detached leases remain a distinct authority model.

## Subprocess stdin inheritance can freeze gates for hours (2026-07-16)

A helper that reads stdin to EOF when stdin is not a TTY (`openrouter_lens.py` pre-fix) combined
with a test that spawns it without pinning `stdin=` will block forever under any runner that
leaves an inheriting pipe open — while passing under runners whose stdin happens to be closed.
The fix class, in order of strength: (1) helpers do fail-closed checks (missing key) BEFORE any
stdin read and skip stdin when the task arrives via flags; (2) `tests/__init__.py` dup2s fd 0 to
devnull so every suite child inherits closed stdin; (3) the gate runner (`verify_repo._run`) and
the canonical `leases.run_git` close stdin and carry timeouts unconditionally. Diagnosis tell:
near-zero CPU time vs hours of wall time.
