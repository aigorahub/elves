# TODO

Project backlog and deferred tasks. Live items first; completed history under
`## Completed Archive`.

## Live

- [ ] Parallelves Phase 2: session-schema lane state and staging validation — v1 records `lanes`
  advisorily for recovery only; validating staged lane state needs its own planned run.
- [ ] Parallelves runtime lane supervision (future work beyond the v1 phase roadmap) — explicitly future work; v1 ships contract
  plus recommend-only tooling and no orchestrator, so supervision needs a product decision first.
- [ ] [#98] Investigate host-native UI prompts and arbitrary third-party tools that bypass
  Elves' transport helpers. Those surfaces cannot honestly be described as covered by the
  built-in external-lane filter and may require host or MCP-level interception.
- [ ] [#92, issue-86 §17] Decompose `full_run.py` (monitor/await extraction) — structural
  refactor deserving its own planned run; v2.10.2's shared projection helper removed the worst
  duplication.
- [ ] [#93, issue-86 §18] Confidence-calibration tracking across runs — roadmap feature
  needing a product decision, not patch-release material.
- [ ] [#94, issue-86 §19] Native-lane structured confidence sidecar — roadmap feature
  needing a product decision, not patch-release material.
- [ ] [#95, issue-86 §20 + prewalk launch path] Complete and independently review the Grok
  prewalk launch path before opening the maintainer-owned `launch_ready` registry gate:
  materialize the bounded prompt-file input, validate the non-yolo auth/permission profile end
  to end, run an operator-authorized live canary at the `high` execution-effort default, bind
  its artifact to the live installed version/build, and regression-test create→exact-resume
  continuity. Qualification evidence must never open this gate by itself; operator-owned and
  never fabricated by an unattended worker.
- [ ] [#96, v2.10.2 review advisory] Resume-prepare over a terminally-evented session survives
  the liveness guard but appends `run_started` after a terminal event, so the rebuilt run dies
  on first monitor ("event appears after terminal event"). Fail-closed today; either refuse
  terminal sessions at rebuild or cover the interplay with a test.
- [ ] [#97, v2.10.2 review advisory] Widen the public persona wording guard beyond the six
  claim shapes (e.g. "Fable-powered", "runs on Fable", "is Fable", and Claude/Anthropic persona
  phrasings) while keeping model-identifier exemptions false-positive-free.

## Completed Archive

### Deferred from PR #5

- [x] ~~Update the validation guide to soften mandatory browser testing language to 'strongly recommended'~~ (already done — validation-guide.md uses "strongly recommended")
- [x] ~~Standardize Verify Green, Contract, and Entropy Check across skill files~~ (stale — these referred to code orchestration modules that don't exist in this repo; the Markdown skill files are the implementation)

### Future Ideas

- [x] Replace the old optional trajectory experiment with true exact-session native-worker
  prewalk. Codex and Claude now share a feature-gated guide→meaningful-edit checkpoint→execution
  supervisor, bounded TODO/checkpoint artifacts, honest instruction fidelity, deterministic
  capability/routing state, parity fixtures, and installed-bundle coverage. Live behavioral
  qualification and dogfood evaluation remain rollout phases, not implementation claims; see
  `references/prewalk.md`.

- [x] Add a lightweight process-retro pass to entropy checks.
  `SKILL.md`, `AGENTS.md`, `README.md`, and `references/execution-log-template.md` now tell Elves
  to spend a few minutes on repeated friction during entropy checks and tighten the survival guide,
  templates, learnings, or tool config when a pattern clearly recurs.

### Follow-ups from v1.7.0

- [x] Add a repo consistency checker for the high-value drift classes from `v1.7.0`.
  `scripts/check_repo_consistency.py` now checks version alignment, recovery-order wording,
  `PENDING-DOCS` coverage, and the expected durable doc surfaces.

- [x] Add a local installed-skill sync helper for `.claude/` and `.codex/` copies.
  `scripts/sync_installed_skills.py` now checks and mirrors the managed bundle from this checkout
  into `~/.claude/skills/elves/` and `~/.codex/skills/elves/`.

- [x] Add optional Cobbler role model routing for subagents.
  Cobbler role routes now stay native-first by default while allowing opt-in `provider:model-id`
  strings such as `openrouter:<model-id>` in the survival guide or config example. Missing provider
  routes fall back to native and should be treated as evidence sources, not authority.
- [x] Add optional full-run phase model routing for implementation, validation, review, scouting,
  and synthesis.
  `SKILL.md`, `AGENTS.md`, README, `references/survival-guide-template.md`,
  `references/execution-log-template.md`, `references/review-subagent.md`,
  `references/tool-config-examples.md`, and `config.json.example` now describe native-first
  routing preferences, terse `*-model` aliases, material fallback logging, and the rule that
  `required: true` must be an explicit survival-guide opt-in.

#### Secret redaction layer

- [x] Redact built-in external model transports before dispatch. Context, OpenRouter, worker
  evidence, and structured output paths now redact secret-shaped values, sensitive mapping keys,
  and exact launch-scoped credential values without persisting the credentials themselves.
  (The remaining host-UI/third-party-tool investigation is a Live item above.)

#### Codebase context indexing

The pre-implementation survey (step 5) relies on the agent searching the codebase in real time. For large repos, a pre-computed index of utilities, patterns, conventions, and module boundaries would make the survey faster and more reliable. Could be generated once during planning and updated incrementally per batch. Similar in spirit to Factory AI's "HyperCode" but implemented as a Markdown file the agent reads rather than proprietary tooling.

- [x] Add an initial durable context index for this repo.
  `.ai-docs/context-index.md` now maps primary surfaces, reference docs, scripts, tests, common
  survey paths, and the validation baseline for future agents.

- [x] Add a regression-specific review cycle for high-risk batches.
  `SKILL.md`, `AGENTS.md`, `README.md`, and `references/review-subagent.md` now describe an
  optional regression-only pass for medium/high blast-radius batches that traces changed shared
  surfaces to their consumers and asks only what existing behavior could break.

#### Public API surface snapshot

For projects with APIs (REST, GraphQL, exported library interfaces), capture the API surface at session start: route list, response shapes, exported types and functions. At the end of each batch, diff the snapshot against the current state. Any unintended change to the public API surface is a finding. This complements the test baseline (which catches removed tests) and the regression attestation (which catches shared-surface changes). It catches changes that pass all tests but alter the contract with consumers.

- [x] Add guardrail docs, config examples, ignored artifact paths, repository checks, and the
  implemented `cobbler_runtime.public_api_snapshot` compatibility gate for public API surfaces.

- [x] Make regression preservation an explicit acceptance-criteria rule.
  `SKILL.md`, `AGENTS.md`, `README.md`, and `references/plan-template.md` now require at least one
  acceptance criterion that proves old behavior still works when a batch changes existing surfaces.

### Follow-ups from v1.8.0

- [x] Expand `scripts/check_repo_consistency.py` to cover the operator-facing docs that now mirror
  run control, including the kickoff prompt template, overnight run report template, and durable
  `.ai-docs/*` surfaces.
  The checker now phrase-pins durable `.ai-docs/*` guidance, the overnight run report issue
  template, and the kickoff prompt's run-control fields.

- [x] Add a lightweight release checklist or helper that sweeps embedded version examples,
  changelog heading promotion, and newly added human-facing doc surfaces during a minor release.
  `scripts/release_checklist.py` now checks release version alignment, warns or fails on
  unpromoted changelog content depending on mode, verifies current-version examples, and reports
  changed or newly added human-facing surfaces from a base ref.

### Follow-ups from v1.11.0

- [x] Add a deterministic preflight guard for duplicate current-branch worktrees, complementing the
  prose-level one-run-one-checkout rule with enforcement. Implemented in `scripts/preflight.sh`: it
  hard-fails when the current branch is checked out in multiple worktrees.
- [x] Optional preflight helper that offers to create the dedicated `git worktree` automatically when
  it detects another active checkout of the same branch.
  `scripts/preflight_worktree.py` now backs
  `./scripts/preflight.sh --create-worktree <branch> --base origin/main`, supports `--dry-run`,
  generated sibling paths, explicit path overrides, branch/base collision checks, and advisory
  duplicate-checkout recommendations without mutating default preflight.
- [x] Partial progress on the v1.8.0 checker-expansion follow-up: v1.11.0 added
  `WORKSPACE_ISOLATION_PHRASES` (covers the kickoff template, survival-guide template, and README).
  PR #31 completes the remaining coverage by phrase-pinning the overnight-run-report template and
  durable `.ai-docs/*` surfaces.
