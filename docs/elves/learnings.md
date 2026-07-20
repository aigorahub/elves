# Project Learnings

> This file is durable memory across Elves runs. Read it after the survival guide and
> `.elves-session.json`, before the plan and execution log. Keep only stable, reusable, actionable
> lessons here.

---

## Promotion Rules

Promote something into this file only if it is:

- **Reusable:** likely to help a later batch or a future run
- **Stable:** not expected to change again in the next hour
- **Actionable:** changes what the agent should do, avoid, or verify
- **Specific:** concrete enough that another session can apply it without guessing

When a learning becomes outdated, move it to `## Retired Learnings` with a short note instead of
silently deleting it.

## Repo Conventions

- [2026-07-17] Tighten staging contracts through explicit versioned opt-in, not surprise migration.
  Existing delegable sessions keep advisory missing-packet compatibility; declaring top-level
  `handoff` activates strict handoff v1 across session state, pending-acceptance ownership, exact
  branch/HEAD, ancestor slice commits, and bounded Markdown/JSON packet capsules. This is cold-
  handoff evidence only; exact-session prewalk has a separate continuity proof.

- [2026-07-13] Execution authority is route-specific. The host always owns canonical run memory,
  protected refs, PR actions, final gates, cumulative independent review, and merge. Host-native and
  legacy bounded routes keep commits/pushes and the per-batch loop in the host. The primary trusted
  full-run route lets the exact registered `branch_progress` worker commit/push only its assigned
  feature branch while the host parks. Untrusted writer leases remain detached and host-imported.
  Every worker packet still carries intent, rationale, Build On targets, owned/forbidden surfaces,
  acceptance evidence, failure modes, and exact route/session/output identity.
- [2026-07-13] Git history is an operator-facing progress surface on both writable routes. The host
  pushes meaningful phase slices for host-native/legacy work; a trusted `branch_progress` full-run
  worker does so on its assigned feature branch. Avoid vague dumps and noisy micro-commits, and
  reserve `Close` for acceptance-backed completion. Protected refs and PR/merge operations stay
  host-only; untrusted workers produce audited detached handoffs only.
- [2026-07-08; updated 2026-07-13] Batch `status: complete` must carry plan Acceptance proof in
  session JSON (`acceptance: [{id: "B#-A#", criterion, met, evidence}]`). New plans use stable
  batch `B#`, batch-acceptance `B#-A#`, and branch-level `M-A#` ids; legacy plans receive
  deterministic aliases by document order and those aliases never change. Green CI alone is not
  landable. Structure/regex
  characterization tests may lock god-file splits but must not alone complete them unless the plan
  explicitly allows characterization-only. Prefer one batch per close commit; use
  `scripts/elves_landing_check.py` before Final Readiness.
- [2026-04-11] This repo has two canonical skill surfaces: `SKILL.md` for Claude-compatible agents
  and `AGENTS.md` for Codex. Any behavior change to Elves must update both in the same release.
- [2026-04-11] Elves works best when staging and launch are treated as separate phases even if the
  user asks for a full unattended run in one session; the plan and run-memory docs should be stable
  before implementation batches begin.
- [2026-04-14] Run control is live metadata, not a planning-time note. If the user changes stop
  behavior, checkpoint meaning, or whether work may continue after a deadline, rewrite `## Run
  Control` immediately and log the change in the execution log.
- [2026-04-14] The survival guide is a live operator brief, not a history log. Rewrite `Run
  Control`, `Current Phase`, `Active Compute`, and `Next Exact Batch` in place; leave chronology to
  the execution log.
- [2026-04-14] Stopping should require positive permission, not inference. The survival guide
  should carry a `Stop Gate`, and `.elves-session.json` should carry a `continuation_guard`, so a
  recovered context can tell whether it must keep going without rereading the whole run.
- [2026-05-09] Substantial finite runs should end with a temporary human-facing Elves Report when
  stopping is allowed. The report is a worker-to-manager morning briefing sourced from the survival
  guide, execution log, learnings, plan, session JSON, and live PR/CI state. It should foreground
  problems found, lessons learned, verification proof, residual risks, human next steps, and
  collapsible batch summaries instead of forcing the user to reconstruct the run from raw logs.

