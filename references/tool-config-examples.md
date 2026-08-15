# Tool Configuration Examples

> These are ready-to-paste `## Tool Configuration` blocks for different project types.
> Copy the block that matches your project into your survival guide, then delete the comments
> and unused lines.
>
> The agent reads `## Tool Configuration` in the survival guide and uses those commands in
> preference to auto-discovery. If a field is blank or commented out, the agent falls back to
> auto-discovery as documented in SKILL.md. Leave `e2e:` commented unless you want browser proof;
> Elves does not run browser or E2E checks unless the user explicitly asked, and they never block
> a run.

Elves helper commands in this reference use source-checkout shorthand. From an installed Claude
Code or Codex skill, invoke helpers from the active Elves skill root while the target repository
stays the working directory; see [`runtime-helper-paths.md`](runtime-helper-paths.md).

---

## Node.js - npm (Minimal)

> Use when your project has some but not all of lint/typecheck/build/test configured.
> Only include what you actually have. The agent skips missing entries.

```yaml
## Tool Configuration

lint: npm run lint --if-present
typecheck: npm run typecheck --if-present
build: npm run build --if-present
test: npm test --if-present
review: github-pr-comments
notification: pr-comment
```

---

## Node.js - npm (Full)

> Use when you have the full suite including E2E and a preview URL for smoke testing.

```yaml
## Tool Configuration

lint: npm run lint
typecheck: npm run typecheck
build: npm run build
test: npm test
e2e: npx playwright test
smoke: curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/health
review: github-pr-comments
notification: slack-webhook    # requires ELVES_SLACK_WEBHOOK env var
```

---

## Node.js - pnpm (Minimal)

```yaml
## Tool Configuration

lint: pnpm lint
typecheck: pnpm typecheck
build: pnpm build
test: pnpm test
review: github-pr-comments
notification: pr-comment
```

---

## Node.js - pnpm (Full)

```yaml
## Tool Configuration

lint: pnpm lint
typecheck: pnpm typecheck
build: pnpm build
test: pnpm test
e2e: pnpm exec playwright test
smoke: curl -s -o /dev/null -w "%{http_code}" https://preview.example.com/health
review: custom-api
review-api-url: https://review.example.com/api/review
review-api-header: x-api-key: ${REVIEW_API_KEY}
notification: slack-webhook
```

---

## Python - ruff + mypy + pytest (Minimal)

> Use when you have basic linting and testing but no type checking configured.

```yaml
## Tool Configuration

lint: ruff check .
test: pytest
review: github-pr-comments
notification: pr-comment
```

---

## Python - ruff + mypy + pytest (Full)

> Use when you have the full Python quality suite. `ruff format --check` validates formatting
> without changing files.

```yaml
## Tool Configuration

lint: ruff check . && ruff format --check .
typecheck: mypy . --ignore-missing-imports
# build: (no build step for pure Python — omit or use `python -m build` for packages)
test: pytest --tb=short
e2e: pytest tests/e2e/ --tb=short    # if you have a separate e2e suite
smoke: curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health
review: github-pr-comments
notification: slack-webhook
```

---

## Go (Minimal)

> `go build ./...` acts as both build and type check in Go.

```yaml
## Tool Configuration

lint: golangci-lint run
build: go build ./...
test: go test ./...
review: github-pr-comments
notification: pr-comment
```

---

## Go (Full)

```yaml
## Tool Configuration

lint: golangci-lint run --timeout=5m
# typecheck: (covered by go build)
build: go build ./...
test: go test ./... -race -count=1
e2e: go test ./tests/e2e/... -tags=e2e
smoke: curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/healthz
review: github-pr-comments
notification: slack-webhook
```

---

## Rust (Minimal)

> `cargo check` is faster than `cargo build` and catches type errors.

```yaml
## Tool Configuration

lint: cargo clippy
build: cargo check
test: cargo test
review: github-pr-comments
notification: pr-comment
```

---

## Rust (Full)

```yaml
## Tool Configuration

lint: cargo clippy -- -D warnings
# typecheck: (covered by cargo build)
build: cargo build
test: cargo test -- --test-threads=4
# e2e: (uncomment if you have integration tests in a separate binary)
# e2e: cargo test --test integration_tests
smoke: curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health
review: github-pr-comments
notification: slack-webhook
```

