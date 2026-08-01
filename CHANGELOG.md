# Changelog

All notable changes to the Elves skill are documented here.

## [Unreleased]

### Fugu calling guide (host routing)

- Collapse Fugu host routing into one decision path: host-native first, first paid call plain
  unless the user set a flag, `--max-wait` before automatic `--deep`, **`--preflight` required when
  any `--include` is present**, task strings name goal / paths / done-when / out of scope.
- Profile choice by deliverable: plain/deep die empty on wall timeout; `--ultra`/`--max` reserve
  synthesis so a written report can still return.
- Add copy-paste `Fugu route:` templates and a wait/poll/capture contract: redirect to a log (never
  `| tail`), chat cancel does not stop the provider, kill the process group to stop spend.
- Companion field guide `references/fugu-calling-guide.md` (dogfood review runs + 2026 Claude Code /
  Codex practice: scope before spend, ranked review prompts, verify findings host-native).
- Field notes: Ultra/Max often run 20–60+ minutes and hit limits on open-ended prompts; keep those
  lanes narrow (public 2026 operator reports + Elves dogfood).
- Restate on SKILL, AGENTS, README, guide, and the Claude Fugu alias.

## [2.22.0] - 2026-08-01

### Full Linear backlog resolution

- User-specified worker models from the live catalog (`resolve_user_specified_worker_model`) with
  fail-closed unavailable/retired ids; handoff cache keys for qualification reuse; docs in
  `references/adaptive-worker-routing.md`.
- Shared secret-file deny corpus in `cobbler_runtime.context` consumed by isolation, Manus, and
  OpenRouter lens.
- Extract `scripts/run_fugu.sh` Python body to `cobbler_runtime/fugu.py` (thin shell shim).
- Compaction stewardship P3 (batch-boundary compact guidance) and P4 (prewalk compaction
  de-qualification) documented.
- Parallelves Phase 2 `validate_lane_staging` and runtime `LaneSupervisor`.
- Planning harvest helpers (`planning_harvest.py`) for beacons, discovery, modes, lean summary,
  task sandbox, canvas, mission prep, goal assessor, JIT batches, auto-plan, review filter,
  merge-recovery scope lock.
- Stdlib tool-output compact layer; usage-pressure routing without inventing quota; summary-video
  storyboard builder; Rust/RTK assessment (no-go port; yes compact layer).

### Fugu economy: preflight, wall cap, and host routing

 preflight, wall cap, and host routing

- Add `run_fugu.sh --preflight` to validate launcher readiness, profile, wall budget, write
  eligibility, and every `--include` path, then print a launch plan and exit without calling the
  provider. Hosts can confirm a non-obvious route before paying wall time.
- Add `run_fugu.sh --max-wait SECONDS` as a first-class wall cap (same authority as
  `SAKANA_FUGU_MAX_WAIT_SECONDS`) so slightly long plain work can stay on `fugu/high` instead of
  automatic `--deep`.
- Fail closed on bad `--include` paths **before** snapshot construction and provider launch, with
  remediation hints (gitignored notes, missing files, policy-blocked paths). Shared helper:
  `cobbler_runtime.isolation.preflight_requested_includes`.
- Document **Fugu economy** host routing: host-native first for inventory/triage/greps, default
  plain, narrow the packet before raising the profile, prefer `--max-wait` over automatic
  `--deep`, never `--include` gitignored paths, use `--preflight` when includes or write mode are
  non-obvious. Restated on SKILL, AGENTS, README, guide, alias, and
  `references/provider-shortcuts.md`; grammar pins include the new flags.

## [2.21.0] - 2026-07-29

### Automatic prewalk qualification

- Make `worker.prewalk=required` run a bounded live qualification canary automatically when matching
  cached proof is absent. The canary has a 180-second wall limit and 1 MiB combined output limit,
  uses a temporary Git worktree, sends the guide packet once, resumes the exact session with only
  `Continue.`, and proves route change, same worktree, one logical stream, retained guide context,
  and packet count before any task worker launches.
- Persist private version/build-and-route-bound success evidence under
  `${XDG_CACHE_HOME:-~/.cache}/elves/prewalk/`. Later `auto` runs reuse matching proof without model
  calls. Failed canaries stop before task launch and name a private `.attempt.json` artifact with
  bounded redacted diagnostics and check results.
- Add explicit `worker.prewalk=experimental`. It requires advertised exact resume and route
  override, reports `exact_session_experimental`, and accepts only qualification uncertainty. The
  real prewalk supervisor still enforces session, worktree, stream, one-packet, meaningful-edit,
  forbidden-path, Git-authority, and no-post-edit-cold-fallback rules.
- Give Claude Code, Codex, and Grok Build the same host semantics. Grok single-phase native-worker
  launch remains registry-gated; valid qualification or explicit experimental mode may enter only
  the non-yolo two-phase prewalk supervisor. Grok provider consent, repository veto, live catalog,
  API-key, Git, PR, and landing restrictions remain unchanged.
- Add prompt-file delivery to the shared multi-phase supervisor so Grok guide and `Continue.`
  phases use the same bounded input contract as its host profile.
- Update SKILL, AGENTS, README, product context, prewalk, host-parity, adaptive-routing, Grok,
  Parallelves, durable AI docs, learnings, config example, public guide, and test expectations for
  the automatic qualification contract.

## [2.20.0] - 2026-07-29

### Mid-run impact path; terminal full suite and deferred hygiene

- Reconcile overnight validation with the proof budget. Ordinary batches prove acceptance via the
  **impact path** (touched surfaces → selected tests) and fix **blockers** only.
- **Deferred hygiene:** bank advisory nits mid-run (survival guide + execution-log digest); drain
  at terminal readiness. Never defer red impact tests, build/typecheck blockers on touched work,
  unmet acceptance, or security/data-integrity defects.
- **Terminal:** full suite (or project full gate), one cumulative review, delta re-review only,
  drain deferred hygiene. No nested full product re-review of settled batches mid-run.
- Retune Effort Standard: hard work on plan acceptance and blockers, not mid-run nit perfection or
  re-running a large full suite between ordinary batches.