## Validation and Tooling

- [2026-07-12] Grok Build ~0.2.93: for read-only/media-style CLI calls prefer default tools +
  `--disallowed-tools` denylist; `--tools` allowlists can fail session create. Lane A implement
  still uses default tools + `--yolo`. Model aliases `fast`/`deep` and optional `--check` are
  supported on `implement prepare|launch`. Battle-scar credit: stdevMac/grok-in-claude and
  grok-in-codex (Apache-2.0); backlog in `references/community-grok-plugin-ideas.md`.
- [2026-07-17] Grok Build 0.2.101 gives explicit `--permission-mode` precedence over
  `--always-approve`. Never combine `--permission-mode auto` with yolo for a trusted headless
  implement launch: it disables the intended unattended mode and can return terminal `Cancelled`
  with process exit zero. Classify the structural terminal record, not the OS exit alone.
- [2026-07-12] Never update an accepted session context digest before rehydration proof. Store
  pending digests/heads on expected canonical drift and promote only after an exact resume matches
  the pending packet; otherwise a later resume silently erases the rehydration obligation.
- [2026-07-12] Do not normalize repo-relative paths with `str.lstrip("./")`. That API strips a set of
  characters, turning `.elves/...` into `elves/...` and breaking forbidden-prefix checks. Strip only
  explicit `./` segments.
- [2026-07-12] Setup `smoked=true` requires a real model response from an explicit smoke executor.
  Opt-in acknowledgment alone is not qualification.


- [2026-07-12] External-harness capabilities must be qualified behaviorally and versioned. CLI
  flags, installed executables, authentication state, actual model identity, persistent-session
  behavior, and safe-write behavior are separate facts; do not infer one from another.
- [2026-07-12] Subscription harnesses may expose observed token/cost usage without exposing
  remaining quota. Preserve `remaining_quota: unknown`; never invent a limit or treat unknown as
  zero.
- [2026-04-11] `./scripts/preflight.sh` is the repo's best built-in environment check. It is useful
  for git/auth/setup validation even though this repo has no package-managed build/test pipeline.
- [2026-04-14] If a run uses paid compute, remote jobs, or long-lived local servers, track them in
  the survival guide's `Active Compute` section. Host-native/legacy runs reconcile after host pushes
  or topology changes; a parked trusted full-run consumes bounded telemetry and reconciles canonical
  memory once at terminal/safety wake rather than after every worker push.

## Review Heuristics

- [2026-04-11] For this repo, the most common regression risk is documentation drift across
  `SKILL.md`, `AGENTS.md`, templates, and README. Review should verify conceptual alignment, not
  just prose quality.
- [2026-04-11] Treat stale docs as `PENDING-DOCS`, not as a vague warning. If recovery docs,
  durable docs, or human docs lag behind a behavior change, the batch is not clean yet.

## Product and Domain Invariants

- [2026-07-17] Native-worker prewalk is a trajectory property, never a packet-format improvement.
  One worker receives the packet once, creates a bounded TODO, makes a model-free-validated task
  edit, and resumes the exact session/worktree on the execution route with only `Continue.`. Static
  help proves advertised grammar only; exact-version behavioral evidence must prove continuity,
  route change, no packet replay, stream binding, and honest instruction fidelity before `auto`
  activates. The current persisted-instruction delivery activates only proven `retained_safe`;
  `pruned` and `turn_scoped` are future transport states. Post-edit cold fallback is forbidden, and
  driver authority is unchanged. Normative contract: `references/prewalk.md`.

- [2026-07-15] Adaptive implementation routing is deterministic and host-parity preserving: prefer
  a separate subscription-native Codex/Claude worker with inherited model policy and plan-matched
  effort. When Grok is permitted, use the authenticated live catalog's parsed default unless the
  operator explicitly selects another exact catalog member. Availability is not permission, and
  unqualified routes fall back honestly.
