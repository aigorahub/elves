# Validation Guide

## Philosophy

The Ralph Loop only works if the evaluation step is honest. Try, check, feed back, repeat — but if the "check" step lies, the loop converges on garbage. That is why validation is the most important phase.

**The goal of validation is zero accumulated debt.** Every batch must be production-ready before you move to the next one. If you skip a failing test or ignore a build warning, the debt compounds across batches and the final output is far from shippable. The user should return to code that is as close to production-ready as it can reasonably be.

**You are working overnight with no one watching. The tests are the watch.** Without them, you produce code that compiles, passes lint, and does the wrong thing. The test gates are non-negotiable — a batch is not done until they all pass.

---

## The Two-Stage Validation Model

Validation has two stages: **local** and **preview**. Run local checks first — they are fast and catch most problems. If the project has a preview deployment, deploy and smoke-test there before moving on.

**Do not advance to the next batch until both stages pass.**

---

## Stage 1: Local Validation

Run whatever deterministic gates are available. Discover them from the project, or use whatever the user configured in the survival guide under `## Tool Configuration`.

Run these gates **in order** — each catches a different class of problem:

### 1. Lint

Catches style issues, unused imports, and obvious mistakes. This is the fastest gate and the first line of defense. Fix lint errors before running anything else — they often indicate deeper problems.

### 2. Typecheck

Catches type errors, interface mismatches, and missing properties. Type checking prevents entire categories of runtime bugs that would otherwise only surface in production or in end-to-end tests. A batch that type-checks cleanly is substantially more trustworthy than one that doesn't.

### 3. Build

The code must compile or bundle successfully. A batch that doesn't build is not a batch — it cannot be shipped, reviewed, or deployed. Build errors must be fixed before any further validation is meaningful.

### 4. Unit / Integration Tests

Targeted tests for the code you changed. Run the relevant suites, not the entire test suite (unless it's fast). These catch logic errors, edge cases, and regressions in the specific functionality you implemented.

### 5. E2E Tests

If the project has Playwright, Cypress, or a similar framework, run the tests that cover the flows you touched. The app should actually work, not just compile. E2E tests catch integration failures that unit tests miss: broken routes, missing environment variables, UI regressions, and API mismatches.

---

### Auto-Discovery Table

Run what exists, skip what doesn't. If a command is not present in the project, omit it rather than failing:

| Project Type   | Lint                          | Typecheck                      | Build                   | Test                    | E2E                                         |
|----------------|-------------------------------|--------------------------------|-------------------------|-------------------------|---------------------------------------------|
| Node (npm)     | `npm run lint --if-present`   | `npm run typecheck --if-present` | `npm run build --if-present` | `npm test --if-present` | `npx playwright test` (if installed)        |
| Node (pnpm)    | `pnpm lint`                   | `pnpm typecheck`               | `pnpm build`            | `pnpm test`             | `pnpm exec playwright test`                 |
| Python         | `ruff check .`                | `mypy .`                       | —                       | `pytest`                | —                                           |
| Go             | `golangci-lint run`           | (built into compile)           | `go build ./...`        | `go test ./...`         | —                                           |
| Rust           | `cargo clippy`                | (built into compile)           | `cargo build`           | `cargo test`            | —                                           |
| Makefile       | `make lint`                   | `make typecheck`               | `make build`            | `make test`             | `make e2e`                                  |

### User Overrides

**User overrides in the survival guide take precedence over auto-discovery.** If the survival guide specifies a different command for any gate under `## Tool Configuration`, use that command instead of the auto-discovered one.

---

Every gate must pass before proceeding. If a gate fails, fix the issue and re-run **from the failing gate**. Do not skip a gate and plan to come back to it — that is how debt accumulates.

---

## Stage 2: Preview Deployment (if available)

If the project has a preview deployment mechanism (Vercel, Netlify, Railway, a staging server, etc.), deploy after local validation passes and verify the app actually works in a real environment.

The user configures this in the survival guide:

```markdown
### Preview Deployment
- deploy-cmd: `vercel deploy --prebuilt --yes`
- preview-url: (captured from deploy output)
- smoke-tests:
  - `curl -sS -o /dev/null -w "%{http_code}" ${PREVIEW_URL}/`
  - `curl -sS -o /dev/null -w "%{http_code}" ${PREVIEW_URL}/api/health`
```

### What Smoke Tests Should Verify

- The app loads (HTTP 200 on key routes)
- Critical API endpoints respond
- No server errors in the response

If preview deployment is not configured, skip this stage — but note in the execution log that only local validation was performed.

---

## What "Passes" Means

A batch passes validation when **all** of the following are true:

- The code lints cleanly (no errors; pre-existing warnings are acceptable)
- Type checking passes with zero errors
- The build succeeds
- Relevant tests pass
- The app runs and behaves correctly (locally or in preview)
- No new type errors, build warnings, or test failures were introduced

If you introduced a test failure or build warning, fix it before moving on. The next batch inherits everything from this one — debt only grows.

---

## Headless App Testing

For web applications, consider starting the app locally and running E2E tests against it. This catches problems that unit tests miss:

- Broken routes
- Missing environment variables
- UI regressions
- API integration failures

If the project has Playwright or Cypress, use them. If it doesn't, even a basic `curl` against key endpoints after starting the dev server is better than nothing.

The user may also configure visual review (screenshot capture + inspection), simulated user walkthroughs, or custom validation scripts. These all go in the survival guide under `## Tool Configuration` and run as part of this step.

---

## Subagent Delegation for Verbose Suites

For verbose test suites, consider delegating validation to a subagent so the output doesn't flood the coordinator's context window. The subagent runs all gates, captures verbose output, and returns a pass/fail summary with key details. The coordinator evaluates the results without being overwhelmed by raw test output.

Delegate validation when:
- The test suite produces many hundreds of lines of output
- Multiple test frameworks are running in sequence
- E2E tests produce screenshots or trace files

Do not delegate validation when the suite is small and fast — the overhead of spawning a subagent isn't worth it for a 10-second test run.
