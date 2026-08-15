# Context Index

Use this index as the first map when surveying the Elves repo. It points to the durable surfaces,
the runtime surfaces, and the checks that usually matter before editing.

## Primary Surfaces

- `SKILL.md`: compact canonical workflow and metadata for every supported host.
- `AGENTS.md`: thin Codex invocation adapter that points back to `SKILL.md`.
- `README.md`: human-facing overview, installation, usage, troubleshooting, and operator guidance.
- `guide/index.html`: short public walkthrough for installing, running, watching, and finishing an
  Elves run in Claude Code or Codex.
- `CHANGELOG.md`: release history and version-specific behavior changes.
- `TODO.md`: historical archive; the live backlog is tracked in GitHub issues.
- `config.json.example`: persistent preference schema, Cobbler-first defaults, and optional
  provider configuration.
- `docs/cobbler.md`: human-facing Cobbler walkthrough, paired with `assets/cobbler-infographic.png`.
- `.github/workflows/pages.yml`: publishes only `guide/` to the repository's GitHub Pages site.

## Durable Agent Docs

- `.ai-docs/manifest.md`: read-order and file inventory for this directory.
- `.ai-docs/architecture.md`: repo shape and documentation-memory layers.
- `.ai-docs/conventions.md`: rules for versioning, cross-file sync, run control, and merge policy.
- `.ai-docs/gotchas.md`: recurring traps in this documentation-heavy repo.
- `.ai-docs/context-index.md`: this quick map for future pre-implementation surveys.

## Reference Docs

- `references/kickoff-prompt-template.md`: recommended single-kickoff prompts plus the explicitly
  labeled legacy two-call alternative.
- `references/survival-guide-template.md`: run-control, Stop Gate, active compute, and launch
  readiness template.
- `references/execution-log-template.md`: batch logging and regression-attestation template.
- `references/review-subagent.md`: review loop, final readiness review, and reviewed-PR landing
  guidance.
- `references/open-ended-guide.md`: continuation rules for non-stop runs.
- `references/autonomy-guide.md`: non-interactive operation, resource hygiene, and local maintenance.
- `references/council-workflow.md`: Cobbler workflow and Council compatibility path.
- `references/council-prompts.md`: Cobbler role and fitted-answer prompt templates.
- `references/council-provider-config.md`: optional provider-backed Cobbler configuration.
- `references/codex-goals.md`: how Goals keeps Codex moving while Cobbler coordinates the Elves
  loop.
- `references/adaptive-worker-routing.md` and `references/grok-open-source-worker.md`: deterministic
  native-first worker choice and the optional open-source Grok capability, launch, follow, fallback,
  and recovery contract.
- `references/prewalk.md`: normative exact-session native-worker guide/execution lifecycle,
  capability truth, TODO/checkpoint schema, parity, recovery, and rollout contract.
- `references/math-*.md`: Cobbler-managed math domain workflow templates, ledgers, and provider
  role guidance.

## Scripts

- `scripts/verify_repo.py`: canonical aggregate repository verification entrypoint; combines
  consistency, release, Python/shell/JSON, installed-link, test, and final-readiness checks.
- `scripts/check_repo_consistency.py` plus `consistency_engine.py` / `consistency_policy.py`:
  cross-file drift engine and high-value guardrail policy.
- `scripts/sync_installed_skills.py`: syncs the installable runtime surface into Claude/Codex skill
  directories.
- `scripts/installed_bundle_smoke.py`: verifies both installed host bundles and rejects broken
  installed-only Markdown links.
- `scripts/install_doctor.py`: advisory install/update diagnostics for startup and doctor mode.
- `scripts/release_checklist.py`: read-only release sweep for version alignment, changelog
  promotion, current-version examples, and changed human-facing docs.
- `scripts/pr_portfolio_report.py`: read-only PR stack health summary for merge state, checks, and
  unresolved review threads.
- `scripts/preflight.sh`: staging preflight for git, gh, environment, non-browser validation
  gates, notifications, and worktree ownership. Does not run Playwright, host-browser, or E2E
  checks; those never block launch.
- `scripts/preflight_worktree.py`: explicit dedicated-worktree helper used by
  `./scripts/preflight.sh --create-worktree`.
- `scripts/validate_survival_guide.py`: advisory validator for required survival-guide sections.
- `scripts/acceptance_contract.py`: pre-launch stable-ID syntax, plan/session synchronization,
  exact criterion parity, advisory packet-path compatibility, and opt-in strict Markdown/JSON
  handoff-v1 state validation.
- `scripts/elves_landing_check.py`: acceptance/readiness proof gate for a live session.
- `scripts/cobbler_agents.py`: thin CLI for onboarding, routing, sessions, trusted full-run
  supervision, legacy bounded implementation, and untrusted writer leases.