- [2026-07-15] Safe worker convenience may be remembered globally at the shared XDG Elves config
  path, but explicit run intent and repository policy outrank it. Never persist credentials or
  merge/destructive/protected-ref/approval-bypass authority. Exact-session continuity may benefit
  from provider caching, but Elves cannot hand a prompt/KV cache from driver to worker.

- [2026-07-12] Native-only Cobbler remains the zero-config default. External Claude/Grok/Sakana,
  OpenRouter, API-only models, and future custom tools are optional role routes; only an explicit
  project Survival Guide may make one required.
- [2026-07-13] External implementation has two distinct authority models. Primary trusted full-run
  uses one exact registered `branch_progress` session on the assigned feature branch while the host
  parks; it never owns protected refs, PR actions, run memory, final review, or merge. The advanced
  untrusted writer path uses one detached lease, full chain/ref/remote/config/hook/path audit, and
  host-only binary-patch import. Either implementer is excluded from independent review quorum.
- [2026-07-12] **Default implementer is the host** (Claude Code or Codex). Grok Build, multi-provider
  plan/review, and the host-import writer lease are optional upgrades when those tools exist — same
  pattern as the math module. Do not imply overnight Elves requires Grok or “Lane A.”
- [2026-07-12] Optional plan/review routes follow the geometry-exploration multi-model panel
  pattern: OpenRouter via `OPENROUTER_API_KEY` + wrapper + named `or-…` presets (any
  `provider/model-id`); Meta Muse Spark 1.1 via `META_API_KEY`/`MODEL_API_KEY` + wrapper, model id
  **`muse-spark-1.1`**, preset e.g. `meta-muse-spark11`. Independent read-only lanes only; pin the
  Meta catalog id (not assumed aliases); native fallback when key/wrapper missing; never sole
  authority. Recipes: `references/cobbler-setup-recipes.md`, `references/council-provider-config.md`.
- [2026-07-12] Google Cloud AlphaEvolve is an optional math-module evolutionary-search lane for
  numerical examples / counterexample signals: managed mutation + local deterministic evaluator,
  gcloud impersonation (no SA keys), independent replay before promotion. Role
  `evolutionary_search`. Not a proof engine. Guide: `references/math-alphaevolve.md`.
- [2026-07-12] Model onboarding is host-mediated on both Claude Code and Codex: `onboard
  plan → interview → apply → probe`. Preferences in ignored `.elves/models.toml`; structural probe
  by default; live smoke opt-in; never print secrets. Protocol: `references/model-onboarding.md`.
- [2026-07-12] Prefer high-quality Claude/Codex for plan+review and a labor model for implement
  (`*-planning` / `*-labor` profiles + local `requested_model`). Google Gemini CLI / Antigravity
  CLI are optional plan/review lenses, usually not cost-effective for the main implement batch.
- [2026-07-12] **Supported Elves main drivers are Claude Code and Codex only.** Optional routes
  (Antigravity, Gemini CLI, Muse, OpenRouter, Grok, AlphaEvolve) may work as tools the host calls;
  that is not our focus. Exotic interfaces are not heavily tested (e.g. no Antigravity subscription
  for maintainer dogfood). Prefer contributor PRs (or issues) when optional paths fail.
- [2026-07-13] When the user has Grok Build and explicitly requests trusted full-run delegation,
  prefer one complete packet, one exact persistent session, `branch_progress`, and a parked host via
  `full-run-prepare|full-run-launch|full-run-await|full-run-reconcile|full-run-logs`.
  `full-run-stop` is cancellation or recovery only. Keep
  `prepare|launch|gate|resume-batch|status` as the legacy bounded route and use `untrusted`
  host-import leases only when the hard writer boundary is required.