---

## Makefile Project

> Use when the project has a Makefile that wraps the actual toolchain. Works for any language.

```yaml
## Tool Configuration

lint: make lint
typecheck: make typecheck
build: make build
test: make test
e2e: make e2e
smoke: make smoke
review: github-pr-comments
notification: pr-comment
```

---

## Monorepo - Turborepo (Full)

> Turborepo caches task results across packages. Use `--filter` to run tasks in a specific
> package during development, or run without filter for the full repo.

```yaml
## Tool Configuration

# Full repo
lint: npx turbo lint
typecheck: npx turbo typecheck
build: npx turbo build
test: npx turbo test
e2e: npx turbo e2e
# smoke: curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/health

# Alternatively, target a specific package:
# lint: npx turbo lint --filter=@acme/api
# test: npx turbo test --filter=@acme/api

review: github-pr-comments
notification: slack-webhook
```

---

## Monorepo - Nx (Full)

```yaml
## Tool Configuration

# Full repo (affected only — faster, runs only what changed)
lint: npx nx affected --target=lint --base=main
typecheck: npx nx affected --target=typecheck --base=main
build: npx nx affected --target=build --base=main
test: npx nx affected --target=test --base=main
e2e: npx nx affected --target=e2e --base=main

# Or run everything (slower, use for final validation):
# lint: npx nx run-many --target=lint --all
# test: npx nx run-many --target=test --all

review: github-pr-comments
notification: slack-webhook
```

---

## Custom API Review (Any Project)

> Use this when you have an internal code review service or AI reviewer with an API endpoint.
> The agent posts the diff and reads structured findings in response.

```yaml
## Tool Configuration

lint: npm run lint
typecheck: npm run typecheck
build: npm run build
test: npm test
review: custom-api
review-api-url: https://review.example.com/api/review
review-api-header: x-api-key: ${REVIEW_API_KEY}
notification: pr-comment
```

---

## Math Research Workflow

> Use when a run includes preliminary research, proof search, source audit, paper drafting, or
> post-draft mathematical review. Math is a Cobbler-managed domain workflow. Host-native subagents
> or direct analysis are the default fallback; external providers and source-search tools are
> optional role routes.

```yaml
## Tool Configuration

review: github-pr-comments
notification: pr-comment

math-coordination: cobbler-managed-domain-workflow
math-provider-policy: native-first-with-optional-external-routes
math-required-env: []
math-optional-env:
  - OPENROUTER_API_KEY
  - GEMINI_API_KEY
  - ANTHROPIC_API_KEY
  - XAI_API_KEY
  - OPENAI_API_KEY
  - EXA_API_KEY
math-role-models:
  subfield_scout: native-subagent
  cross_field_synthesizer: native-coordinator
  proof_critic: native-subagent
  derivation_checker: native-subagent
  source_auditor: native-subagent
  exposition_editor: native-subagent
  formalization_scout: native-subagent
  evolutionary_search: off
math-optional-tools:
  # - alphaevolve
math-external-route-examples:
  # subfield_scout: openrouter:<model-id>
  # proof_critic: openrouter:<model-id>
  # evolutionary_search: alphaevolve:<task-id>
math-alphaevolve:
  enabled: false
  auth: gcloud-impersonation
  artifact_dir: alphaevolve_runs
  promote_policy: independent-local-replay-only
math-fallback-policy: record-before-switching-provider
math-ledger-dir: docs/math
```

---

## Cobbler

> Default Cobbler coordination block for Elves runs. Cobbler-first is the default orchestration
> model; Quick Cobbler is the one-off read-only answer mode. Customize only if changing routing,
> role count, answer shape, or provider-backed council. Quick Cobbler requires no external provider
> key. Provider-backed council is optional advanced plumbing.