- Rewrite `references/validation-guide.md` (remove "zero accumulated debt / every batch
  production-ready" as mid-run law). Align SKILL, proof-and-review, survival-guide and
  execution-log templates, kickoff and open-ended guides, and consistency pins
  (`MIDRUN_TERMINAL_HYGIENE_PHRASES`).

## [2.19.0] - 2026-07-29

### Grok Build as a supported main driver (no prewalk)

- Grok Build may stage and run Elves as orchestrator alongside Claude Code and Codex. The safety
  kernel (memory, protected refs, PR, gates, landing, merge ownership) is the same.
- **Hard limit:** when Grok is the main driver, exact-session prewalk is always off. `auto`
  records actual mode `off`; `worker.prewalk=required` fails before launch. Prefer host-native
  work or a cold packet handoff. Never claim Grok-host prewalk.
- Grok remains an optional worker under Claude/Codex when permitted. Worker prewalk stays
  feature-gated and unqualified as before.
- Managed install targets remain Claude and Codex skill roots; Grok often discovers Elves via
  Claude skill compatibility. Native `~/.grok/skills` install remains issue #88.
- SKILL, AGENTS, README, guide (including the Grok FAQ), PRODUCT, host-parity, prewalk, and
  consistency pins restated for Claude/Codex/Grok host set and the prewalk gap.

## [2.18.1] - 2026-07-29

### Host Fugu routing for natural "use Fugu"

- Natural language such as "use Fugu" (or plain `/fugu` / `$elves fugu` without a profile flag)
  is no longer treated as an implicit always-bare `fugu/high` launch. The host agent must choose
  the lane before launch: general vs `review <scope>`, plain / `--deep` / `--ultra` / `--max`
  (profile locks model + effort; no free model slug), read-only vs qualified `--write`, and
  optional exact `--include` paths. Prefer the cheapest matching lane; explicit user flags always
  win. The disposable isolation snapshot remains always-on safety infrastructure, not a host
  skip option; the host only adds admitted context via `--include`.
- Authoritative decision table lives in `references/provider-shortcuts.md` under **Host routing
  when the user says "use Fugu"**. SKILL.md, AGENTS.md, README, guide, and the Claude `/fugu`
  alias carry the same contract anchors, and `FUGU_HOST_ROUTING_PHRASES` pins them so the
  routing story cannot land on five surfaces and miss the sixth (including model-lock and
  cheapest-lane anchors after Fugu review of PR #210).
- Flag→profile table is documented as the runner map only; flagless invocations are host-routed.
  Paid Fugu spend inside that section requires explicit user provider intent.

### Follow-up filed

- Issue #211 tracks an optional stdlib tool-output compact layer (RTK ideas without an RTK
  dependency): exit-code honesty, failure tee, git/test filters, Elves-owned subprocess wiring.

## [2.18.0] - 2026-07-27

### Structural-debt survey, deep-dive reviews, and executor plans

- Add `docs/reviews/2026-07-structural-debt-survey.md` (a four-auditor, driver-vetted audit of
  the v2.10→v2.17.1 growth: 28 registered findings with evidence, measured baselines, vetting
  corrections, and direction options) and `docs/reviews/2026-07-routing-caching-compaction.md`
  (driver→worker handoff economics, model-scoped prompt-cache reality, compaction control
  surfaces, and the recycle-beats-summarize doctrine). Executor-ready plans for the top five
  findings live in `advisor-plans/`; the items below are that first wave, and
  `advisor-plans/README.md` records per-plan status and deferrals.

### Honest verification signal on every host

- Skip the provider-shortcut suites below the Python 3.10 floor instead of failing 25 tests
  plus 2 errors with raw TypeErrors on stock macOS Python, and guard all three heredoc runner
  scripts (`run_fugu.sh`, `run_grok.sh`, `run_devin.sh`) with a clear "requires Python >= 3.10
  (repo floor)" message before the embedded Python executes.
- `verify_repo.py --ci` and `--final-readiness` now default `--version` from the SKILL.md
  frontmatter, so gate commands in docs never carry a version literal again. The stale
  `--version 2.10.0` examples in `.ai-docs/` (which failed three ways on a clean tree) become
  versionless forms, and the README maintainers' gates drop their literals. The 3.10 floor is
  now stated user-facing in the README and guide install steps. The unit test pinning the old
  require-`--version` contract is replaced by two sharper ones: fail closed when no SKILL.md
  frontmatter is present at the repo root, and resolve-and-proceed when one is.

### Redaction parity and secret-corpus unification

- Add `slack_webhook` and colon-less `uri_userinfo_bare` patterns to
  `context.SECRET_VALUE_PATTERNS`: both shapes were already redacted at the notify/preflight
  shell boundary but previously survived Python-side artifact persistence and the release
  secret scan. Classify `*WEBHOOK` environment names as secret, rebuild `setup.py`'s drifted
  private pattern copy on the shared corpus, and route four previously unredacted
  `json.dumps` payload prints in `cobbler_agents.py` through the redacting `_emit_json`. A new
  parity test pins every named pattern to a synthetic sample and asserts the shell and Python
  boundaries cover the same shape families. Operators should rotate any Slack webhook or
  URL-embedded token that passed through run artifacts before this release. Deny-list
  unification across `isolation`/`openrouter_lens`/`manus` remains tracked in issue #204.
- Teach the release secret scan that documented Slack webhook placeholders
  (`T.../B.../...`, `YOUR/WEBHOOK/URL`) are not credentials, so the new pattern does not fail
  `verify_repo.py --ci` on the shipped operations-guide and tool-config examples. Live
  multi-segment tokens still fail closed; a unit test pins both sides.

### Preflight and snapshot hardening

- `preflight.sh` no longer aborts the entire checklist at the gh-identity section when
  `gh auth status` uses the `as <user>` wording: the previous `grep -o "account ..."` pipeline
  exited nonzero under `set -euo pipefail`, killing sections 3-14 before any real check ran.
  Both wordings are now parsed by one total `awk` extraction and covered by tests.
- The public-API snapshot baseline extraction fails closed when `tarfile`'s `filter=` keyword
  is unavailable (Python 3.10.0-3.10.11 / 3.11.0-3.11.3, inside the supported floor): archive
  members are hand-validated against non-regular types, absolute paths, `..` segments, and
  destination escapes instead of falling back to an unfiltered `extractall` of a
  caller-supplied ref.
- `verify_repo.py`'s shell gate now compiles every `<<'PY'` heredoc body with real-file line
  mapping, so the ~1,760 embedded Python lines in the provider runners can no longer ship
  unparseable (`bash -n` treats a quoted heredoc as an opaque string, and `compileall` never
  visits `.sh` files). Extracting the Fugu body into an importable module remains tracked in
  `advisor-plans/004` and issue #203.

### Docs: grammar completion, compaction stewardship, config example

- Complete the remaining `/fugu` invocation-grammar drift siblings of the v2.17.1 fix:
  SKILL.md's copy-ready task line gains `[--write] [--include PATH]`, and the review forms on
  SKILL.md and AGENTS.md gain the `[--deep|--ultra|--max]` profile flags. A new
  `FUGU_INVOCATION_GRAMMAR_PHRASES` group pins the full task and review grammar on the
  restating surfaces so a runner flag can no longer land on five surfaces and miss the sixth.
- Extend `references/operations-guide.md` with deterministic post-compaction recovery (a
  `compact`-matched SessionStart hook) and a compactor "Summary instructions" block that
  preserves acceptance IDs, run-doc paths, the branch name, and Stop Gate state. Both are
  marked version-dependent and should be verified against the installed host's hooks
  documentation.
- Add the missing `worker.parallel` key to `config.json.example`'s worker block, and remove
  the one em dash from `guide/index.html` per PRODUCT.md's guide voice.
- Align remaining user-facing version callouts to v2.18.0 (SKILL.md user-guide label and the
  guide's GitHub source/releases link) so Claude Code and Codex adapter surfaces stay in lockstep
  with the release pin.

### Backlog tracking

- Live backlog tracking moves from `TODO.md` to GitHub issues. `TODO.md`'s Live section
  becomes a migration map and pointer; its Completed Archive remains as history. Issues
  #203-#208 cover the v2.18.0 deferrals and the previously unfiled Parallelves phases.

## [2.17.1] - 2026-07-25

### Document the `--max` flag on every invocation surface

- v2.17.0 shipped the `/fugu --max` lane and described its model, effort, and wall budget, but left
  every user-facing invocation grammar reading `[--deep|--ultra]`, so the flag was undiscoverable
  from the docs on both supported hosts. Update the grammar to `[--deep|--ultra|--max]` across the
  Claude Code form (`README.md`, `guide/index.html`, the `/fugu` alias, and the shortcut table),
  the Codex form (`AGENTS.md` and the shortcut table's `$elves fugu` column), the `run_fugu.sh`
  invocations in `SKILL.md` and `AGENTS.md`, and the pinned alias phrases in the consistency policy.
  Claude Code and Codex were equally incomplete, so host parity was never broken — both were simply
  missing the flag.

## [2.17.0] - 2026-07-25

### Fugu `--max` lane

- Add `/fugu --max` (`$elves fugu --max`): `fugu-ultra-v1.1` at `max` effort on a 60-minute default
  wall budget. v2.16.0 documented v1.1's third effort level but exposed no lane, reasoning that
  `--ultra`'s value is its reserved exact-session synthesis inside a bounded wall limit. Field use
  argued the other way for one narrow, high-stakes gate — a proof step, a security-sensitive review,
  a decision that has to be right the first time — provided the prompt is narrow and the timeout is
  long. The lane keeps everything that makes `--ultra` useful (same versioned model, catalog
  resolution, reserved synthesis, identical context and audit rules) and changes only the effort
  level and the wall budget. Profiles stay mutually exclusive, so `--ultra --max` is rejected.
- Note that `max` is real only on `fugu-ultra-v1.1`: a legacy bundle publishing only the floating
  `fugu-ultra` alias has the provider map `max` down to `xhigh`, which is the provider's documented
  compatibility behavior rather than a silent Elves downgrade.
- State in `references/provider-shortcuts.md` that every Fugu profile is bounded by a hard
  wall-clock limit covering exploration, synthesis, and cleanup — in contrast to stream/SSE idle
  timeouts elsewhere in Sakana tooling, under which a Max or Ultra call emitting heartbeats can run
  indefinitely and needs a separate cap.
- Extend `FUGU_SHORTCUT_PROFILE_PHRASES` to pin the new lane on all six restating surfaces.

### Load-stable Fugu Ultra exploration budgets

- Raise the exploration budgets in four Fugu Ultra tests from 0.8-1s to 3s (wall 10s). The previous
  budgets sat below the kernel-sandbox process-spawn floor, so under load the fake launcher could
  not emit `thread.started` before the phase closed and all four failed together with
  `exploration ended without a resumable exact thread id`. Under 2x CPU oversubscription across 22
  runs the old budgets failed 1/22 and the raised budgets 0/22.
- Recorded for the next person: making the fakes cheaper does *not* fix this. Emitting the thread id
  before draining stdin and replacing a `dd | tr` pipeline with one `printf` builtin measured
  20/22 against a 21/22 baseline — indistinguishable. The cost that matters is process spawn under
  the sandbox, which no fake-side change removes.

## [2.16.1] - 2026-07-24

### Deterministic supervisor and Manus timing proofs

- Stop `test_nonzero_exit_overrides_complete_worker_report` and its three sibling
  lifecycle waits from polling through the supervisor reaping window. `monitor_full_run`
  deliberately refuses an exit record while the recorded identity is still alive, and that
  refusal is not transient in the state machine: a later poll recovers `exit_code`, but the
  blocker keeps naming the premature refusal, so the settled nonzero-exit classification is
  unreachable once the window has been observed. Waiting for the reap before monitoring
  removes the race at its source instead of widening a deadline. `await_supervised_reap`
  fails loudly when the identity is still alive after its budget, so a genuinely unreapable
  run reports that directly rather than as a confusing assertion elsewhere.
- Add a deterministic regression test that holds the recorded group alive past the product's
  settle window and pins the resulting `failed` status with no `exit_code` — the exact status
  a poll-for-first-terminal-state test captured on a loaded CI host.
- Give `test_manus_wide_timeout_is_hard_bounded_and_resumable` a wall budget above the
  create round trip. The runner arms its deadline at the top of `main()`, so the previous
  0.05s budget had to cover roster setup, manifest writes, and the create call; on a loaded
  host it expired first and left `main_task` null, failing on a bare `TypeError`. The timeout
  still fires during polling, and an explicit precondition assertion now names the cause
  instead of subscripting `None`.

### Fugu shortcut profile drift guard

- Add `FUGU_SHORTCUT_PROFILE_PHRASES`, pinning `fugu/high`, `fugu/xhigh`, and
  `fugu-ultra-v1.1/high` across `SKILL.md`, `AGENTS.md`, `README.md`, `guide/index.html`,
  `references/provider-shortcuts.md`, and the Claude alias, each in that surface's own
  markup. Fugu was previously covered only by the alias phrase group, so a model rename could
  land on five surfaces and miss the sixth — which is how `guide/index.html` kept saying
  `fugu-ultra/high` through the v2.16.0 rename.

## [2.16.0] - 2026-07-24

### Opus 5 delegation and family-local native handoffs

- Add the Claude Opus 5 delegation default: a driver planning at Opus 5 `max`/`ultracode` hands off
  to the same observed `claude-opus-5` model at `high`. Opus 5 is capable enough at `high` that the
  worker no longer needs to match the planner's effort, and the pair keeps the existing
  same-model/lower-effort shape.
- Remove the Fable→Opus cross-model route. Native delegation now stays inside one model family in
  every case: a Fable 5 `max`/`ultra` driver hands off to `claude-fable-5` at `low` rather than
  crossing into the Opus family. The route was documentation-only, so nothing in the runtime
  changes; `references/adaptive-worker-routing.md`, `SKILL.md`, `README.md`, `guide/index.html`,
  `.ai-docs/architecture.md`, and the consistency policy drop it together. The one remaining
  cross-family worker is the explicitly permitted, capability-probed Grok Build handoff, which a
  user opts into rather than receiving as a default.

### Fugu-Ultra v1.1 and the Claude Code-compatible Fugu endpoint

- Resolve the `/fugu --ultra` model against the installed Codex catalog instead of hard-coding one
  spelling. Sakana's 2026-07-24 catalog publishes `fugu-ultra-v1.1` and drops the plain
  `fugu-ultra` slug that older bundles listed, so the lane prefers `fugu-ultra-v1.1`, accepts the
  equivalent `fugu-ultra` alias from a legacy bundle, and otherwise keeps `fugu-ultra-v1.1` and
  lets the provider resolve its own aliases. `fugu-ultra-v1.0` is never substituted, because it is
  a different model. Catalog reads are bounded and fail safe: an unreadable, oversized, or
  unparseable `fugu.json` keeps the default rather than failing the lane. Ultra-phase detection
  keys on the `fugu-ultra` prefix so every published spelling resolves correctly.
- Correct the documented effort facts. `max` is a genuinely distinct third effort level on
  `fugu-ultra-v1.1` only; `fugu`, `fugu-ultra-v1.0`, and `fugu-cyber` still accept `max` as a
  compatibility alias for `xhigh`. The shortcut still exposes no `max` lane, because `--ultra`'s
  value is its reserved exact-session synthesis phase inside a bounded wall limit.
- Document Sakana's Claude Code-compatible endpoints and `claude-fugu` launcher: the
  `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` pair, the `[1m]` tier model names, and the cosmetic
  Claude Code mismatches Sakana lists (six-stop effort slider collapsed onto the `high`/`xhigh`
  boundary, duplicate Sonnet/Haiku picker rows, API-token billing labels). The `/fugu` shortcut
  deliberately stays on the separately audited `codex-fugu` lane; that safety kernel is qualified
  against Codex semantics and does not transfer to another launcher by analogy.
- State in `references/prewalk.md` that the Claude Code-compatible Fugu route advertises the same
  `--resume` grammar but remains an unqualified external provider, so `auto` keeps reporting actual
  mode `off` for it, and that pinned Fugu routes must name a current catalog slug.

## [2.15.0] - 2026-07-23

### General Fugu tasks and explicit review mode

- Separate provider choice from task type. Plain `/fugu <task>`, `$elves fugu <task>`, and natural
  “use Fugu” requests now return task-appropriate analysis, design, investigation, or other
  deliverables without forcing review severities or a clean verdict. `fugu review <scope>` retains
  the read-only base/change review with ordered P0-P3 findings and exact file/line evidence.
- Replace Fugu's tracked-only context with a bounded Git-enumerated snapshot of policy-admitted
  tracked and non-ignored untracked files. Repeatable `--include <path>` records exact host-selected
  context and fails if it cannot actually be admitted and copied, while ignored
  dependency/cache/build trees, both `.env.*` and `*.env` dotenv/credential families, reserved
  internal namespaces, Git/Elves state, executable agent configuration, unsafe file types/links,
  ownership violations, repository escapes, and count/size overflow remain excluded or fail closed
  with visible bounded diagnostics.
- Add user-authorized `--write` for general tasks only. Fugu may modify only its disposable
  kernel-isolated snapshot; a host-side before/after digest-and-mode audit rejects protected,
  credential, unsafe, or oversized output and exports accepted regular files/deletions as an inert
  temporary handoff. Mode-only and executable changes retain safe manifest/export semantics. The
  host checkout is never mutated and the handoff is never applied automatically. Writes require a
  qualified recursive Linux bwrap PID namespace and fail before provider launch on macOS.
- Preserve regular `fugu/high`, deep `fugu/xhigh`, and `fugu-ultra/high` behavior across task
  modes, including closed input, credential scrubbing, no Linux procfs, qualified macOS/Linux
  filesystem boundaries, hard-wall cleanup, exact-session Ultra synthesis, bounded incremental
  event parsing over a host-owned pipe, no-follow pinned final output, and live writable-state
  limits that tolerate benign temporary-tree disappearance while failing closed on other audit
  errors. Every settled phase receives a final descriptor-safe audit. macOS read-only cleanup is
  explicitly best-effort and non-authoritative; polling is not recursive containment.
- Update the Claude alias, Codex adapter, README, guide, provider reference, installed bundles,
  consistency policy, hermetic provider/isolation coverage, and release examples for v2.15.0.

## [2.14.1] - 2026-07-23

### Install ship-list correctness and audit hygiene

- Ship `scripts/worktree_gc.py` and `scripts/provider_supervisor.py` in installed Claude Code and
  Codex skill bundles. Both are call-site dependencies of shipped `preflight.sh --gc-worktrees` and
  `full_run.py` provider supervision; bundle smoke now requires them and fails if either is missing.
- Document call-site runtime deps and source-only archives (`docs/plans/`, `docs/elves/`) in
  `references/runtime-helper-paths.md`. Historical identifying past-run artifacts under
  `docs/elves/` were removed so committed examples stay non-identifying; durable learnings remain.
- Enforce source-only archive fences in sync apply/check so managed allowlist mistakes cannot install
  `docs/plans` or `docs/elves`.
- Relax effort-guardrail consistency pins from exact motivational sentences to section/contract
  anchors so ordinary editorial rewording does not break CI. Survival-guide validation keeps the
  effort section concepts without requiring a byte-exact phrase.
- Add an **anti-accretion** code-quality rule in `SKILL.md`: no new repo meta-tooling, coined terms,
  or config keys without an explicit plan acceptance criterion naming overnight-run value.
- Preserve Claude/Codex host-parity: only managed install surfaces and shared workflow docs change;
  invocation wording is unchanged.

## [2.14.0] - 2026-07-22

### Landing profile learning loop

- Add host-owned observation capture, deterministic candidate synthesis, explicit promotion, and
  exact-HEAD waivers under gitignored `.elves/runtime/landing-profile/`. Learning state never grants
  merge, tag, release, protected-ref, connector, secret, or posting authority.
- Extend `scripts/landing_profile.py` with `observe`, `propose`, `candidates`, `promote`, `waive`,
  and `clear-waiver`. Only explicit `promote` rewrites tracked `.elves/landing-profile.json`; there
  is no auto-promotion. Candidates remain schema-v1 shapes (`path_touched` /
  `post_merge_checklist`); executable shapes stay unsupported and fail closed.
- Bind exact-HEAD waivers into evaluation digests: a waived blocking path failure becomes
  `status=waived` for that HEAD only, and a moved HEAD invalidates the waiver.
- Keep missing-profile neutrality and schema-v1 evaluation unchanged for repositories that never use
  learning commands. Document the learning loop and ship focused hermetic coverage.

## [2.13.0] - 2026-07-22

### Exact-HEAD project landing profiles

- Add tracked `.elves/landing-profile.json` schema v1 with bounded `path_touched` and declarative
  `post_merge_checklist` checks; missing profiles remain neutral while unsafe, malformed,
  unsupported, executable, or blocking-failed profiles fail closed.
- Bind deterministic results to exact profile bytes, HEAD, resolved base and merge base, and
  normalized outcomes. Schema v1 rejects `command`, `argv`, and other executable shapes before any
  profile-directed process launch; fixed internal local Git reads provide repository identity and
  changed paths only.
- Make project green/digest state a distinct host-owned landing-authority input that workers cannot
  assert and that never grants merge, tag, release, protected-ref, connector, secret, or posting
  authority. Ship the CLI/runtime in both installed host bundles.
- Dogfood the profile for documentation, guide, changelog/release, and Claude/Codex parity
  freshness. For a host-authorized release-worthy merge, require verification of the matching
  immutable GitHub tag/release and a <=280-character X announcement draft with value and link;
  never post it automatically.
- Harden Fugu's bounded process-group cleanup against Darwin's `EPERM` zombie-leader race without
  extending the provider wall deadline, fail closed with a distinct status when reap remains
  unproved, and keep its bootstrap-inclusive macOS timing proof below the fake provider's unbounded
  completion time.

## [2.12.0] - 2026-07-21

### Optional provider convenience shortcuts

- Add installed runner scripts and Claude Code aliases for `/fugu`, `/manus`, `/grok`, and
  `/devin`, with host-honest `$elves …` / natural-language equivalents for Codex.
- Route Sakana review through the official project-aware `codex-fugu` CLI in a bounded, read-only
  session: regular `fugu/high` by default, `fugu/xhigh` with `--deep`, and `fugu-ultra/high` with
  `--ultra`. Keep regular/deep ephemeral; give Ultra compact evidence and a bounded exact-session
  synthesis phase so it returns a verdict without guessing “last” state, while keeping all raw
  events and session state inside the disposable lane. Use the Manus v2 task API, documented
  headless Grok CLI, and
  official Devin sessions API instead of homepage URLs, unbounded agent loops, or shell-built JSON.
- Add Cobbler-managed Manus research rosters: `--wide` requests native Wide Research and
  reconciles structured one-result-per-roster-item coverage; missing or duplicated items fall back
  to deterministic top-level tasks before synthesis. Add explicit file upload, direct `--fanout`,
  atomic ignored manifests, and duplicate-safe `--resume`, while documenting that the public API
  cannot force Wide Research or directly create its internal child agents.
- Make known-failed Manus repair, fan-out, and synthesis tasks selectively retryable on explicit
  resume while retaining bounded failure history and emitting validated rows if synthesis fails.
  Give synthesis a fresh task, normalize waiting exits, reject zero-delay polling, strengthen
  credential-path refusal, and cover retry/recovery behavior hermetically.
- Harden every provider boundary after independent review: run Fugu over a tracked-only snapshot
  with same-policy diff evidence, including safe deletion patches but not deleted credential paths,
  in a required OS filesystem sandbox and allowlisted environment, without Linux procfs exposing
  the credential-bearing parent; grant metadata-only macOS traversal for native temp/cache path
  resolution and only the active immutable Codex distribution for adjacent runtime metadata, so the
  real CLI works without exposing sibling contents; and explicitly let Codex review the deliberately
  Git-metadata-free snapshot in its documented external-sandbox mode while regression-proving that
  Elves' mandatory outer boundary still blocks writes;
  run Grok over a disposable tracked-source snapshot in Elves' required outer read-only kernel
  sandbox plus Grok's built-in inner `strict` profile, with an explicit provider key, a tool shell that
  scrubs both key names before model-directed commands, no Linux procfs for parent-environment
  inspection, provider-documented isolated `dontAsk`, and a bypass lock, while rejecting
  shared-file OAuth that the provider/tool sandbox cannot safely separate;
  send Manus's connector and skill-selection lists at the documented nested `message` location,
  avoid explicit connector/forced-skill grants, and disclose that empty `enable_skills` loads
  account defaults instead of claiming skill isolation; confine new/resumed Manus manifests to
  `.elves/runtime/manus/` through no-follow traversal, exclusively reserve new records before
  upload, never overwrite, and durably mark paid roster-task create intent so interrupted task-ID
  persistence fails closed against duplicate resume; and
  give Devin empty secret/knowledge grants plus bounded response bodies and hard wall-clock
  creation/poll timeouts capped by one wait budget. Manus API and upload bodies use the same hard
  deadline instead of relying on socket-idle timeouts.
- Ship the runners in installed bundles, preserve managed-alias conflict protection, bound remote
  polling, and add hermetic transport and inventory coverage plus README/guide/host-parity docs.

## [2.11.0] - 2026-07-20

### Parallelves v1: contract and deterministic lane tooling

- Add the **Parallelves** contract (`references/parallelves.md`): Cobbler-coordinated parallel
  implementation lanes within one run, with trunk -> lanes -> integration topology, a mandatory
  cross-lane integration entropy review, reversible demotion back to serial, and optional
  competitive lanes. Serial remains the default everywhere; there is no runtime lane
  orchestrator in v1 and no sentence claims one.
- Add deterministic, model-free lane tooling (`scripts/cobbler_runtime/parallel_lanes.py` and the
  `lanes validate` / `lanes plan` CLI): a bounded fail-closed plan-lanes parser, a lane-partition
  validator, and the four-gate width test (structural width, worker dominance, lane budget, risk
  posture). The test is recommend-only; every declined gate records a concrete
  `parallel_declined:<gate>:<detail>` reason, and nothing auto-launches.
- Add the `worker.parallel` preference (`off` default | `auto`), glossary entries, plan-template
  lane grammar, host-parity notes, review-subagent integration-entropy section, and
  SKILL/AGENTS/README/guide coverage, all pinned by the consistency checker.

## [2.10.4] - 2026-07-19

### Doc precision and guide navigation

- Qualify explicit-route precedence in `SKILL.md` and
  `references/adaptive-worker-routing.md`: an explicit worker route choice wins for any
  **catalog-listed, non-retired** model, matching the routing refusal of retired Composer 2.5
  (`model_retired` fallback instead of silent substitution).
- The quick-start guide footer now links back to the main Elves page on GitHub alongside the
  changelog and releases.

## [2.10.3] - 2026-07-19

### Grok worker model, host check, and new-user onboarding

- Prefer **`grok-4.5` at `high`** for permitted Grok Build workers when the authenticated live
  catalog returns it. **Composer 2.5** (`grok-composer-2.5-fast`) is retired and is never selected
  (explicit pin or live default); launch-time `auto` uses the same preferred-model helper in
  routing, full-run prepare, and legacy implement launch.
- Add a **supported main drivers host check** in `SKILL.md` / `AGENTS.md`: if Grok Build (or another
  non–Claude/Codex host) is the orchestrator, refuse to stage or run Elves and redirect to Claude
  Code or Codex. Grok remains an optional worker under those hosts.
- User guide: **[Paste this to your agent](https://aigorahub.github.io/elves/#agent-onboarding)**
  install/orient block; FAQ for “I opened Grok and tried `/elves`”; worker table and README updated
  for Grok 4.5 / host policy. `references/model-onboarding.md`, `host-parity.md`, `docs/cobbler.md`,
  and Grok worker docs aligned.
- Track follow-ups: native `~/.grok/skills` install (#88) and full Grok main-driver parity (#89).

## [2.10.2] - 2026-07-19

### Confidence-review attribution and effort-authority fixes (issue #86)

- Fix confidence-review batch attribution: canonical `B0`/`B1` report ids now parse through the
  shared batch-id normalizer (honoring a parsed `0`) and event↔report merging keys on the
  normalized number, so event signals land on their own batch, corroboration is never
  fabricated across batches, and same-batch conflict detection can fire.
- Unify the four confidence-projection copies in `full_run.py` behind one shared helper;
  reject a worker-supplied `unsure_about_count` without its `unsure_about` list outside the
  shared-OAuth projection; keep the highest-attention rows (with an explicit dropped count)
  when the review prompt block overflows; state the hidden-item count on reservation
  truncation; and compare reservation sets order-insensitively in conflict detection.
- Make effort explicitness one normalized authority: the operator parser rejects abbreviated
  long options (`--effor low` fails loudly), the CLI passes `effort=None` unless explicit,
  `prepare_full_run` resolves the adapter default from the normalized adapter name (mixed-case
  `Grok-Build` gets the grok `high` default), and the resolved effort plus its explicit origin
  persist in run state so a flagless resume prepare keeps an originally-explicit value.
- Salvage torn event logs on host reconstruction: valid earlier events survive a torn final
  line and the review block reports partial or discarded evidence instead of claiming no
  signal was reported. Monitor/await delivery of `review_context` is proven end-to-end, and a
  latent missing `typing.Mapping` import that crashed every text-mode CLI print of the review
  block is fixed.
- Guard docs and policy: a one-sided bump of the doc-pinned Grok upstream short SHA or
  `GROK_UPSTREAM_SEMANTIC_COMMIT` now fails the consistency checker; the public-wording guard
  flags persona claims (powered-by/built-on/backed-by phrasings naming the model) while
  passing `Fable 5` / `claude-fable` model identifiers; the Grok launch prompt no longer contradicts its own
  `--effort high` default; and the prewalk launch example marks execution effort
  route-dependent.
- Harden the supervisor: `leases.run_git` enforces a 30-second default timeout matching the
  native-worker git hardening (explicit overrides remain), and the prewalk capability-evidence
  loader reads through the one shared fd-bound artifact reader, rejecting symlinked,
  irregular, group/other-writable, or oversized artifacts.
- Operator note: any pre-upgrade Grok qualification canary recorded at execution effort
  `medium` fails `qualification_route_mismatch` under the new grok-route `high` default and
  must be re-recorded at `high`.

## [2.10.1] - 2026-07-19

### Confidence-guided reviewer handoff

- Turn validated full-run `confidence` / `unsure_about` evidence into a bounded
  `elves-worker-confidence-review-v1` context on successful terminal reconciliation, carried by
  the monitor/await or host-reconstruction response with an exact `review_prompt_block` for the
  primary reviewer.
- Conservatively combine report and event signals: low confidence, reservations, hidden
  shared-OAuth reservation counts, and conflicting sources require a deeper pass; partial or
  missing signals explicitly retain full baseline review, and high confidence can never reduce
  gates or review scope.
- Give Claude Code and Codex the same Final Readiness prompt contract and required
  `Confidence-Guided Review` output; native worker runs derive the identical triage table from
  cumulative `Confidence:` commit trailers.

## [2.10.0] - 2026-07-19

### Runtime hardening and Python 3.10 floor guards (audit B1)

- Add explicit Python >= 3.10 entry-point guards to `sync_installed_skills.py` and
  `installed_bundle_smoke.py`, and version-gate their test modules so a local 3.9 run reports
  skips instead of errors; CI (3.10/3.12/3.14) behavior is unchanged.
- Narrow native-worker identity capture to host-known identity event types, so a foreign
  `session_id` in ordinary worker stdout can no longer bind or mismatch session identity.
- Scope transient-failure markers to stderr lines and provider error events (task stdout that
  merely mentions "timeout" is terminal, not transient); unify one canonical
  `schema.AMBIGUOUS_SESSION_TOKENS` set (`continue`, `most-recent`, `most_recent`, leading-dash
  guard) across every consumer site.
- Terminalize hung-git `TimeoutExpired` on the supervise/status paths with an honest
  `native_worker_git_timeout` state, tolerate torn follow-log JSON lines, preserve a bounded
  `stderr_tail` alongside provider events, report the post-edit code when guide recovery moved
  HEAD, and enforce at test time that every emitted failure reason is a member of
  `PREWALK_FAILURE_CODES`.
- Keep the public-API compatibility gate strict while classifying recursively additive,
  non-required JSON Schema properties as compatible; removals, changed definitions, and new
  required properties still fail closed.

### Explicit delegation route identity and Grok highest-effort default

- Define native worker handoffs as explicit `(model, effort)` routes: GPT-5.6 strong-driver routes
  keep the same GPT-5.6 identity at `medium`, GPT-4.8 Max/UltraCode keeps the same GPT-4.8 identity
  at `medium`, and Fable 5 `max`/`ultra` keeps Fable 5 at `low`. The Fable→Opus exception is named
  honestly as `claude-opus-4-8` at `medium`, not described as same-model inheritance.
- Make permitted Grok Build delegation use the authenticated live-catalog default at explicit
  `high`, Grok's highest supported effort. Full-run and legacy launch defaults now agree; Devin
  retains its existing `medium` default, explicit effort overrides still win, and Elves never
  hardcodes a stale Composer model absent from the live catalog (rechecked with Grok Build 0.2.103
  and upstream source commit `7cfcb20`).

### Host-profile registry and feature-gated Grok prewalk arm (audit B2)

- Extract a single host-profile registry (`cobbler_runtime/host_profiles.py`) consumed by spec
  construction, child-env secret projection, launch identity readiness, prewalk probe functions,
  and routing transport naming; codex/claude argv stays byte-identical (proven by differential
  tests) and `native_worker_profiles()` becomes a view of the registry.
- Add a feature-gated `grok` host row: create `--session-id <uuid> --cwd <worktree> --model
  --effort --permission-mode auto --output-format streaming-json`, exact `--resume <uuid>` with
  execution route flags, `XAI_API_KEY`-only secret allowlist, and never
  yolo/always-approve/dontAsk on this lane. `launch_ready` is false: `native-worker launch --host
  grok` fails closed, and the arm remains feature-gated off.
- Replace the categorical external-provider prewalk veto with qualification-based gating:
  provider=grok prewalk requires the absence of the repository `allow_grok=false` veto, explicit consent, and a valid qualification
  artifact; otherwise routing records the honest concrete fallback
  `prewalk_capability_unavailable:grok_prewalk_unqualified:<reason>`. Default outcome in every
  current environment is unchanged: actual prewalk mode `off` for every host.

### Grok prewalk qualification tooling (audit B3)

- Add the read-only static probe `native-worker prewalk-capabilities --host grok --json`
  (installed help/version grammar only, zero model calls, concrete unavailable reason without an
  installed binary) backed by a recorded help fixture.
- Add the `grok_prewalk_qualification_canary` schema v1 and `load_grok_prewalk_qualification`:
  a bounded (<= 64 KiB) fd-bound (O_NOFOLLOW, fstat-identity) loader requiring the exact
  18-field set, canonical session UUID, and installed version plus parsed build-commit binding;
  every single-field mutation fails closed with a stable diagnostic. `route-worker` gains
  `--grok-prewalk-qualification <artifact.json>` and requires `--probe-grok`, so the artifact is
  checked against the version and build commit reported by the installed binary rather than
  trusting its self-asserted identity.
- `qualified()` semantics mirror the native rule: only operator-recorded `retained_safe`
  evidence can satisfy the behavioral gate; `pruned`/`turn_scoped` load as recorded,
  non-activating states. Qualification never opens the separate registry launch feature gate,
  so actual Grok prewalk remains off and `required` fails closed while `launch_ready` is false.
  The tooling validates artifacts and never fabricates them; no live artifact exists and no
  canary ran.

### Contract amendments, glossary, and doc hygiene (audit B4)

- `references/prewalk.md`: the separately-qualified external-provider doorway is now the
  governing sentence, the Promise admits a separately qualified worker session, the host-parity
  table gains a Grok Build column (marked feature-gated, unqualified), and the qualification
  artifact plus `--host grok` probe are documented.
- `references/adaptive-worker-routing.md` and `references/host-parity.md`: document the grok
  probe, the qualification flag, provider=grok x `worker.prewalk` semantics (auto falls back
  honestly; required fails before launch), and extend the release-honesty rule to external
  providers. `references/grok-open-source-worker.md` gains the non-yolo prewalk-lane section and
  the operator live-canary procedure (verification basis: grok-build 0.2.102 source, commit
  `98c3b24`).
- `references/glossary.md`: add prewalk, guide/execution route, instruction fidelity,
  behavioral qualification artifact, canary, Lane A, Mode A1, main/work driver, implementation
  lane, and state capsule; remove the dead "Handling matrix" entry.
- Doc hygiene: fix the installed-bundle dead link in `councilelves-launch-prompt.md`, add
  `opencode-cli` to the canonical work-driver spelling map, align the `grok-4.5`
  catalog-membership framing between SKILL.md and the routing doc, add 0.2.93 vs >= 0.2.101
  version-applicability markers to `grok-implementer-launch-prompt.md`, and restructure
  `TODO.md` into a live backlog plus `## Completed Archive`.
- Grok prewalk remains feature-gated off for every host and environment; nothing in this release
  claims Grok prewalk availability or behavioral qualification.

### Worker confidence signal (audit B5)

- Add optional additive `confidence` (`high`/`medium`/`low`) and `unsure_about` (bounded list of
  non-empty strings, at most 16 items of 500 chars, no secret-like text) fields to trusted
  full-run `batch_complete`/`run_complete` events, report `batches[]` rows, and the legacy done
  report schema. Absent fields stay valid; present fields are validated fail-closed with stable
  diagnostics, and the legacy gate reports malformed fields as non-fatal warnings.
- An empty `unsure_about` list is a valid, complete answer everywhere — a positive assertion
  ("I verified everything I touched and have no reservations"), never a lazy default. The signal
  is review triage only, never authority: it does not skip gates, waive review, or change
  completion requirements in either direction.
- The parked supervisor surfaces the latest `batch_complete` confidence signal in its bounded
  monitor `check_summary` (redacted; under shared OAuth the free-text list is replaced by a
  bounded derived count and the confidence enum still surfaces, so suppression never conflates
  with the asserted-clean empty list; null means no signal). Shared-OAuth projection validates
  and secret-scans the original confidence fields before removing free text, preventing malformed
  `unsure_about` data from being normalized into an apparently valid count. SKILL.md adds
  the batch-Close `Confidence:` commit trailer format, and the review subagent reads the signal
  first to allocate attention to flagged areas.

## [2.9.0] - 2026-07-17

### Grok Build unattended-launch compatibility

- Stop combining Grok Build's `--permission-mode auto` with `--always-approve`. Grok Build 0.2.101
  gives the explicit permission mode precedence, which disables always-approve and can cancel the
  first headless tool permission. Trusted implementation launches now use the unambiguous
  `--always-approve` surface alone; non-yolo launches retain their explicit permission mode.
- Treat structural Grok terminal `Cancelled`, refusal, error, and max-turn records as typed worker
  failures even when the provider process exits zero. Shared-OAuth monitoring exposes only the
  bounded category and never raw transcript text.

### Explicit handoff v1 staging contract

- Add opt-in machine-readable coordinator-to-worker handoff validation. A session that declares a
  top-level `handoff` object now binds fresh-start/resume state, the active batch, completed-slice
  commit evidence, exact pending-acceptance ownership, and the next worker action to the current
  repository branch and HEAD.
- Support the same state capsule and exact plan/packet acceptance mapping in leading Markdown
  `elves-handoff-v1` comments and JSON `elves_handoff` objects. Packet reads are UTF-8 and bounded;
  malformed, misplaced, oversized, or identity-drifting declared capsules block staging.
- Preserve v2.8 compatibility: delegable sessions that do not declare handoff v1 retain the
  advisory-only missing-`worker_packet_path` diagnostic. A capsule describes a cold handoff and
  never proves exact-session prewalk continuity.

## [2.8.0] - 2026-07-17

### True exact-session native-worker prewalk

- Add a feature-gated Codex/Claude prewalk lifecycle: one worker packet and exact session/worktree,
  guide-route orientation, bounded TODO plus model-free meaningful-edit checkpoint, automatic
  execution-route resume with only `Continue.`, and one redacted phase-labeled follow stream.
- Add version-3 private state, stable failure diagnostics, exact-session guide recovery, canonical
  5/10/20-minute execution transport backoff, explicit clean pre-edit `auto` fallback, and strict
  prohibition of cold fallback after any task edit. Version-2 single-phase workers remain valid.
- Add provider-neutral route/capability/fidelity contracts, the safe `worker.prewalk` preference,
  read-only installed-host probes, exact-version behavioral qualification artifacts, deterministic
  parity/lifecycle fixtures, installed-bundle proof, and the normative `references/prewalk.md`.
  Static help is advertised grammar only; the current transport activates only with proven
  `retained_safe` evidence; no paid canary ran and unqualified `auto` resolves off.

### Release checklist automation

- `release_checklist.py --json` emits one deterministic machine-readable object (`version`, `ok`,
  `failures`, `warnings`, `notes`; sorted keys) for automation consumers. Selected from the
  release-json worker benchmark (grok implementation) and landed via cherry-pick.

### Documentation and host parity

- Align SKILL, the thin Codex adapter, README, public guide, routing/parity references, durable AI
  docs, changelog, and current-version examples on v2.8.0. Codex and Claude retain equivalent
  trajectory, checkpoint, recovery, visibility, and authority semantics through host-specific CLI
  grammar; neither host is claimed behaviorally qualified by this release.

## [2.7.0] - 2026-07-17

### full_run.py split, phase 1

- `full_run.py` shrinks from 10,090 to 7,019 lines: the embedded provider-supervisor program is now
  a real lintable file (`scripts/provider_supervisor.py`) whose exact source the child still
  receives byte-identically; git-contract checks live in `cobbler_runtime/git_contract.py` on the
  canonical hardened `run_git`; provider credential/launch-auth hardening lives in
  `cobbler_runtime/provider_auth.py`. `full_run` re-exports every moved name, so import surfaces
  are unchanged.

### Thin Codex adapter and consistency-engine slimming

- AGENTS.md is now a true thin adapter (89 lines): every contract is a named pointer into SKILL.md
  or one authoritative reference, including the new commit-cadence/phase-role, worker failure
  recovery, packet-at-staging, worktree-lifecycle, and bounded-gates rules. The consistency engine
  covers it with one whole-file pointer corpus instead of 24 per-contract shims, drops ~70
  restatement pin entries, scopes the Cobbler section check to actual Cobbler content, and
  documents the pin-addition policy (a pin requires a normative sentence in more than one file).

### README restructure and glossary

- README.md is now a 372-line repository reference: install, safety model, failure-mode table,
  configuration, and a reference index that links each contract's single authoritative file
  instead of restating it. The task-first tutorial remains the published guide. New
  `references/glossary.md` defines every coined term once; new `references/operations-guide.md`
  holds the operational how-tos (sleep prevention, tmux, monitoring, notifications, SessionStart
  hook, daily briefing) moved verbatim from the README. Version narration now lives only in this
  changelog. Consistency pins updated to the linked-not-restated doctrine (22 README restatement
  pin-sets removed; forbidden-phrase guards retained).

### Hermetic, bounded gates and worker failure recovery

- `verify_repo.py` gate subprocesses run with closed stdin and hard per-step timeouts (suite step
  1800s); a timed-out step fails cleanly instead of hanging. The test suite redirects file
  descriptor 0 to devnull at discovery so every child a test spawns inherits closed stdin
  regardless of runner; `openrouter_lens.py` no longer reads a stdin envelope when the task is
  provided via flags. Worker failure recovery is codified in SKILL.md: transient provider errors
  resume with escalating backoff and never consume the substantive re-drive budget; workers keep
  an untracked progress ledger under `.elves/runtime/`.

### Consolidated git/secret/path helpers

- One canonical hardened `run_git` (leases) now serves audit, delegated-git, and all of
  `full_run.py` (16 raw subprocess call sites migrated with per-call env/cwd preserved); it closes
  stdin unconditionally and accepts an optional timeout. The weak duplicate `ensure_private_dir`
  was removed in favor of the fd-anchored storage variant; `.elves-session.json` is spelled once
  as `schema.ELVES_SESSION_BASENAME`; cycle-free function-local imports were hoisted and the two
  genuinely cyclic ones (risk_policy, behavior_policy) documented as such.

### Worker packet as a staging deliverable

- Staging now requires the standalone coordinator→implementer packet for delegable runs: SKILL.md's
  launch-ready checklist gains the conditional line, the survival-guide template Run Control gains a
  `Worker packet:` field, and `references/schema-and-acceptance.md` documents the optional
  `worker_packet_path` session key plus the canonical work-driver spelling map (hyphen/underscore
  equivalent; `devin-cli` covered).
- `acceptance_contract.py validate` emits an advisory `worker_packet_missing` warning — never a
  blocking issue or exit-code change — when a session records a non-host-native work driver without
  a recorded packet path.
- SKILL.md's handoff standard now states commit cadence and phase roles: at least one pushed
  non-Close progress slice before Close (first at first failing test or surface change), exactly one
  acceptance-backed Close per batch, driver reconciles under Review, batch labels contain only that
  batch's work. Echoed in the kickoff template and the Grok implementer launch prompt.

### Worktree reclaim lifecycle

- New `scripts/worktree_gc.py` (surfaced as `./scripts/preflight.sh --gc-worktrees`) reports and,
  with an explicit `--apply`, removes worktrees that are registered, linked, not the main worktree,
  not the invoking directory, clean including untracked files, fully merged into `origin/main`,
  and zero commits ahead of upstream. Removal is guarded: `git worktree remove` without `--force`,
  `git branch -d` never `-D`, and `git worktree prune` only after successful removals; report mode
  performs zero mutations. Unregistered `<repo>-*` sibling directories are listed as operator-owned
  and never deleted.
- Post-merge teardown is now part of the lifecycle docs: SKILL.md Final Completion and the Reviewed
  PR Landing Command tear down the run's own recorded worktree, staging records the created
  worktree path as `worktree_path` in `.elves-session.json`, and `config.json.example` gains
  `cleanup.worktrees: "on-merge" | "report" | "never"` (default `report`).

### Redaction hardening

- Exact-value redaction now draws environment secrets from one shared collector
  (`cobbler_runtime.context.collect_secret_env_values`) with a minimum exact-value length of 8.
  Short secret-named flag values (Claude Code sessions export `CLAUDE_CODE_SDK_HAS_OAUTH_REFRESH=1`)
  no longer register `"1"` as an exact secret, which corrupted gate JSON paths, timestamps, and
  version strings; secret-named values of 8+ characters still redact exactly, and pattern-based
  redaction is unchanged.

## [2.6.0] - 2026-07-16

### Open-source Grok Build worker

- Treat the installed Grok Build executable as launch authority: record a redacted capability
  ledger, use caller-generated `--session-id` identities plus exact resume, and identify
  unsupported `--new-session` without entering an invalid-flag or login loop.
- Keep private `HOME`/`GROK_HOME` isolation and the narrow `GROK_AUTH_PATH` OAuth projection;
  qualify the provider independently from behaviorally proven headless `/goal`, with a compatible
  one-packet fallback when goal enhancement is unavailable. Goal proof now requires a bounded,
  build-bound terminal-canary artifact rather than a free-form assertion.
- Select only authenticated live-catalog models and follow streaming JSON through bounded,
  sanitized progress, usage, terminal, and typed-error events, including credentials split across
  adjacent stream records.
- Native Codex and Claude Code routes stay commit-capable in linked worktrees through narrow Git
  metadata paths, stripped ambient Git credentials, and terminal feature-ancestry/protected-ref
  verification instead of granting the entire shared `.git` directory.
- Add the open-source worker path to the README, practical guide, setup recipes, launch prompt, and
  host-parity reference, with one detailed operational reference for capability checks, launch,
  follow, fallback, and recovery.

### Native-worker and landing hardening

- Fix current Claude Code streaming launches by adding the required `--verbose` flag. Supervised
  Claude workers now use safe mode with classifier-backed `auto` permissions so they can commit
  unattended; edit-only `acceptEdits` is no longer presented as commit-capable.
- Report a bounded, redacted stderr tail when a native worker exits nonzero before its first
  provider event, making launch grammar and authentication failures visible in ordinary status.
- Validate `run_id` and the exact `start_head` collision tripwire during staging, safely migrate an
  exact legacy tripwire during explicit sync, and cover symmetric batch and Master Acceptance row
  derivation for both stable-ID spellings without overwriting evidence.
- Document the committed-session landing check and cleanup order, plus quote-insensitive static
  asset sweeps followed by browser or preview verification.

## [2.5.0] - 2026-07-15

### User guide and GitHub Pages

- Add a task-first HTML guide for installing Elves, starting a run, choosing and watching a worker,
  reviewing the result, and choosing whether the driver may merge.
- Publish the guide from this repository at `https://aigorahub.github.io/elves/` with a
  dependency-free GitHub Pages workflow, and link it from the README.
- Align the end-to-end and durable documentation with the native-first worker flow while preserving
  equivalent Claude Code and Codex semantics.
- Apply a restrained, responsive, keyboard-usable design and a direct writing pass, followed by a
  critical Gemini 3.5 clarity review.

### Adaptive subscription-native workers

- Add one deterministic route decision for Codex and Claude Code: a separate subscription-native
  worker by default, with inherited model policy, plan-matched effort, provenance, advisory driver
  upgrades, and honest fallback.
- Add private atomic machine-global preferences at
  `${XDG_CONFIG_HOME:-~/.config}/elves/config.json`; management preserves safe unknown fields and
  rejects credentials, dangerous permission fields/values, relative XDG roots, and
  merge/destructive/protected-ref/approval-bypass authority.
- Correct native session grammar and exact identity capture: caller-assigned Claude UUIDs and
  Codex `thread.started.thread_id` resumed only through `codex exec resume <id>` from the registered
  worktree working directory.
- Probe optional Grok without inference. Repository vetoes remain absolute, remembered
  current-run/global Grok selection supplies consent, and advertised goal syntax remains distinct
  from behavioral verification.
- Add a supervised native-worker launch/status/follow lifecycle with private per-run structured
  logs, exact process/session/worktree binding, and an exact watcher command before driver parking.
- Avoid a fast-worker status race on macOS by distinguishing unavailable start metadata from an
  exited PID and briefly rereading terminal state before reporting that both processes were lost.
- Document that independent worker sessions may receive provider-managed cache hits, but Elves
  cannot transfer the live driver's prompt/KV cache or hidden model state.

## [2.4.0] - 2026-07-15

### Devin CLI worker adapter

- Add optional `devin-cli` implementation worker adapter pinned to `swe-1-7-lightning`.
- Support Devin CLI session creation, exact-session capture, and `--resume` recovery
  through the parked full-run lifecycle without changing Grok or host-native paths.
- Launch argv uses `--print` as the non-interactive transport; the Devin TUI is never
  started under full-run supervision.
- Add `--grant-devin-auth` to validate and project the host's canonical Devin CLI
  `config.json` and `credentials.toml` into the isolated worker `HOME` for both create
  and resume; missing/invalid/unsafe host auth fails before spawn.
- Session capture runs discovery with the exact isolated worker `HOME`/`XDG` paths,
  requires a single matching worktree session, and cross-checks the transport-authored
  ATIF export's `session_id` for fast-worker exits.
- Onboarding, setup recipes, and adapter registry now surface `devin-cli` as an
  optional route alongside Grok and OpenCode.
- Make repository CI select `Unreleased` for development commits and the exact
  skill version for clean release commits, preserving strict release-scoped API approvals.
- Compare release verification with the previous reachable release tag from `HEAD^`, explicitly
  excluding the current version tag so release follow-ups and post-tag runs retain the full release
  diff instead of allowing an empty or partial self-diff.

## [2.3.0] - 2026-07-14

### Joyful runs rewrite

- Compact canonical workflow in `SKILL.md`; `AGENTS.md` is a thin Codex adapter (not a second fork).
- Independent axes: `risk` low|standard|high and `trust_mode` trusted|untrusted (legacy four-tier
  labels remain compatibility aliases).
- Host-owned landing authority with exact-HEAD readiness; worker evidence cannot grant merge.
- Complete-without-merge and complete-and-merge share one readiness pipeline; active-run `/land-pr`
  grants driver authorization without restarting readiness.
- Default sanitized non-model follow stream on `full-run-await` (`--quiet` opt-out).
- Impact-path proof selection, evidence input digests, convergent cumulative + delta re-review.
- Focused references: joyful-runs-contract, landing-authority, follow-mode, proof-and-review,
  host-parity, schema-and-acceptance; temporary migration ledger for 2.2→2.3.
- Safety kernel preserved with destinations and proving tests in `canonical_contract.py`.

## [2.2.0] - 2026-07-13

### Faster trusted Grok full-runs

- Risk-tiered execution policy with a thin safety kernel and four tiers
  (trivial/docs, standard trusted, high-risk trusted, untrusted).
- Proof budget: validate once, verify changes, attest final — touched-surface
  per batch; broad proof at risk checkpoints and terminal readiness.
- Removed equal-thirds time quotas and fixed-cadence entropy reviews: trusted workers keep moving,
  intermediate process polish is advisory, and the host spends deep-review effort once at terminal.
- Host-native/legacy mid-run PR feedback is one nonblocking new/unresolved fetch; trusted parked
  worker pushes trigger no host PR polling, and terminal readiness reads/waits once.
- Bug-category expansion blocks only confirmed same-root failures on owned or
  affected shared surfaces; unrelated siblings are advisory.
- Capability-detected native Grok goal with honest headless-compatible fallback.
- Blocking `full-run-await` / monitor `--wait` until material transition.
- Incremental healthy monitor polls (skip deep remote all-ref audit and deep Git
  reconciliation); full safety kernel at terminal/safety wakes.
- Clean exit without a valid machine report wakes `driver_wake_reconcile` with
  `provenance: host_reconstructed` reconstruction constraints; `full-run-reconcile` exposes the
  host-owned recovery path instead of rejecting otherwise verifiable trusted work.
- Gate evidence keyed by product/test input digest (docs-only commits may reuse);
  cleanup-only tip attestation reuses live broad proof when safe.
- Phase model + reasoning-effort routing with requested/actual/fallback recording.
- Optional Grok image/video capabilities with graceful unavailable-tier fallback.
- GitHub Actions concurrency cancellation for superseded workflow runs.
- Parallel unittest remains deferred pending sequential parity evidence.

## [2.1.1] - 2026-07-13

### Acceptance contract compatibility and staging diagnostics

- Treat `B0` and `B1` as equally valid batch-numbering starts, without reserving or preferring
  either convention; batch-taking helpers normalize equivalent integer and stable-id forms.
- Accept bare `- [ ] B0-A1: criterion` and bracketed `- [ ] [B0-A1] criterion` stable-id rows as
  equivalent plan syntax, with targeted diagnostics for malformed rows.
- Validate plan, session, and full-run packet acceptance mappings during staging so missing,
  duplicate, unrelated, or text-mismatched criteria—and missing or extra session batches—block
  before worker launch rather than failing late; `acceptance_contract.py` provides read-only
  validation plus explicit proof-preserving session sync.
- Require production full-run state to bind the canonical plan/session contract to the exact packet
  and revalidate it before launch or reconciliation; legacy unbound production state fails closed.
- Reject ambiguous/oversized batch IDs, duplicate session JSON keys, explicit empty legacy or stable
  Batch/Master Acceptance sections, and malformed proof containers without erasing existing
  evidence. Final evidence remains a separate `elves_landing_check.py` gate after staging validation.

## [2.1.0] - 2026-07-13

### Trusted full-run delegation (major stabilization)

Elves **2.1.0** ships a real delegated full-run mode: after Claude Code or Codex stages a trusted
Grok Build run, one persistent worker owns feature-branch implementation, tests, commits, pushes,
and structured progress while the driver parks on bounded events. Host-native remains the default;
Grok Build stays optional and explicit.

### Runtime, install, and adapter truth

- Recursive shipment of `scripts/cobbler_runtime/` plus `openrouter_lens.py` into installed bundles
- Fresh Claude Code and Codex installed-bundle smokes from outside the source tree
- Built-in adapter registry preserves Gemini/Antigravity/OpenCode identities and contracts
- Python 3.10 local-model TOML support through the bundled strict compatibility parser
- Canonical `scripts/verify_repo.py` gate; CI triggers on `scripts/**`
- Exactly seven managed Claude aliases; Codex installs no Claude alias tree

### Parity, isolation, and security

- Structured behavior policy and full-run supervisor (prepare/launch/monitor/logs/stop)
- Versioned full-run event/report v1 contract, exact-session/branch validation, and cumulative
  terminal review while the Claude Code or Codex driver remains quietly parked: unchanged health is
  silent and nonterminal updates are host-coalesced
- Digest-keyed private session/lease storage, locks, write qualification fail-closed
- Disposable tracked-source isolation, minimal implement env grants, generation-bound signaling,
  pre-snapshot/pre-spawn fallback or blocking for hard external routes on Linux and Darwin where
  the runtime cannot acquire recursive authority atomically, plus fail-closed legacy bounded
  `--exec` where recursive absence cannot be proven
- Explicit headless Grok authentication: named `XAI_API_KEY` grants or trusted-Lane-A
  `--grant-grok-auth`, which combines isolated per-run Grok state with one validated canonical
  owner-private OAuth file through native `GROK_AUTH_PATH`, preserving rotating refresh tokens;
  the exact native Mach-O/ELF Grok artifact and its safe ancestor chain are probed credential-free
  and bound through spawn, while full-ancestor owner/mode/link/ACL validation fails closed
- Explicit GitHub HTTPS branch-push authentication through either `--grant-github-push` or one
  named `GH_TOKEN`/`GITHUB_TOKEN` grant; the isolated worker receives one reset, launch-scoped Git
  credential helper while raw credentials, host Git config, HOME/XDG state, and SSH agents remain
  outside persisted/public state; explicit host author/committer identity is projected and missing
  identity fails before Git can guess
- Packet-bound `high_risk_checkpoint` events and exact host acknowledgements gate both active runs
  and completed-provider final readiness, so omitted or emit-and-complete checkpoint races fail
  closed
- Export only from `AUDITED_PASS`, with bound Git config/ref/index/object authority, sealed
  per-commit patch transport digests, and post-audit refs/remotes/config/hooks revalidation;
  public `worker import` descriptor-reads the retained bundle, proves its final tree in a disposable
  checkout, and applies those same bytes to the clean host before host-owned validation,
  commit, and push, while exact prepare/audit HMACs protect named credential grants
- Delegated feature-branch Git contract with a narrow verified descendant-progress collision
  exception; host-owned `bN` refs for bounded routes and one `b0` launch ref plus worker commit SHAs
  for trusted parked full-run rollback
- One-to-one plan acceptance IDs with Master Acceptance evidence

### Evidence-aware validation and architecture

- Attempt path decomposed into transport/artifact/result helpers
- Preflight evidence reuse keyed by HEAD/config; final readiness never cache-only
- Evidence-aware focused review selection with high-risk escalation
- Public-API snapshot compatibility gate with cycle-safe literal-helper exit resolution and a
  tracked, release-scoped approval manifest for intentional contract changes; CI path filters
  include that approval manifest on both pull requests and pushes to `main`

### Documentation and release

- Host-honest Claude/Codex invocation, full-run Run Control fields, corrected test-integrity and
  rollback guidance, progressive README disclosure, v2.1.0 metadata

## [2.0.0] - 2026-07-12

### Efficient multi-model workflows under Cobbler (major)

**Elves 2.0** is about **efficient, intelligent workflows for agentic development and research** —
not loyalty to a single vendor stack. The default coordinator (**Cobbler**) routes plan, implement,
review, and math-domain work across agents and models when that helps, while **vanilla Cobbler is
host-native** (Claude Code or Codex out of the box). Optional tools never block an ordinary
overnight run. Multi-model support exists so people are **not locked into one ecosystem**; the
product is still the loop (plan → batches → gates → review → memory), not a model catalog.

This is a major product release (orchestration surface + multi-agent tooling), not only a docs
pass. Host-native runs stay fully valid without any external provider.

| Layer | What landed (summary) |
| --- | --- |
| **Main drivers** | Claude Code / Codex only as supported Elves skill hosts (orchestrators) |
| **Onboarding** | `onboard plan\|show\|apply\|probe`, partial apply merge, apply-blocked bare tokens, relative probe paths |
| **Plan/review lenses** | OpenRouter lens + presets; Gemini CLI / Antigravity headless adapters; Muse Spark docs |
| **Work drivers** | Grok Build Lane A (`implement …`); OpenCode plan/labor adapter (`--file` packets) |
| **Math domain** | Google **AlphaEvolve** as optional `evolutionary_search` (runner + local evaluator; not a proof engine) |
| **Honesty** | Exotic main/work paths lightly tested; prefer PRs; exact session ids over `latest`/`continue` |

Canonical maps: [`references/model-onboarding.md`](references/model-onboarding.md),
[`references/cobbler-setup-recipes.md`](references/cobbler-setup-recipes.md),
[`references/math-alphaevolve.md`](references/math-alphaevolve.md).

### E2E chat-to-work / chat-to-land (recommended single kickoff)

- **Default user path:** one kickoff after conceptual agreement (optional multi-planner) —
  plan + stage + batch loop → landable PR (**chat-to-work**) or through reviewed-PR merge
  (**chat-to-land**). Fixes the old failure mode where users never staged properly.
- Agent still stages before coding; does not wait for a second human call once launch-ready.
- Labor completeness: main driver re-drives lazy work drivers (e.g. partial Grok Build turns).
- Optional `/goal` (Codex) as continuation seatbelt. Docs:
  [`references/e2e-chat-to-land.md`](references/e2e-chat-to-land.md),
  [`references/kickoff-prompt-template.md`](references/kickoff-prompt-template.md).

### Grok implement: aliases, --check, humanized failures (community credit)

- Lane A `implement prepare|launch|resume-batch` accepts Grok model aliases **`fast`** /
  **`deep`** and optional **`--check`** / **`--effort`**. Failed `--exec` surfaces short
  `error_human` messages for common CLI dumps (auth, tool-config, rate limit).
- Documented Grok Build ~0.2.93 **denylist vs allowlist** guidance for read-only/media-style
  invocations in `references/grok-implementer-launch-prompt.md`.
- Future backlog (structured review schema, review packet builder, concurrent job status, etc.):
  [`references/community-grok-plugin-ideas.md`](references/community-grok-plugin-ideas.md).
- **Credit:** patterns adapted from [stdevMac/grok-in-claude](https://github.com/stdevMac/grok-in-claude)
  and [stdevMac/grok-in-codex](https://github.com/stdevMac/grok-in-codex) (Apache-2.0). Elves does
  not vendor those plugins; host-owned leases and run memory remain Elves-native.

### Docs: native-first implement framing

- Clarified that **vanilla Cobbler is host-native** (Claude Code or Codex out of the box). Grok
  Build, multi-provider plan/review, and the stricter host-import writer lease are **optional
  upgrades** when those tools exist — same pattern as the math module’s optional providers.
- Kept operator CLIs (`implement …`, `worker …`) and `implementation_lane: fast | untrusted` as
  opt-in surfaces; they are not the default overnight path.

### Docs: Muse Spark and OpenRouter as optional planner/reviewer routes

- Documented optional multi-model **plan/review** lanes after the production math-run pattern
  (thin CLI wrappers, named presets, panel orchestration):
  - **OpenRouter:** `OPENROUTER_API_KEY` + any `provider/model-id` via named `or-…` presets
  - **Meta Muse Spark 1.1:** `META_API_KEY` / `MODEL_API_KEY`, catalog id **`muse-spark-1.1`**,
    preset e.g. `meta-muse-spark11`, Responses API at `api.meta.ai`
- Independent read-only evidence only; native fallback if key/wrapper missing; never sole
  authority. Recipes in `references/cobbler-setup-recipes.md` and
  `references/council-provider-config.md`.

### Docs: Google AlphaEvolve in the math module

- Added optional math role `evolutionary_search` and
  [`references/math-alphaevolve.md`](references/math-alphaevolve.md) for Google Cloud AlphaEvolve:
  managed program mutation + **deterministic local evaluator** for high-quality examples and
  counterexample *signals* (not proofs).
- Pattern from production math runs: gcloud impersonation (no long-lived keys), sandbox candidates,
  independent local replay before promotion, artifacts under `alphaevolve_runs/`.
- Wired into math workflow, provider config, plan/survival templates, ledgers, review prompts, and
  setup recipes. Still optional; missing AlphaEvolve never blocks native Discovery Sprint.

### Model onboarding (Claude Code + Codex)

- Host-mediated **purpose → route** interview with CLI support:
  `python3 scripts/cobbler_agents.py onboard plan|show|apply|probe`.
- Users choose (and later update) which tools handle planning, implement, review, scout, etc.;
  defaults stay **host-native**.
- Structural **probe** verifies PATH/`--help` and env **names** (OpenRouter/Meta/AlphaEvolve hints);
  live smoke remains opt-in and never prints secrets.
- Protocol: [`references/model-onboarding.md`](references/model-onboarding.md); wired into
  `/setup-cobbler`, skill surfaces, and setup recipes for both Claude Code and Codex.
- **Within-family tiers:** `claude-code-planning` / `claude-code-labor` and
  `codex-fugu-planning` / `codex-fugu-labor` so plan/review can use a high-quality model and
  implement can use a labor model (pin `requested_model` locally).
- **Google subscription CLIs:** `gemini-cli` and `antigravity-cli` as optional **plan/review/scout**
  routes (usually not cost-effective for bulk implement). **Supported main drivers remain Claude
  Code and Codex only**; other tools are optional lenses, not claimed Elves hosts. Exotic
  interfaces (Antigravity included) are **not heavily tested** — no maintainer dogfood without
  the right subscription. Prefer PRs (or issues) when something breaks.
- **Onboard correctness (pre-merge review fixes):**
  - Partial `onboard apply` / `setup` **merges** into existing models.toml roles (use
    `--reset-roles` to wipe unspecified roles back to host-native).
  - Bare `openrouter` / `meta-muse` / `alphaevolve` tokens are **apply-blocked**; configure a
    custom-cli wrapper (or math Survival Guide for AlphaEvolve). No placeholder `my-coding-agent`.
  - `--required` resolves tier profiles to underlying adapters (e.g. `claude-code-planning` →
    `claude-code`).
  - Probe reads `[profiles.*].executable` (custom wrappers, antigravity `agy` fallback).
  - Probe resolves **relative** recipe/profile executables (e.g. `scripts/openrouter_lens.py`)
    against the repo root so `onboard probe` matches adapter dispatch when cwd ≠ checkout.
  - Env **name** presence also scans ignored `.env.local` (values never returned).
  - Plan/review-only profiles on implement emit a warning; corrupt models.toml surfaces warnings
    instead of silent host-native pass.
- **Google CLI adapter support (dogfood):**
  - `gemini-cli` / `antigravity-cli` headless builders use `-p`/`--print` (not bare stdin), Gemini
    `--skip-trust` + plan approval, Antigravity `--mode plan`.
  - Prefer **current** Gemini models (dogfood: 3.1 Pro plan/review, 3.5 Flash optional labor);
    pin via `requested_model` in ignored models.toml — re-check `agy models` after upgrades.
  - Experimental `antigravity-labor` profile for Flash-class implement; **not** Lane A / Grok
    `implement prepare|launch`, not write-lease qualified.
  - **Exact session continuity (preferred, most robust):** `session_id` on readonly invocations and
    session create/resume for Gemini (`--session-id` / `--resume <uuid>`) and Antigravity
    (`--conversation <id>`); reject ambiguous latest/continue. Plan→review should resume the same
    chat when possible.
  - **No session id (fallback):** repo documents the agent can read (plan, contract, execution log,
    Survival Guide, constitution) — never invent `latest`/`continue`.
  - Review protocol: completeness (plan+contract), constitution deal-breakers, and regressions
    (indirect breakage), not only local correctness of the diff.
- **OpenRouter plan/review lens:** `scripts/openrouter_lens.py` + apply-ready profiles
  `openrouter-lens`, `or-qwen-max`, `or-glm` (custom-cli). Exact `--session-id` for plan→review
  continuity; context files / packet when no session. Bare `openrouter` remains apply-blocked.
  Pin current OpenRouter model slugs locally (examples: `qwen/qwen3-max`, `z-ai/glm-5`).
- **OpenCode implement/plan adapter:** `opencode-cli` / `opencode-labor` for the OpenCode terminal
  agent (Claude Code–like; OpenRouter + 75+ providers). Headless `opencode run` with exact
  `--session`; labor uses `--auto`. `implement prepare --adapter opencode-cli` alongside Grok.
  Framed as **work driver (laborer)** under a **main driver** Claude Code/Codex orchestrator
  (not Elves skill host). Example: OpenCode + OpenRouter GLM for batch coding.
- **Exotic honesty:** OpenCode/Antigravity as main driver may or may not work (untested / not a
  design focus). Work-driver matrices (OpenCode, Antigravity, Gemini CLI, OpenRouter, …) are
  incomplete coverage. Prefer PRs/tests to harden community paths.

## [1.20.2] - 2026-07-12

### Optional external batch implementer

- Documented optional `implementation_lane: fast | untrusted` on skill surfaces (`SKILL.md`,
  `AGENTS.md`) for when an external implement CLI (e.g. Grok Build) is available.
- Operator CLI: `python3 scripts/cobbler_agents.py implement prepare|launch|gate|resume-batch|status`.
- Launch recipe: `references/grok-implementer-launch-prompt.md`. Host-import `worker` lease remains
  advanced and is not the default overnight path.

## [1.20.1] - 2026-07-12

### Cobbler runtime truthfulness and safety

- Effective routes preserve executable, model, argv contracts, required policy, and ordered
  fallbacks; canned host-native reports cannot satisfy quorum without injected host evidence.
- Adapter builders use version-aware Claude/Grok/Codex flags with fixture-backed help probes.
- Process-group cancellation reaps descendants; run IDs are collision-resistant; named credentials
  are scoped and redacted from artifacts.
- Session rehydration freezes active digests until exact resume proves the pending packet; registry
  writes are atomic and malformed records fail closed.
- Writer path allowlists no longer use unsafe `lstrip("./")`; empty allowlists fail closed; lease
  lifecycle includes `audited_pass` and `apply_checked`; audits prefer common-dir config/hooks.
- Setup smoke is true only after a real smoke executor model response; dry-run writes nothing.

## [1.20.0] - 2026-07-12

### Cobbler external-agent orchestration

- Added standard-library `scripts/cobbler_agents.py` runtime for provider-neutral role routes,
  config resolution (Survival Guide → local `.elves/models.toml` → user config → native),
  parallel read-only council dispatch, exact sessions, single external writer lease/audit, and setup.
- Coordinator-to-implementer handoff standard and operator-visible git progress commits are pinned
  across `SKILL.md`, `AGENTS.md`, templates, and consistency checks.
- External writers may create only audited detached commits; host imports binary patches and owns
  branch commits, pushes, PRs, run memory, validation, and acceptance.
- Setup inventory/non-interactive flags, Claude `/setup-cobbler` + `/setup-council` aliases, Codex
  natural/`$elves` setup wording, and custom harness recipes (OpenRouter/API-only/wrappers).
- Master launch prompt: `references/councilelves-launch-prompt.md`.
- Native-only defaults remain complete with zero external tools or provider keys.

## [1.19.0] - 2026-07-08

### Acceptance evidence and landing hardening

Frontier models often treat the Completion Contract as spirit. Smaller or less disciplined models
treat it as a checklist they can satisfy with the easiest green signals: CI passed, a structure
test exists, session JSON says `complete`. That gap is how a PR can look landable while plan
Acceptance (LOC cuts, facades, real splits) is still open.

- **Policy:** Green CI + `status: complete` is not landable; landable is plan Acceptance with proof.
- Required per-batch `acceptance: [{criterion, met, evidence}]` on `.elves-session.json` before
  `status: complete` (Completion Contract, Structured Session Data, Document step) on both Claude
  (`SKILL.md`) and Codex (`AGENTS.md`) surfaces.
- **God-file rule:** structure/regex/characterization locks may lock behavior but must not alone
  complete a split batch unless plan Acceptance explicitly allows characterization-only.
- Prefer **one batch per close commit**; multi-batch closes require separate **Validate:** sections
  per batch id in the execution log (stops "close remaining" commits from laundering unfinished work).
- Added `scripts/elves_landing_check.py` as a pre-land / Final Readiness check (session acceptance,
  plan Acceptance checkboxes, multi-batch close detection, optional evidence-dir layout). Shipped in
  the installable skill bundle for Claude and Codex.
- Survival guide template: Acceptance Checks expanded; new Evidence / SCRATCH layout section.
- Plan and execution-log templates: measurable split/god-file Acceptance and per-batch Validate proof.
- Readiness Gate and Final Readiness Review require landing-check-clean acceptance evidence.
- README documents why these guards exist and how to run the landing check.

## [1.18.0] - 2026-06-16

- Made Cobbler's role as the default Elves coordinator explicit across runtime docs, README,
  templates, config examples, and durable `.ai-docs/*` notes.
- Added durable run-level Cobbler session state guidance: staged and active Elves runs record
  `## Cobbler Session State` and `.elves-session.json` `cobbler.default_for_session` so compaction
  preserves the Cobbler-first posture.
- Reframed math as the first Cobbler-managed domain workflow while preserving Discovery Sprint,
  scout lanes, claim lifecycle, source audit, adversarial proof review, artifact ledgers, and human
  verification.
- Changed math provider defaults to native-first with optional external role routes. OpenRouter
  remains a useful optional math role preset, but `OPENROUTER_API_KEY` is no longer required by
  default in config examples.
- Added repo consistency and structured config checks for Cobbler domain workflow hierarchy,
  provider-optional math defaults, and run-level Cobbler session state.
- Added the release checklist to the repo consistency CI workflow.

## [1.17.0] - 2026-06-15

- Expanded Cobbler from council-style synthesis into an explicit harness loop: capability scan,
  route and medium selection, context packet, agents/tools/skills, evidence assembly, fitted answer,
  present/record, and reclassification when new facts change the route.
- Updated Cobbler docs to describe one-off Cobbler, Cobbler inside an Elves run, and Cobbler Mode
  in plainer user-facing terms while keeping provider-backed model routing optional.
- Added Cobbler harness drift checks so the docs keep the source-inspired orchestration loop intact
  without importing model persona, provider dependency, policy text, or safety framing.

## [1.16.0] - 2026-06-15

- Made Cobbler-first coordination the default Elves run model: Run Cobbler now frames planning,
  contract, risk, debugging, review, and synthesis decisions, while Quick Cobbler remains the
  read-only one-off answer mode.
- Added Cobbler Mode as a thread-local convention: `/cobbler-mode` in Claude Code and
  `$elves cobbler-mode` in Codex keep follow-up prompts Cobbler-mediated without creating durable
  run state or requiring provider-backed council.
- Added `scripts/release_checklist.py`, a read-only maintainer helper for release sweeps covering
  version alignment, changelog promotion, current-version examples, and changed human-facing docs.
- Added tests, README usage notes, TODO closure, and CI compilation coverage for the release
  checklist helper.
- Added `scripts/pr_portfolio_report.py`, a read-only repo helper for summarizing PR stack health
  across merge state, pending/failing checks, and unresolved review threads.
- Added `--fail-on-draft` to the PR portfolio helper so operators can compose
  `--fail-on-attention --fail-on-draft` as a landing-readiness gate without treating intentional
  drafts as attention-worthy.
- Cleaned up integration-preview status wording across follow-up plan docs, the context index, and
  preflight branch-ahead messaging so shipped helpers are not described as absent future work.
- Changed the release checklist summary to say `completed with warnings` when warning-only
  development checks pass with advisory follow-ups.
- Made the `tests/` directory importable so plain `python3 -m unittest discover` finds the helper
  regression suite instead of reporting zero tests.
- Added a repo-only `scripts/workspace_guard.py` prototype that checks candidate write commands
  against `.elves-session.json` owned-tip state, with advisory defaults, strict-mode blocking, and
  explicit local/remote tip update commands.
- Clarified Codex installation and sync guidance so users see, at the setup point, that Codex
  installs the main skill bundle and invokes Cobbler with `$elves cobbler: ...` or natural language
  rather than Claude Code slash aliases.
- Documented that new persistent Cobbler preferences belong under top-level `cobbler`, while legacy
  `council` config remains for compatibility and loses precedence when both are present.
- Included `config.json.example` in the managed Claude/Codex skill bundle so installed copies have
  the persistent-preferences template the docs reference.
- Added `.ai-docs/context-index.md`, a durable pre-implementation survey map for repo surfaces,
  scripts, tests, common edit paths, and validation baselines.
- Expanded the repo consistency checker to phrase-pin operator-facing docs, including durable
  `.ai-docs/*` guidance, the overnight run report issue template, and kickoff run-control fields.
- Updated the repo consistency workflow so issue template changes trigger the checker.
- `scripts/preflight.sh` now includes a Workspace Ownership check that inspects
  `git worktree list --porcelain`, hard-fails when the current branch is checked out in more than
  one worktree, and prints the branch-tip collision tripwire when the checkout is uniquely owned.
- Added `scripts/preflight_worktree.py` and `./scripts/preflight.sh --create-worktree <branch>` so
  staging can create or dry-run a dedicated worktree with explicit base-ref, path, branch collision,
  and tripwire output while the default preflight checklist remains advisory and non-mutating.
- Cobbler provider-backed council docs now include native-first role model routing: roles default to
  host subagents, optional `provider:model-id` routes can be configured when keys exist, unavailable
  routes fall back to native, and dissent is resolved by evidence rather than model prestige.
- Added optional full-run `model-routing` guardrails for implementation, validation, review,
  scouting, and synthesis phases. The guidance is native-first, provider-optional, and records
  requested route, actual route, and fallback reason only when material.
- Added guardrails for optional public API surface snapshots: survival-guide/config examples,
  regression-attestation and review guidance, ignored `.elves/api-surface/` artifacts, and repo
  consistency checks. Snapshots stay advisory by default and are evidence, not authority.

## [1.15.0] - 2026-06-14

### Cobbler

- Added Cobbler as the user-facing coordinator inside Elves: ask once, and Cobbler decides whether
  to answer directly, bring in specialist elves, or convene a read-only council of independent
  lenses.
- Made `/cobbler` the primary Claude Code entry point and `$elves cobbler: ...` the reliable Codex
  invocation while preserving `/council`, `/ec`, `/elves-council`, and `$elves council: ...` as
  compatibility aliases.
- Clarified that Quick Cobbler is native-subagent-first, read-only, and stateless by default:
  Codex should use Codex subagents, Claude Code should use Claude Code subagents, and environments
  without subagents should perform the same read-only lens analysis directly.
- Reframed external model diversity as optional provider-backed council configuration. Ordinary
  Cobbler and Council-compatible use requires no OpenRouter or other provider key.
- Synchronized the Cobbler hierarchy across `SKILL.md`, `AGENTS.md`, README, changelog, reference
  templates, config examples, managed Claude Code alias skills, and repo consistency checks.

## [1.14.0] - 2026-06-14

### Elves Council

- Added the Elves Council concept: `/council`, `/ec`, and `/elves-council` are documented as
  chat-native aliases for a fast, read-only Quick Council that gathers independent native-subagent
  lenses and returns one synthesized recommendation with visible dissent.
- Clarified that Quick Council is native-subagent-first, read-only, and stateless by default. Codex
  should use Codex subagents, Claude Code should use Claude Code subagents, and environments without
  subagents should perform the same read-only analysis directly.
- Reserved Deep Council as an optional external-provider mode for broader model diversity without
  requiring OpenRouter or any provider key for normal `/council` use.
- Synchronized the release skeleton across `SKILL.md`, `AGENTS.md`, README, and changelog while
  avoiding imported vendor identity, persona, policy, or safety framing.

## [1.13.0] - 2026-06-02

### Reviewed PR landing command

- Added an explicit Reviewed PR Landing Command for the common instruction: get a subagent to
  review the diff from main, read every PR review surface, address actionable findings, run the
  tests that make sense, and land with a merge commit once everything is green.
- Added `\land-pr` and `/land-pr` as shorthand aliases for the Reviewed PR Landing Command.
- Clarified that this one-off command is an explicit merge opt-in for the current PR while the
  normal Elves default remains unchanged: the human merges unless merge-on-green is explicitly set.
- Synchronized the command across Claude-compatible `SKILL.md`, Codex `AGENTS.md`, README, review
  guidance, kickoff and survival-guide templates, and the repo consistency checker, including alias
  coverage so the shorthand remains present across user-facing docs.

## [1.12.0] - 2026-06-01

### Math research workflow kit

- Added the beta math module as an optional Elves workflow for preliminary research, proof search,
  source audit, paper drafting, and post-draft review.
- The module is a portable public version of a fuller Aigora workflow: prompts, ledgers, provider
  roles, and review loops that can run with standard tools.
- For uncertain mathematical goals, the module starts with a Discovery Sprint: independent scouts across
  relevant and adjacent subfields look for solved related problems, transferable techniques, natural
  assumptions, and plausible quick wins before theorem drafting begins.
- Provider guidance is OpenRouter-first, with optional native Gemini, Claude, xAI, OpenAI, Exa, and
  local tools configured by role rather than hardcoded model names.
- The docs distinguish model-generated ideas, checks, and draft prose from human-verified
  mathematical claims.

## [1.11.0] - 2026-05-31

### Run isolation, sharper continuation, and a stronger closeout

- **Concurrent-run isolation (new).** One run now owns one branch and one checkout. The skill adds a
  hard rule against sharing a working tree or branch with another active agent, a strong default to
  stage in a dedicated `git worktree` (`git worktree add -b <branch> ../<repo>-<branch>`) when agents
  may share a repo, and a collision tripwire: the agent records the branch tip at staging and stops
  if HEAD or the remote moves to a commit it didn't create. Added to Preflight, Stage the Run,
  Forbidden Commands, Merge Conflicts, Hard Stops, the survival-guide Run Control / Launch Readiness /
  Non-Negotiables / Rollback sections, the kickoff template, and README. Motivated by a real
  Claude-and-Codex collision in one shared checkout.
- **Sharper continuation language.** The Forbidden Stop Reasons and Pre-Final Guard now name the
  specific rationalizations agents stop on ("the remaining work feels like a lot for one turn" and
  "this feels like a natural place to check in") and reframe the volume of remaining work as the
  reason the run exists, not a reason to stop.
- **Two-stage lifecycle made explicit.** SKILL.md, AGENTS.md, and README now state up front that a
  run is two separate calls: first you **stage**, then you **start**. The kickoff template's
  stage/launch split is reinforced.
- **Stronger closeout.** The Final Readiness Review is now the mandatory last step of every finite
  run: review `git diff <default-branch>...HEAD`, read every PR comment, run every test that makes
  sense, confirm the branch is green, then hand the user the Elves Report and tell them to review it.
- **Merge-policy opt-in.** Default is unchanged: the user merges; the agent never merges and never
  squashes. New: the user may set a `merge-on-green` preference in Run Control, in which case the
  agent lands a regular merge commit (never a squash) after the Final Readiness Review passes.

## [1.10.1] - 2026-05-09

### Human-facing Elves Reports

- **Elves Report protocol added.** Substantial finite Elves runs now generate a temporary static
  HTML worker-to-manager report before handoff, summarizing status, problems found, lessons learned,
  collapsible batch timeline, validation/review proof, residual risks, human next steps, and source
  links.
- **Final Completion updated.** Both Claude-compatible `SKILL.md` and Codex `AGENTS.md` now insert
  Elves Report generation after the Final Readiness Review and before operational-artifact cleanup,
  with instructions to refresh the report if cleanup, final review fixes, CI, or PR state changes.
- **Templates updated.** The survival guide template now includes an Elves Report configuration,
  and the execution-log template records the latest report path plus problems found, lessons learned,
  and human next steps in the Session Summary.
- **Reusable HTML template added.** `references/elves-report-template.html` gives workers a
  polished, collapsible-batch starting point for manager-facing reports.
- **README updated.** User-facing docs now explain Elves Reports and why HTML/Markdown is the
  default for precise accountability while generated image infographics remain opt-in.
- **Proof-of-concept HTML added.** `docs/elves-report-proof-of-concept.html` shows what a committed
  report-style page can look like when opened locally or served through GitHub Pages.
- **Committed examples sanitized.** Public proof-of-concept content now uses non-identifying sample
  batches, and runtime guidance keeps reusable templates/examples free of private project names.
- **Consistency checker extended.** `scripts/check_repo_consistency.py` now verifies Elves Report
  guidance across the Claude, Codex, README, survival-guide, and execution-log surfaces.

## [1.9.0] - 2026-05-03

### Final cleanup and memory performance

- **Final readiness review added.** Before finite-mode handoff, Elves now runs a fresh cumulative
  review of `git diff <default-branch>...HEAD`, the branch commit history, execution log, PR
  comments, check runs, docs, and memory hygiene. Supported platforms should use a review subagent;
  others perform the same review directly, then fix and repeat until clean.
- **Strategic forgetting added.** Runtime docs now distinguish execution chats, handoff docs,
  archives, and durable memory so long runs leave a clean memory workspace instead of a bloated
  active thread.
- **Long-run hygiene added to entropy checks.** Elves now checks for oversized logs, stale live
  survival-guide state, superseded lessons, idle resources, and visible memory pressure during
  long runs, not only at final completion.
- **Safe local app maintenance documented.** The autonomy guide now describes inspect-first,
  backup-first, archive-first cleanup for Codex/Claude application state, with explicit warnings
  not to mutate active app databases during a coding run.
- **Codex Goals launch guidance added.** The README, kickoff template, and new
  `references/codex-goals.md` explain how to use `/goal` as an optional Codex continuation
  backend while Elves remains responsible for the Stop Gate, review loop, memory hygiene, and
  Readiness Gate.

## [1.8.0] - 2026-04-14

### Run control hardening

- **Checkpoint semantics are now explicit.** Elves now distinguishes between a delivery checkpoint
  and a true stop boundary, so "have results by 8am, then keep going" is modeled as open-ended
  mode with a checkpoint instead of a silent deadline stop.
- **Latest controlling instruction wins.** The skill and references now require the survival guide
  to rewrite `## Run Control` immediately when the user changes stop behavior mid-run.
- **Post-push operator checklist added.** After every push, the agent must re-read the survival
  guide, confirm the single next action, inspect active compute/resources, reconcile any idle or
  ambiguous paid work, and confirm whether stopping is actually allowed.
- **Survival guide template upgraded.** The template now includes checkpoint fields, an `Active
  Compute` section, and a dedicated post-checkpoint control loop, reinforcing that the survival
  guide is a live operator brief rather than an append-only history log.
- **Open-ended and autonomy references expanded.** `references/open-ended-guide.md` and
  `references/autonomy-guide.md` now cover checkpointed open-ended runs, mid-run stop-policy
  changes, and compute-status check-ins more explicitly.
- **README clarified the operating model.** User-facing docs now explain checkpointed open-ended
  runs and encourage rewriting the survival guide in place instead of stacking stale "next action"
  updates.
- **Templates and durable docs synced.** The kickoff prompt, execution-log template, overnight run
  report, repo learnings, and `.ai-docs/*` surfaces now mirror the same checkpoint, stop-policy,
  and active-compute model instead of leaving that knowledge trapped in the main skill files.

### Follow-up hardening

- **Stop permission is now explicit.** The survival guide adds a dedicated `Stop Gate`, the repo
  records `.elves-session.json` `continuation_guard` state, and both Claude Code and Codex runtime
  docs now treat stopping as positive permission instead of a judgment call.
- **Staging gets an advisory survival-guide validator.** `scripts/validate_survival_guide.py` plus
  a warning-only preflight hook can catch half-filled `Run Control`, `Stop Gate`, and recovery
  fields before the user goes offline, without blocking launch automatically.
- **Long runs now enforce sustained effort.** The survival guide, launch prompt, and runtime docs
  now explicitly tell the model not to be lazy, to work as hard as it can for the entire run, and
  to avoid coasting after the first green check or useful checkpoint.

## [1.7.0] - 2026-04-11

### Durable memory and AI-friendly docs

- **Learnings is now a first-class memory surface.** Elves formally distinguishes plan, survival
  guide, learnings, and execution log, with `learnings.md` acting as durable reusable memory across
  runs instead of forcing every lesson to live in chronological batch notes.
- **Lightweight `.ai-docs/` architecture added.** The repo now includes `.ai-docs/manifest.md`,
  `.ai-docs/architecture.md`, `.ai-docs/conventions.md`, and `.ai-docs/gotchas.md` as the curated
  durable layer for stable repo truths.
- **Promotion flow is explicit.** The documentation system now defines `execution log -> learnings
  -> .ai-docs`, which keeps transient status, reusable lessons, and stable architecture knowledge
  in separate places.

### Docs in the loop

- **Documentation freshness is part of done.** Batches now track docs impacted, updated, promoted,
  and deferred instead of treating docs as end-of-run cleanup.
- **`PENDING-DOCS` added to review vocabulary.** Elves can now distinguish code bugs from
  documentation debt that still blocks a batch from being truly clean.
- **Compaction recovery order upgraded.** Recovery and launch guidance now consistently read:
  survival guide -> `.elves-session.json` -> learnings -> plan -> execution log ->
  `.ai-docs/manifest.md` (if present).
- **Regression preservation moved into the contract.** Plans and contracts now require at least
  one acceptance criterion that proves existing behavior still works whenever a batch changes
  existing surfaces.
- **High-risk regression review pass added.** Medium/high blast-radius batches can now run a
  narrow second review pass that ignores style and new ideas, traces changed shared surfaces to
  their consumers, and focuses only on what existing behavior could break.
- **Entropy checks can now tune the process itself.** Elves now does a lightweight process retro
  during entropy checks and records any survival-guide/template/tooling adjustment when the same
  friction repeats across batches.

### Cross-file sync

- **`SKILL.md` and `AGENTS.md` updated together** to describe the same `1.7.0` memory model,
  review loop, and `.elves-session.json` expectations.
- **Review and autonomy references updated** so `references/review-subagent.md` and
  `references/autonomy-guide.md` use the same terminology as the main skill files.
- **README, TODO, and run templates refreshed** to reflect the new layered-memory architecture and
  human-facing workflow.
- **Installed skill sync helper added.** `scripts/sync_installed_skills.py` can now check and
  mirror the canonical bundle into `~/.claude/skills/elves/` and `~/.codex/skills/elves/` so the
  local runtime copies do not drift behind the repo release. The default `--target all` behavior
  now scopes itself to installed copies that actually exist, so one-platform setups do not get
  false drift reports for the other platform.
- **Install doctor added.** `scripts/install_doctor.py` now gives startup-time update notices and
  explains when a project-local install differs from the global copy, so users can see which
  version is actually active before assuming an upgrade failed.
- **Installed runtime bundle clarified.** Installed copies now ship only the runtime scripts
  (`preflight.sh`, `notify.sh`, and `install_doctor.py`) while repo-only maintenance helpers stay
  in the checkout.
- **Repo consistency checker added.** `scripts/check_repo_consistency.py` now verifies the
  canonical version, recovery-order wording, `PENDING-DOCS` coverage, and durable doc surfaces so
  cross-file drift is caught locally before PR bots have to flag it.
- **Repo consistency workflow added.** `.github/workflows/repo-consistency.yml` runs the checker
  and Python syntax validation on PRs so drift gets caught automatically during review.

## [1.6.1] - 2026-04-02

### Review follow-up: internal consistency fixes

- **Launch read order aligned.** The launch instructions now match the core `Orient` step: survival guide, `.elves-session.json` if present, plan, then execution log.
- **Codex launch-readiness checklist completed.** `AGENTS.md` now includes the missing guardrail for unresolved planning questions that would obviously stall the run.
- **Survival guide redundancy removed.** The temporary `Run status` field was removed so `## Current Phase` remains the single source of truth for run state.
- **Kickoff template examples corrected.** The hard-launch prompt examples now match the documented recovery and read order.

## [1.6.0] - 2026-04-02

### Operator flow: stage first, launch second

#### New staging model
- **Two-call handoff is now explicit.** Elves now distinguishes between staging the run and launching the unattended execution. Planning/setup churn belongs in the staging call. The overnight run begins only after a fresh short launch command.
- **Prompt-overload guardrail added.** If a user pastes a large plan and also says "run now," the agent should slow the interaction down, stage the run, and wait for a final launch command instead of half-starting the implementation.
- **Launch readiness checklist added.** The skill now requires a cleaned plan, current survival guide and execution log, active branch, PR, preflight, recorded run controls, and a short launch prompt before unattended execution begins.

#### Prompt and template updates
- **Kickoff prompt template rewritten** around `Stage` and `Hard Launch` prompts instead of a single combined kickoff message.
- **Survival guide template updated** with run status and a launch-readiness checklist.
- **Execution log template updated** with a session setup / staging entry so the handoff between preparation and execution is visible on disk.
- **Plan template clarified** that the plan is not the launch prompt and should not be re-pasted into the launch command.

#### Cross-file sync
- **SKILL.md updated** with explicit Phase 2 staging and Phase 3 launch behavior for Claude Code.
- **AGENTS.md updated** with the same guardrails for Codex.
- **README updated** to explain the new stage-then-launch workflow, common launch failures, and the revised quick-start sequence.

## [1.5.0] - 2026-03-28

### Quality of Life: Ride-Along Protocol and Commit Message Discipline

#### Ride-along protocol (new)
- **Ride-along prefixes for mid-run user messages.** Users can prefix messages with `ra:`, `ride-along:`, or `[ride-along]` to signal "handle this and keep going." The agent responds in 1-3 sentences, incorporates any info or adjustments, and resumes the loop immediately. No follow-up questions, no pause, no summaries.
- **`ra:` shorthand added.** `ra:` is now the fastest supported form for ride-along messages, while `ride-along:` and `[ride-along]` remain valid explicit forms.
- **Full section in SKILL.md** with agent behavior rules, examples, and anti-patterns. Concise version in AGENTS.md.
- **README updated** with the new ride-along pattern in the "Riding along" section.

#### Commit message discipline (tightened)
- **Self-check rule added.** Before every `git commit`, the agent must verify the subject line matches the format. Non-negotiable.
- **Explicit anti-patterns added.** Five concrete examples of bad commit messages (missing prefix, vague descriptions, process-not-change descriptions, noun phrases without verbs) so the agent knows what NOT to do.
- **Verb-first requirement.** Subject must start with an action verb after the progress prefix: Add, Fix, Update, Remove, Implement, Extend, Refactor. Not a noun phrase, not a gerund.
- **Short subject guidance** made explicit. Commit subjects should stay concise enough to read cleanly in common `git log` views; the examples now aim for roughly 100 characters or less instead of a brittle hard cap.
- **"Progress report" framing reinforced.** `git log --oneline` should read as a timeline of the work. If it doesn't, the messages aren't specific enough.
- Applied to both SKILL.md and AGENTS.md.

#### Cross-file sync
- All changes applied to SKILL.md, AGENTS.md, and README.md.

## [1.4.0] - 2026-03-27

### Regression Prevention: Blast Radius, Attestation, Test Baselines, and Shared-Surface Analysis

#### Regression attestation (new)
- **Regression attestation step added to Document (step 9).** Forces the agent to reason about safety before marking a batch complete. Four required components: cumulative diff review (`git diff main...HEAD --stat`), shared-surface analysis with consumer verification, test baseline comparison, and confidence level with reasoning. "All tests pass" isn't sufficient. The agent must explain *what* it checked and *why* it believes existing functionality is preserved.
- **Regression attestation added to Completion Contract** (now 15 items). A batch can't be marked done without the attestation.
- **Execution log template updated** with structured regression attestation section.

#### Test baseline (new)
- **Test baseline capture in Verify Green (step 2).** Agent records test count (passed, total, skipped) in `.elves-session.json` at session start. At the end of each batch, legitimate behavior-driven count changes are allowed with preserved/improved coverage and explanation; green-seeking weaken/delete/skip is forbidden.

#### Blast radius (new)
- **Blast radius section added to Contract (step 4).** Contract now has four required sections (was three): behaviors, Build on, acceptance criteria, and blast radius. Agent must list shared files being modified, count consumers, and assess risk before writing code. Shifts regression thinking into the contract where it's cheapest to address.

#### Shared-surface regression check (new)
- **Shared-surface analysis added to review subagent.** For any modified file imported by code outside the batch scope, the reviewer must grep for consumers, verify backward compatibility, and check that all callers were updated. Unverified shared-surface changes are BLOCKING.

#### Commit-level regression tracing (new)
- **`Safe because:` line in commit messages.** When a commit touches shared code (utilities, types, interfaces, configs), the commit body must include a `Safe because:` line explaining why consumers aren't broken. Creates an audit trail the reviewer can verify.

#### Regression non-negotiable (new)
- **Survival guide template updated** with a new non-negotiable: "Never introduce regressions." Spells out the verification steps (test count, consumer grep, cumulative diff check).

#### Cross-file sync
- All changes applied to both SKILL.md (Claude Code) and AGENTS.md (Codex).
- AGENTS.md Completion Contract updated to 11 items (referencing full 15-item version in SKILL.md).

#### Backlog additions (TODO.md)
- Regression-specific review cycle for high-risk batches
- Public API surface snapshot
- Regression test as first-class acceptance criterion

## [1.3.2] - 2026-03-25

### Remaining review suggestions: operational completeness

#### New sections
- **Merge Conflicts:** What to do when `git push` fails due to a diverged remote (fetch and merge, never rebase, resolve or Hard Stop). Added to both SKILL.md and AGENTS.md.

#### Expanded sections
- **Scout Mode:** Added prioritization guidance (risk-reducing first, then quality, then leave ambiguous items), validation gate requirement, commit format (`[branch · Scout]`), and when-to-stop rules. Applied to both SKILL.md and AGENTS.md.
- **Entropy Check:** Added cadence scaling guidance (check after batch 2-3 for short plans, every 3 for long, stretch to 4-5 if reviews are clean).
- **AGENTS.md Planning phase:** Added full planning section with interactive and autonomous modes, architecture survey, and references to plan-template.md and kickoff-prompt-template.md. Was the biggest content gap between the two files.

#### Precision improvements
- **Contract step:** "Build on" section explicitly marked as required (was only shown in the example).
- **Compaction Recovery:** Added note about restoring files from git history if compaction happens during Final Completion cleanup.
- **AGENTS.md:** Added `python3 (no jq)` explanation, compaction recovery cleanup note, config.json reference already added in v1.3.1.

## [1.3.1] - 2026-03-25

### Review fixes: structural consistency and operational gaps

#### Core Loop restructuring
- **Wired the Judge into the Core Loop as step 8.** The legality check was described in a standalone section but had no step number — an agent following steps literally would never run it. Now step 8 sits between Review (7) and Document (9).
- **Renumbered all Core Loop steps** 1-15. Eliminated the "11a" hack — PR Loop is now step 13.
- **Fixed heading levels.** Batch Decomposition and Time Allocation were peers of Core Loop when they should have been children.

#### Internal consistency
- **Unified Orient and Compaction Recovery reading orders.** Added `.elves-session.json` to Orient step.
- **Clarified proof scope in Completion Contract.** "Relevant tests" → "Touched-surface tests" with note that broad regression runs at entropy checks and Readiness Gate.
- **Added legality check to Completion Contract** (now 14 items).

#### Operational gaps
- **Added `gh` API failure/retry guidance** to step 13 (PR Loop).
- **Added references** to `review-subagent.md`, `plan-template.md`, `kickoff-prompt-template.md`.

#### Cross-file sync
- AGENTS.md: renumbered steps 1-15, added step 8 (Judge), added `.elves-session.json` to Orient, added legality check to Completion Contract, added `gh` API failure guidance, added Persistent Preferences section.
- README: changed "v0" to "still early", updated file structure diagram, removed placeholder URL.
- TODO.md: marked stale PR #5 items as done.

## [1.3.0] - 2026-03-25

### PR Loop, Readiness Gate, Constitution & Legality Check

#### PR timing and review cadence
- **"Don't wait to open the PR"** — explicit instruction to open the PR after the first pushed commit, not delay until the branch is nearly done. Keep using the same PR throughout the run.
- **PR Loop (step 13):** After every push (including mid-implementation), poll PR comments, inline reviews, and check status before starting new work. Lightweight scan that defers to step 7 for full review cycles.

#### Constitution and the legality check
- **Three quality layers** made explicit: correctness (validation gates), plan compliance (review step), legality (the judge). Each asks a different question.
- **The gaming problem:** Explains why agent-authored tests have a ceiling — agents can satisfy every deterministic test while missing the point. The constitution breaks through by providing success criteria the agent didn't author.
- **The constitution:** `docs/constitution.md` or `CONSTITUTION.md` contains deal-breaker behaviors (flows with mermaid diagrams, business logic, invariants). Read during every Orient step and compaction recovery.
- **The judge:** Read-only legality check producing PASS/WARN/FAIL/UNCHANGED verdicts per intention. Runs after each batch passes validation and review. FAIL blocks the batch.
- **The flywheel:** Constitution grows via planning (propose new intentions), mistakes (regressions become safeguards), and incidents. Agent drafts, human owns.

#### Readiness gate
- **Readiness Gate:** 7-point branch-level checklist before declaring review-ready (local proof on current tip, preview proof, artifact inspection, PR comments polled, legality check clean, git status clean, execution log current). Distinct from the per-batch Completion Contract.

#### Proof scope
- **Touched-surface vs broad regression proof.** Default to touched-surface per batch; run broad regression at entropy check intervals and before readiness.
- **Re-earn proof after each push** — don't inherit proof from prior commits after review fixes.
- **Artifact inspection** — inspect actual downloaded output for export/download changes.

#### Triage and operational specificity
- **Four-category triage** unified across step 7, step 13, and judge: fix now, defer, intentional design, false positive. Replaces the previous three-category scheme.
- **Subagent capacity:** If pool is full, reuse/close idle agents or do work directly. Never skip review.
- **Process warnings:** Stop and clean up if session/process-count warnings appear.

#### Housekeeping
- Updated AGENTS.md (Codex variant) with all v1.3.0 changes.
- Updated CHANGELOG.md and README.md.

## [1.2.0] - 2026-03-25

### Harness Design: Full-Lifecycle Philosophy, Time Allocation, and Industry Convergence

#### Code Quality Philosophy across the full lifecycle
- **Philosophy now informs planning, contracts, and implementation — not just review.** Previously the 9 principles were enforced at review time. Now they're threaded through the entire lifecycle:
  - **Planning:** New architecture survey step before batch decomposition. Batch ordering is architecture-aware — shared utilities go in early batches, pattern-setting batches come before pattern-following ones.
  - **Contract (step 4):** New **Build on** section identifies specific existing patterns, utilities, and conventions the batch should extend. Gives the implementing agent a concrete target and the reviewer something specific to verify against.
  - **Implementation (step 5):** New **pre-implementation survey** — search for relevant utilities, patterns, and conventions before writing code. Logged in the execution log so the reviewer can check whether the agent used what it found.
  - **Review (step 7):** Reviewer now checks implementation against the Build on section and pre-implementation survey. Creating a duplicate of something identified in the survey is a blocking finding.

#### Time allocation
- Added **Time Allocation** guidance to the core loop. Default is equal thirds (implement, validate, review); configurable in survival guide. Agents naturally rush validation and review — this makes the expected balance explicit and trackable.

#### Entropy management
- Added **Entropy Check** step (step 12): every 3 batches, the agent performs a cross-batch quality scan to catch accumulated drift — duplicated utilities, naming inconsistencies, diverging patterns — that individual batch reviews miss. Cadence is configurable via survival guide.

#### New principle and architecture support
- Added **Principle #9: Favor boring technology.** Agents should prefer well-known, stable, composable libraries over novel ones. "Boring" technology has stable APIs and broad training-data representation, making agents more reliable. Sometimes reimplementing a small utility is cheaper than pulling in an opaque dependency.
- Added **Architectural Boundaries** section to survival guide template: optional section for defining layered architecture, dependency direction, module ownership, and enforcement mechanisms (structural tests, lint rules). Helps agents respect boundaries in larger codebases.

#### Industry convergence
- Expanded **Prior art and convergence** section in README. Elves, Anthropic, OpenAI, and Factory AI independently converged on the same core patterns for autonomous agent orchestration — plan approval before execution, persistent state across context boundaries, iterative self-correction, quality enforcement, and codebase conditioning for agent performance. Added [Factory AI Missions](https://factory.ai/news/missions) and their [Agent Readiness framework](https://factory.ai/news/agent-readiness) as a third independent convergence point alongside Anthropic and OpenAI.

#### Housekeeping
- Core loop steps renumbered: Continue or Stop is now step 13 (was 12).
- Added future ideas to TODO.md: process self-improvement across sessions, multi-model routing, secret redaction, codebase context indexing.

## [1.1.0] - 2026-03-24

### Harness Design Improvements

- Added **Verify Green** step (step 2): agents confirm the project is in a working state before starting each batch
- Added **Contract** step (step 4): agents define testable acceptance criteria before writing code (generator/evaluator pattern)
- Two-stage validation now explicit in core loop: local gates then preview deployment
- Structured session data (`.elves-session.json`) tracks `review_comments` dispositions (`fixed`, `dismissed`, `deferred`) for compaction recovery
- Strengthened review loop with commit-message-as-communication-channel guidance
- Consistent philosophy principles (1-8) across SKILL.md, AGENTS.md, and review-subagent.md
- Cross-references between AGENTS.md and reference docs (validation-guide.md, verification-patterns.md)
- Browser verification language clarified: "strongly recommended" (not blocking for non-UI projects)
- Generalized browser automation references to "Playwright, Cypress, or similar" (not Playwright MCP-specific)
- Dependency installation examples added to SKILL.md Verify Green step
- Batch sizing examples clarified as overrides of the stated default
- Configurable thresholds (5-modification, 3-cycle) noted as overridable via survival guide

## [1.0.0] - 2026-03-21

### Core Skill

- Interactive planning phase: the agent and user collaborate on scope, batches, and configuration before any code is written
- Multi-batch execution with user-defined sprint sizing (default: 4 developers x 2-week sprint)
- Core loop: Orient, Tag, Implement, Validate, Review, Document, Update, Push, Re-read, Continue
- Three-document compaction survival system (Plan, Survival Guide, Execution Log)
- Subagent delegation for long runs (Claude Code): implementer, validator, reviewer, scout
- Scout mode for bonus improvements after planned batches are done
- Time-aware pacing with session budgets
- Rollback safety with scoped Git refs at `refs/elves/rollback/<run>/<session>/bN-<digest>`
- Structured session data in `.elves-session.json`
- Persistent preferences via `config.json`
- Skill memory: execution logs improve over time

### Safety

- Forbidden commands: `git reset --hard`, `git checkout .`, `git clean -fd`, `git push --force`, `git rebase` on shared branches
- Test integrity: never modify a test to make it pass. Fix the code, not the test
- Non-interactive operation with `CI=true` and comprehensive env var hardening
- Mid-run check-in protocol: answer concisely, keep going
- PreToolUse hook example for deterministic enforcement of forbidden commands
- Survey and popup suppression guidance for Claude Code, Codex, and Cursor

### Validation

- Two-stage validation: local gates then preview deployment
- Auto-discovery for Node.js, Python, Go, Rust, and Makefile projects
- Zero accumulated debt philosophy: every batch must be production-ready
- Verification patterns: headless browser drivers, video recording, smoke testing, state assertions, custom scripts

### Review

- Built-in review subagent reads PR comments, bot reviews, and CI status (zero config)
- Adversarial review pattern: fresh-eyes subagent with no implementation context
- Custom review API support (opt-in)
- Additional checks: smoke tests, visual review, doc review, custom scripts
- Finding triage: genuine issues, intentional design choices, false positives

### Documentation

- README with origin story, Ralph Loop, Human Sandwich, and honest v0 framing
- "What to expect" section with real ROI numbers (6-9 months of work in 3-4 hours of human time)
- "Riding along" guidance: say "do not stop" in every message
- "What can go wrong" failure modes table with mitigations
- Preventing sleep/shutdown guide (caffeinate, systemd-inhibit, tmux/screen)
- Monitoring with GitKraken and Slack notifications
- Claude Code hooks: SessionStart for auto-loading context, PreToolUse for forbidden commands
- Installation guide: global and per-project for Claude Code, Codex, Claude.ai
- "Making it your own" customization guidance
- Daily briefing and Friday planning cadence

### Templates

- Survival guide template with non-negotiables, tool config, and safe rollback procedures
- Execution log template with timing breakdown and Ralph Loop framing
- Plan template with worked example (auth system refactor) and Human Sandwich framing
- Kickoff prompt template (minimal and full versions) with daily briefing guidance
- Tool configuration examples for Node, Python, Go, Rust, monorepos, and custom APIs

### Scripts

- `preflight.sh`: comprehensive pre-run checklist (git, auth, project detection, sleep prevention, gate dry-runs, notification checks, non-interactive env guidance, branch staleness)
- `notify.sh`: Slack webhook, custom command, or PR comment notification helper. Returns proper exit codes in --test mode for preflight validation

### Platform Support

- Claude Code (SKILL.md): full feature set with subagents and hooks
- Codex (AGENTS.md): direct execution, concise format
- Claude.ai: zip upload
- Any Agent Skills compatible platform (open standard)
- Passes `agentskills validate`