- [2026-07-15] For open-source Grok Build, the installed executable is launch authority and
  upstream source is semantic reference. Build 0.2.101 proves caller-assigned `--session-id`, exact
  resume, `/goal status` command resolution with the narrow auth projection and no model inference,
  streaming JSON, JSON schema, ACP, and the existing autonomous/read-only flags; it rejects
  `--new-session`. Its exact authenticated packet-backed `/goal` canary did not reach terminal state,
  so goal behavior remains unproven and the one-packet prompt fallback is required. Qualify
  provider/auth/live catalog independently from goal behavior, select only catalog-returned models
  using the parsed default unless another exact catalog member is explicitly selected, preserve
  private `HOME`/`GROK_HOME` plus the narrow `GROK_AUTH_PATH`, and never persist raw OAuth or provider
  output. Future goal enablement requires a bounded, mode-safe terminal-canary JSON artifact tied to
  the exact installed build, canonical session, prompt digest, successful exit, and matching end
  event; persisted state keeps only its digest ID.
- [2026-07-13] An isolated headless Grok process cannot inherit an interactive subscription login
  accidentally. Require exactly one explicit strategy before spawn: grant `XAI_API_KEY` by name, or
  for trusted Lane A keep the run's private `GROK_HOME` while exposing only the validated canonical
  owner-private `auth.json` through native `GROK_AUTH_PATH`. Never copy OAuth state: Grok may rotate
  the refresh token, invalidating the host copy and deleting the only fresh authority on cleanup.
  Shared OAuth remains credential minimization for a trusted same-user lane, not a privilege
  boundary; disable raw tails because historical token values may rotate. Probe and bind an exact
  native Mach-O/ELF executable plus every safe ancestor without host credentials, and validate every
  open auth-path ancestor including native
  ACLs; mode bits alone do not prove owner-private access on macOS.
- [2026-07-13] Do not claim hard recursive subprocess cleanup from process groups, pidfds, ancestry
  polling, or environment markers. A child can double-fork, call `setsid`, scrub its environment,
  and escape between scans. A pidfd opened only after an asyncio child is returned is not an atomic
  generation binding either. Until a boundary is acquired atomically with spawn, hard external
  council lanes fail before snapshot creation or spawn on Linux and Darwin; optional routes fall
  back native and required routes block. Legacy bounded
  `--exec` has no qualified boundary on either supported OS and must fail before spawn. Keep the
  trusted same-user full-run lane separate and describe its cleanup boundary honestly.
- [2026-04-11] Elves is intentionally lightweight. Borrow architectural ideas from richer systems,
  but avoid pulling in hydration, skeleton generation, or opaque automation unless the repo
  genuinely needs them.
- [2026-07-13] The user owns whether Elves may merge. Default is user-merges; only explicit
  merge-on-green Run Control or the reviewed-PR landing command authorizes Elves to land, and then
  only by regular merge commit after final readiness.

## Known Traps

- [2026-07-15] A subscription-native Codex or Claude worker can edit a linked worktree while its
  sandbox still denies the shared parent Git directory and `index.lock`. Staging must prove commit
  capability before launch or use a qualified checkout layout whose feature-branch Git metadata is
  writable without granting protected-ref authority. A private JSONL follow log also isn't a
  readable operator view when the host hides tool output. Keep the exact follow command, and explore
  a temporary local HTML view as a later usability improvement rather than waking the driver for
  routine narration.

- [2026-07-15] Codex `exec resume` has no resume-local `-C`, `--sandbox`, or `--add-dir` flags.
  Current Codex accepts the exec-level sandbox and additional-write-root options before the
  `resume` subcommand; bind the exact worktree through the supervisor OS CWD and keep those options
  before `resume`. Do not preserve the older `-c sandbox_mode="workspace-write"` workaround because
  it omits the narrow linked-worktree Git roots. Structured JSONL inside a hidden host tool call is
  not a user-visible worker stream; bind and surface a proven native agent view or exact private
  follow command before parking.

- [2026-07-12] Grok Build headless turns can exit before detached commits despite incomplete work.
  Prefer absolute `--prompt-file` paths (worker CWD is not the host runtime dir). If the process
  exits with dirty porcelain twice, host-seal audited worker tree commits with explicit recovery
  notes rather than thrashing the same lease indefinitely.
- [2026-07-12] Independent review quorum can tolerate optional lane rate limits when host + another
  independent non-implementer lane still meet required_quorum. Never use the exact implementer
  successor as its own independent reviewer.