```yaml
## Tool Configuration

review: github-pr-comments
notification: pr-comment

cobbler-enabled: true
cobbler-coordination-default: cobbler-first
cobbler-default-for-elves-runs: true
cobbler-default-mode: quick
cobbler-default-backend: native-subagents
cobbler-primary-invocations:
  claude-code: /cobbler
  codex: "$elves cobbler: <task>"
cobbler-compatibility-aliases:
  - /council
  - /ec
  - /elves-council
  - "$elves council: <task>"
cobbler-default-answer-shape:
  - Recommendation
  - Why this fits
  - Strongest dissent
  - Risks
  - Next move
  - Confidence
cobbler-default-role-count: 3
cobbler-max-role-count: 5
cobbler-quick-read-only: true
cobbler-quick-stateless: true
cobbler-run-logging: existing-elves-memory
cobbler-harness-loop:
  - capability-scan
  - route-and-medium-selection
  - context-packet
  - execute-agents-tools-skills
  - collect-evidence
  - fit-answer
  - present-record
  - reclassify
cobbler-output-mediums:
  - chat-answer
  - file-edit
  - pr-comment
  - execution-log
  - .elves-session.json
  - elves-report
cobbler-context-packet:
  - user-intent
  - mode
  - work-scope
  - relevant-files
  - run-state-pointers
  - available-tools-skills
  - source-freshness
  - constraints
  - forbidden-actions
cobbler-model-routing-policy: native-first
cobbler-provider-backed-fallback: native-subagent-and-note

# Optional provider-backed council diversity. Leave disabled unless the user opts in.
cobbler-provider-backed-enabled: false
cobbler-provider-backed-policy: optional-external-providers
cobbler-provider-backed-required-env: []
cobbler-provider-backed-optional-env:
  - OPENROUTER_API_KEY
  - GEMINI_API_KEY
  - ANTHROPIC_API_KEY
  - XAI_API_KEY
  - OPENAI_API_KEY
cobbler-provider-backed-role-models:
  default: native-subagent
  architect: native-subagent
  skeptic: native-subagent
  implementation_analyst: native-subagent
  tester: native-subagent
  synthesis: native-coordinator
cobbler-provider-backed-role-effort:
  architect: high
  skeptic: high
  tester: medium

# Optional effort values are hints only: low, medium, high, or xhigh when the backend supports them.
#
# Optional external routes use provider:model-id strings and still fall back to native when
# provider-backed council is disabled or the configured key is unavailable.
# cobbler-provider-backed-role-models:
#   skeptic: "openrouter:<model-id>"
#   fast_sanity: "openrouter:<fast-model-id>"
```

Legacy `council-*` config keys remain compatibility aliases for existing `v1.14.0` setups. Prefer
new `cobbler-*` keys in fresh configs, but do not rename working project config just for style.

### Setup (optional local preferences)

```bash
# Inventory only — no credentials printed, no paid model turns
python3 scripts/cobbler_agents.py setup --json --dry-run

# Write ignored local .elves/models.toml (never stage it)
python3 scripts/cobbler_agents.py setup --json \
  --implement grok-build \
  --review claude-code \
  --lightweight-review host-native
```

Claude Code: `/setup-cobbler` or `/setup-council`. Codex: `$elves setup-cobbler` /
`$elves setup-council` (not top-level slash). Recipes: `references/cobbler-setup-recipes.md`.

### Read-only council runtime commands

```bash
# Parallel independent lenses (default host-native; no paid providers required)
python3 scripts/cobbler_agents.py council --json \
  --task "review the proposed batch contract" \
  --roles architect,skeptic,tester \
  --target-quorum 2

# Hard quorum only when the project Survival Guide marks the phase required=true
python3 scripts/cobbler_agents.py council --json \
  --task "required review phase" \
  --phase review --phase-required --required-quorum 2

# Utility review — not a council vote, cannot close high-risk review
python3 scripts/cobbler_agents.py lightweight-review --json \
  --task "quick docs/consistency check"
```

Artifacts (if written) stay under ignored `.elves/runtime/council/<run-id>/`. Do not commit
transcripts. Host synthesis remains the fitted-answer owner.

---

## Full-Run Model Routing

> Use when a full Elves run should prefer different elves for implementation, validation, review,
> scouting, and synthesis. These preferences are advisory unless the host or configured provider can
> honor them. Native host capability is the default; missing optional provider access falls back to
> host-native work and does not block ordinary runs.