- `scripts/cobbler_runtime/preferences.py`, `worker_routing.py`, `native_worker.py`: safe global
  worker preferences, deterministic adaptive route decisions, and host-native worker specs.
- `scripts/cobbler_runtime/prewalk.py`: provider-neutral prewalk artifacts, capability evidence,
  meaningful-edit transition validation, and canonical guide/continuation prompts.
- `scripts/cobbler_runtime/`: typed provider-neutral runtime for routing, isolation, delegated Git,
  full-run supervision, evidence review, sessions, storage, and public API snapshots.
- `scripts/openrouter_lens.py`: optional read-only OpenRouter role wrapper.
- `scripts/workspace_guard.py`: installed optional owned-tip guard for candidate write commands.
- `scripts/notify.sh`: Slack/custom-command/GitHub fallback notification helper.

## Tests

- Repository/release/install: `test_check_repo_consistency.py`, `test_verify_repo.py`,
  `test_release_checklist.py`, `test_sync_installed_skills.py`, `test_installed_bundle_smoke.py`,
  `test_install_doctor.py`, and `test_architecture_evidence.py`.
- Cobbler routing/config: `test_cobbler_agents_config.py`, `test_cobbler_agents_dispatch.py`,
  `test_dispatch_isolation.py`, `test_cobbler_native_only_fallback.py`,
  `test_cobbler_agents_onboard.py`, `test_cobbler_agents_setup.py`,
  `test_cobbler_agents_sessions.py`, and `test_cobbler_executables.py`.
- Worker/supervisor/Git: `test_cobbler_agents_implement.py`, `test_full_run_supervisor.py`,
  `test_cobbler_agents_leases.py`, `test_worker_cli_lifecycle.py`,
  `test_storage_isolation_git.py`, `test_public_api_snapshot.py`, and
  `test_native_worker_prewalk.py`.
- Operator surfaces: `test_elves_landing_check.py`, `test_preflight_sh.py`,
  `test_preflight_worktree.py`, `test_acceptance_contract.py`,
  `test_validate_survival_guide.py`, `test_workspace_guard.py`, `test_notify_sh.py`,
  `test_pr_portfolio_report.py`, and `test_openrouter_lens.py`.

## Common Survey Paths

- Behavior or run-loop change: read `SKILL.md`, `AGENTS.md`, `README.md`, related `references/*`,
  `scripts/check_repo_consistency.py`, and `tests/test_check_repo_consistency.py`.
- Cobbler change: read `SKILL.md`/`AGENTS.md` Cobbler sections, README Cobbler sections,
  `docs/cobbler.md`, `references/council-workflow.md`, `references/council-prompts.md`,
  `references/council-provider-config.md`, survival/kickoff/execution-log templates, image assets
  such as `assets/cobbler-infographic.png`, and the Cobbler phrase maps in
  `scripts/check_repo_consistency.py`.
- Math workflow change: read `references/math-workflow.md`, `references/math-provider-config.md`,
  `references/math-plan-template.md`, `references/math-review-prompts.md`,
  `references/math-artifact-ledgers.md`, `config.json.example`, README, and the domain-workflow
  phrase maps and structured config tests.
- Preflight or install change: read `scripts/preflight.sh`, `scripts/preflight_worktree.py`,
  `scripts/install_doctor.py`, `scripts/sync_installed_skills.py`, matching tests, README install
  sections, and `.ai-docs/gotchas.md`.
- Release/version change: read `SKILL.md` metadata, `AGENTS.md` front matter, `CHANGELOG.md`,
  README release/install sections, `config.json.example`, and release helper/checker scripts.
- Acceptance contract change: read `scripts/cobbler_runtime/acceptance.py`,
  `scripts/acceptance_contract.py`, `scripts/elves_landing_check.py`, full-run prepare/launch,
  preflight, plan/session/packet templates, and their focused tests.
- Prewalk or native phase-route change: read `references/prewalk.md`,
  `references/host-parity.md`, `references/adaptive-worker-routing.md`, `prewalk.py`,
  `native_worker.py`, `worker_routing.py`, versioned host-help fixtures, installed-bundle smoke,
  and `test_native_worker_prewalk.py`.

## Validation Baseline

For this repo, use the canonical aggregate verifier instead of maintaining a duplicate command
list:

```bash
python3 scripts/verify_repo.py --ci
```

Before final readiness on an active run, use:

```bash
python3 scripts/verify_repo.py --final-readiness --session <session-path>
```

The aggregate verifier includes `git diff --check`; focused tests remain useful while iterating.