- [2026-07-12] Accidental `#` H1 lines inside README sections break `extract_markdown_section`
  phrase pins for Cobbler; demote accidental headings before closing docs batches.


- [2026-07-12] Grok Build 0.2.93 headless `--worktree --resume` can silently retain the source
  checkout. Interactive worktree resume creates a discoverable child session with the full parent
  transcript. Verify actual CWD, registered detached worktree, parent/child identity, and HEAD; never
  treat the flag itself or an unchanged requested session ID as isolation proof.
- [2026-07-12] A Grok sandbox profile is fixed at session startup and cannot be changed by resume or
  fork. In a linked worktree, `workspace` may allow source edits while denying the shared Git
  `index.lock` outside the CWD; edit capability therefore does not imply commit capability. Start a
  separately qualified commit-capable session before implementation, seed it from canonical run
  memory, constrain Git to detached commits, and audit all shared-repo state afterward.
- [2026-07-12] Narrow Grok `--tools` allowlists can remove terminal background-support tools and
  make agent construction fail. Treat a harness toolset as a behaviorally qualified bundle rather
  than composing individual advertised capabilities ad hoc.
- [2026-07-12] Grok's CLI `dontAsk` behavior is documented as incompletely wired, and child-process
  network restrictions are a no-op on macOS. Prompt rules and mode names are not hard boundaries;
  combine explicit policy, hard hooks/custom sandbox where available, credential/environment
  isolation, and mechanical post-turn audit.
- [2026-07-12] Fugu may inherit unrelated Codex MCP servers. An optional MCP OAuth `invalid_grant`
  warning is not evidence that Sakana inference failed; report model health and MCP health
  separately.
- [2026-04-11] Repo-level changes can look complete after updating one skill file, but `SKILL.md`,
  `AGENTS.md`, templates, README, and CHANGELOG often drift unless they are reviewed as a set.
- [2026-04-11] If `.elves-session.json` is intentionally committed during a live Elves run, do not
  also ignore it in `.gitignore`; reviewers will correctly read that as contradictory workflow
  guidance.
- [2026-04-14] A checkpoint, return time, or delivery target is not automatically a stop
  condition. If the survival guide does not explicitly call it a hard stop, the agent should treat
  it as a relaunch point and keep going.
- [2026-04-14] Clean commits, green CI, summaries, and user silence are all false stop signals.
  If work remains and the Stop Gate says `no`, the agent should update docs, push, and continue.

## Retired Learnings

- [Retired 2026-07-13] “The host owns all git/push and external implementation is always detached.”
  Superseded by the route split: exact registered trusted `branch_progress` full-run workers may
  advance only their assigned feature branch; untrusted leases remain detached.
- [Retired 2026-07-13] “Preferred Grok work is one bounded batch through
  `prepare|launch|gate|resume-batch|status`.” Superseded by the primary one-session full-run route;
  bounded lifecycle remains legacy/alternative.
- [Retired 2026-07-13] “The user always merges.” Superseded by explicit user-owned merge policy:
  default user-merges, with merge-on-green and reviewed-PR landing as narrow opt-ins.

## Worker commit cadence is a contract, not a preference (2026-07-16, hygiene-and-hardening B1)

A native worker session given only "push meaningful slices" and a Definition of Done will batch
everything and commit once at the end — the branch stays at the staging tip while work accumulates
uncommitted, which blinds the parked driver and forfeits crash recovery (pushed progress is the
recovery mechanism). Make cadence explicit in every packet: at least one pushed non-Close progress
slice before Close, first slice as soon as a failing test or first surface change exists; treat a
monolithic Close commit as a reconcile-visible defect. A mid-run driver nudge works (B1 pushed its
Implement slice immediately after instruction), but the packet should carry the rule from launch.

## Bounded-by-construction beats per-site discipline (2026-07-16, hygiene-and-hardening B9)