```yaml
## Tool Configuration

model-routing:
  enabled: true
  policy: native-first
  fallback: host-native
  phases:
    implement:
      preference: strongest-host-native
      provider-backed-allowed: false
      required: false
    validate:
      preference: reliable-host-native
      provider-backed-allowed: false
      required: false
    review:
      preference: independent-lens
      provider-backed-allowed: true
      required: false
    scout:
      preference: broad-fast-lens
      provider-backed-allowed: true
      required: false
    synthesize:
      preference: coordinator
      provider-backed-allowed: true
      required: false

# Terse aliases are staging sugar and should expand to the structured block above.
implement-model: strongest-host-native
validate-model: reliable-host-native
review-model: independent-lens
scout-model: broad-fast-lens
synthesize-model: coordinator

# Provider namespaces are explicit. Do not treat bare aliases as provider model IDs.
# Examples: native-subagent, host-default, codex:<host-option>, claude-code:<host-option>,
# openrouter:<model-id>, gemini:<model-id>, anthropic:<model-id>, xai:<model-id>,
# openai:<model-id>.
```

Use `required: true` only when the survival guide explicitly opts the project into a hard route
requirement. Never infer it from provider config, Quick Cobbler, or legacy Council aliases.

---

## Public API Surface Snapshot

> Use this when a run should capture consumer-facing contracts as regression evidence. Keep it
> optional by default. `enabled: auto` should continue with `unavailable` when no credible source
> exists; `required: true` is only valid when the survival guide explicitly opts in.

```yaml
api-surface-snapshot:
  enabled: auto
  required: false
  baseline-path: .elves/api-surface/baseline.json
  current-path: .elves/api-surface/current.json
  diff-path: .elves/api-surface/diff.md
  sources:
    rest:
      mode: auto
      preferred: openapi
      examples:
        - npm run openapi:json
        - python manage.py spectacular --file -
    graphql:
      mode: auto
      preferred: sdl
      examples:
        - npm run graphql:schema
    exports:
      mode: auto
      preferred: package-exports-or-declaration-output
    cli:
      mode: auto
      preferred: help-output
      examples:
        - my-tool --help
    events:
      mode: auto
      preferred: documented-event-schema
    config:
      mode: auto
      preferred: documented-env-and-config-keys
  policy:
    unavailable-source: warning
    additive-change: info
    intentional-breaking-change: requires-plan-note
    unexpected-breaking-change: blocking
```

Record shapes and field names, not secrets, bearer tokens, cookies, customer payloads, or production sample data.
Use existing structured sources before inventing scanners.
If no credible source exists, record `unavailable` with the reason instead of fabricating a snapshot.
A snapshot proves public surface shape only; it is not a substitute for tests, E2E checks, review, or the human-owned constitution.

---

## Notification Options Reference

> Choose one notification method. Only one is active at a time.

```yaml
# Option 1: PR comment (zero config, always available)
notification: pr-comment

# Option 2: Slack webhook (requires ELVES_SLACK_WEBHOOK env var)
notification: slack-webhook
# export ELVES_SLACK_WEBHOOK=https://hooks.slack.com/services/T.../B.../...

# Option 3: Custom command (any shell command or script)
notification: custom-cmd
# export ELVES_NOTIFY_CMD="curl -s -X POST https://ntfy.sh/my-topic -d 'Elves done'"
# export ELVES_NOTIFY_CMD="osascript -e 'display notification \"Elves done\" with title \"Elves\"'"
# export ELVES_NOTIFY_CMD="./scripts/notify-team.sh"
```

---

## Notes on Tool Configuration

**Precedence:** Commands in `## Tool Configuration` always take precedence over auto-discovery.
If you configure a command here, the agent will use it, even if the auto-discovered command
would produce the same result.

**Blank or omitted fields:** If a field is absent, the agent falls back to auto-discovery
for that step. If auto-discovery also finds nothing, the step is skipped silently.

**Exit codes:** Every configured command must return exit code 0 for pass, non-zero for fail.
The agent treats any non-zero exit as a gate failure and won't proceed until it is resolved.

**Environment variables:** Commands can reference environment variables using `${VAR_NAME}`
syntax. The agent will substitute them at runtime. Sensitive values should be in the
environment, not hardcoded in the survival guide.

**Working directory:** All commands run from the repo root unless you specify otherwise.
If your tests must be run from a subdirectory, prefix the command:
```yaml
test: cd packages/api && npm test
```
