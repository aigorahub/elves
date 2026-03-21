# Tool Configuration Examples

> These are ready-to-paste `## Tool Configuration` blocks for different project types.
> Copy the block that matches your project into your survival guide, then delete the comments
> and unused lines.
>
> The agent reads `## Tool Configuration` in the survival guide and uses those commands in
> preference to auto-discovery. If a field is blank or commented out, the agent falls back to
> auto-discovery as documented in SKILL.md.

---

## Node.js — npm (Minimal)

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

## Node.js — npm (Full)

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

## Node.js — pnpm (Minimal)

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

## Node.js — pnpm (Full)

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

## Python — ruff + mypy + pytest (Minimal)

> Use when you have basic linting and testing but no type checking configured.

```yaml
## Tool Configuration

lint: ruff check .
test: pytest
review: github-pr-comments
notification: pr-comment
```

---

## Python — ruff + mypy + pytest (Full)

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

## Monorepo — Turborepo (Full)

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

## Monorepo — Nx (Full)

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

## Notification Options Reference

> Choose one notification method. Only one is active at a time.

```yaml
# Option 1: PR comment — zero config, always available
notification: pr-comment

# Option 2: Slack webhook — requires ELVES_SLACK_WEBHOOK env var
notification: slack-webhook
# export ELVES_SLACK_WEBHOOK=https://hooks.slack.com/services/T.../B.../...

# Option 3: Custom command — any shell command or script
notification: custom-cmd
# export ELVES_NOTIFY_CMD="curl -s -X POST https://ntfy.sh/my-topic -d 'Elves done'"
# export ELVES_NOTIFY_CMD="osascript -e 'display notification \"Elves done\" with title \"Elves\"'"
# export ELVES_NOTIFY_CMD="./scripts/notify-team.sh"
```

---

## Notes on Tool Configuration

**Precedence:** Commands in `## Tool Configuration` always take precedence over auto-discovery.
If you configure a command here, the agent will use it — even if the auto-discovered command
would produce the same result.

**Blank or omitted fields:** If a field is absent, the agent falls back to auto-discovery
for that step. If auto-discovery also finds nothing, the step is skipped silently.

**Exit codes:** Every configured command must return exit code 0 for pass, non-zero for fail.
The agent treats any non-zero exit as a gate failure and will not proceed until it is resolved.

**Environment variables:** Commands can reference environment variables using `${VAR_NAME}`
syntax. The agent will substitute them at runtime. Sensitive values should be in the
environment, not hardcoded in the survival guide.

**Working directory:** All commands run from the repo root unless you specify otherwise.
If your tests must be run from a subdirectory, prefix the command:
```yaml
test: cd packages/api && npm test
```