233 test call sites spawned subprocesses without pinning stdin; auditing them one by one is the
wrong altitude. Two chokepoints gave a total guarantee instead: an fd-level devnull redirect in
`tests/__init__.py` (children inherit closed stdin no matter the runner) and stdin+timeout
hardening in the single gate runner and the canonical git helper. When a failure class comes from
a default (inherited stdin), fix the default, not the instances.

## Local environment floor and worker transport (2026-07-18, audit-follow-ups staging)

- This machine runs system Python 3.9.6 only; the repo's implicit floor is 3.10
  (`Path.parents` slicing in `sync_installed_skills.py`). Until the B1 floor guard lands, the
  local suite shows 18 pre-existing errors confined to the sync/bundle test modules; CI
  (3.10/3.12/3.14) is the authoritative broad gate. Do not "fix" this by weakening tests.
- The standalone `claude` CLI binary is not installed here, so the supervised `native-worker`
  CLI transport (and exact-session prewalk for a live worker) is unavailable on this machine.
  Honest fallback: in-session native subagent workers with an explicit model/effort pin, driver
  owns git. Record requested vs actual route in `.elves-session.json`.

## Verified Grok Build grammar for the prewalk port (2026-07-18, audit PR #82)

From grok-build 0.2.102 source (commit 98c3b24), adversarially verified: `--session-id <uuid>`
is create-only; `--resume <id>` is strict exact resume; model/effort override IS applied on
resume before the prompt; `--cwd` pins cwd; headless streaming JSON has no tool-call events and
emits `sessionId` only on the terminal `end` event; non-yolo `--permission-mode auto` fails
closed on unapproved tools; sandbox profile is resume-sticky; `todo_write`'s `plan.json`
persistence is vestigial (the private JSON mirror must be the durable prewalk artifact). Source
of truth: `docs/reviews/2026-07-repo-audit-grok-prewalk.md`.

## Native Claude worker launch semantics (2026-07-19, issue-86 run)

Verified live on the v2.10.2 run (claude CLI 2.1.207, native-worker supervisor v2):

- The launcher's `--session-id` flag means **exact-session resume** (it builds `claude --resume
  <uuid>`), not create-with-id; passing it on a fresh launch dies pre-model with "No conversation
  found". Omit it and the supervisor mints the create-mode UUID itself (argv then carries
  `--session-id <minted>` on the claude side).
- The native lane runs workers with **network push disabled** (`git_network_push: disabled`,
  scoped git write roots, nulled gh config): worker commits stay local and the host pushes at
  reconcile. Worker packets must say local-commits-only; a push instruction sends the worker into
  guaranteed failures.
- The exit authority verifier compares protected refs against the **launch-time snapshot**: any
  host-minted ref created after launch (e.g. an exact-session `b0` rollback ref that needed the
  minted UUID) is flagged `native_worker_git_authority_violation` at exit. Mint every host ref
  before launch, or expect to attribute a false positive at wake. The run-scoped pre-launch `b0`
  ref is sufficient rollback authority; the exact-session duplicate is not worth the flag.
- Watchdog shape that worked: poll the local branch tip + follow-log size + `native-worker
  status` every ~150s; emit commit subjects, terminal transitions, and a 30-minute quiet
  heartbeat.

## Decorator-placement regression class (2026-07-19, terminal review blocker)

Inserting a new helper between a decorator and its function silently moves the decorator onto
the helper (`@_locked_full_run` ended up wrapping pure `resolve_worker_effort`, leaving
`prepare_full_run` unserialized). Reviewers: when a diff adds a function directly above a
decorated definition, check `hasattr(fn, "__wrapped__")` on both. Pin the invariant with a
structure test asserting the wrapper is present on the entry point and absent on the helper.

## Parallelves staging (2026-07-19)

- Parallelves v1 is deliberately contracts + deterministic tooling with NO runtime
  orchestrator: the honest-scope guard that made the audit run's PR land cleanly applies
  doubly to a feature whose failure mode is overclaimed orchestration.
- Fable/low workers get smaller, more mechanical batches with exact section/code lists in the
  plan; re-drive budget 2/batch. The width-test/lane grammar is line-based on purpose so the
  parser stays stdlib-only (no yaml dependency).
