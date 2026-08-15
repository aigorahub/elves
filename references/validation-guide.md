# Validation Guide

## Philosophy

The Ralph Loop only works if the evaluation step is honest. Try, check, feed back, repeat. If the
check step lies, the loop converges on garbage.

**Proof budget:** **validate once, verify changes, attest final** (see
`references/proof-and-review.md`).

- **Mid-run (ordinary batches):** prove this batch's acceptance with the **impact path**
  (changed surface → affected consumer → selected tests). Fix **blockers** only.
- **Terminal readiness (and explicit high-risk checkpoints):** broad / full suite proof, then
  drain **deferred hygiene**.
- **Never** weaken, skip, or delete tests merely to obtain green.

**Correctness debt vs polish debt.** Mid-run you must not leave red impact tests, broken
build/typecheck on touched surfaces, unmet acceptance, or security/data-integrity failures. You
**may** bank advisory nits (style, naming, drive-by docs polish, unrelated warnings) as deferred
hygiene and continue to the next planned batch. That is not "ship broken code." It is separating
blockers from polish so overnight runs do not re-run the world after every small change.

**You are working overnight with no one watching.** Impact tests and acceptance evidence are the
watch mid-run. The full suite and cumulative review are the watch at the end.

---

## Mid-run vs terminal

| Phase | Proof | Review | Polish / nits |
|-------|--------|--------|----------------|
| Ordinary batch (low/standard risk) | Impact path + build/typecheck on touched work | No nested full product review; contract walk for this batch only | Queue as **Deferred hygiene** |
| High-risk checkpoint (plan-named, security, data, shared kernel) | Broader proof as planned | Still fix blockers only unless plan says otherwise | Still queue pure advisories when safe |
| Terminal readiness | Full suite (or project full gate) + readiness checklist | One cumulative review → consolidate blockers → revise → **delta** re-review only | Drain deferred hygiene that is still true |

**Do not** re-run the full suite between ordinary batches when impact tests are green and the suite
is large. **Do** re-run from the failing impact gate when a blocker fails.

Trusted full-run workers follow the same split internally; the parked host does **not** add a
per-batch driver review on a healthy run.

---

## Deferred hygiene

When you see a non-blocking issue mid-run:

1. Record one line under **Deferred hygiene** in the survival guide and/or execution-log Run Digest
   (surface, what, why advisory).
2. Do **not** start a polish sub-project mid-batch.
3. At terminal readiness (or an explicit hygiene batch), re-check the queue, fix what still matters,
   drop what is obsolete, and clear the list with evidence.

**Always blocking (never defer):**

- Failing impact / acceptance tests for the current batch
- Build or typecheck failures on touched surfaces and their impact-path consumers
- Security or data-integrity defects
- Unmet plan acceptance criteria for the batch
- Constitution FAIL

**Usually deferred:**

- Style and naming nits outside acceptance
- Pre-existing warnings not introduced as errors
- Untouched-surface "improvements"
- Second full review of already settled batches
- Full-repo suite when impact path is green

---

## The Two-Stage Validation Model

Validation has two stages: **local** and **preview**. Run local checks first. If the project has a
preview deployment, use it when the impact path or terminal phase requires runtime proof.

**Do not advance to the next batch while mid-run blockers remain.** Preview is required only when
configured and when the batch's acceptance or risk needs it; it is not a license to re-validate the
entire product every batch.

---

## Stage 1: Local Validation

Run whatever deterministic gates are available. Discover them from the project, or use whatever the
user configured in the survival guide under `## Tool Configuration`.

### Mid-run gate order (impact path)

1. **Lint / typecheck / build** on touched work (or project-equivalent) when they are cheap signals
   for this change. Fix errors that block the batch. Pre-existing warnings may be deferred if they
   are not new blockers.
2. **Selected unit / integration tests** for the code you changed and its consumers. Prefer the
   relevant suites, not the entire test suite, unless the suite is small or the plan requires full.
3. **E2E / browser** only when the user explicitly asked, or configured an `e2e:` gate in the
   survival guide. Last resort. Never block a run. Prefer the flows they named, not every
   browser project. Skip host-browser and Playwright MCP tools unless asked.

### Terminal / high-risk gate order

Run the full project gate set (lint, typecheck, build, full test, E2E as configured), then preview
smoke if configured, then drain deferred hygiene.

### Auto-Discovery Table

Run what exists, skip what doesn't. If a command isn't present in the project, omit it rather than
failing:

| Project Type   | Lint                          | Typecheck                      | Build                   | Test                    | E2E                                         |
|----------------|-------------------------------|--------------------------------|-------------------------|-------------------------|---------------------------------------------|
| Node (npm)     | `npm run lint --if-present`   | `npm run typecheck --if-present` | `npm run build --if-present` | `npm test --if-present` | only if the user configured `e2e:` or asked |
| Node (pnpm)    | `pnpm lint`                   | `pnpm typecheck`               | `pnpm build`            | `pnpm test`             | only if the user configured `e2e:` or asked |
| Python         | `ruff check .`                | `mypy .`                       | (none)                  | `pytest`                | (none)                                      |
| Go             | `golangci-lint run`           | (built into compile)           | `go build ./...`        | `go test ./...`         | (none)                                      |
| Rust           | `cargo clippy`                | (built into compile)           | `cargo build`           | `cargo test`            | (none)                                      |
| Makefile       | `make lint`                   | `make typecheck`               | `make build`            | `make test`             | only if the user configured `e2e:` or asked |

### User Overrides

**User overrides in the survival guide take precedence over auto-discovery.** If the survival guide
specifies a different command for any gate under `## Tool Configuration`, use that command instead
of the auto-discovered one.

---

If a **blocker** gate fails, fix the issue and re-run **from the failing gate**. Do not skip a
blocker and plan to come back later. Advisory failures go to deferred hygiene.

---

## Stage 2: Preview Deployment (if available)

If the project has a preview deployment mechanism (Vercel, Netlify, Railway, a staging server, etc.),
deploy when acceptance or risk requires runtime proof (often terminal or high-risk batches) and
verify the app works in a real environment.

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

If preview deployment isn't configured, skip this stage. Note in the execution log that only local
validation was performed.

---

## What "Passes" Means Mid-Run

An ordinary batch passes validation when **all** of the following are true:

- Impact-path tests for this batch's acceptance are green
- Touched surfaces and their impact-path consumers typecheck/build (or project equivalent) without new blockers
- Plan acceptance criteria for this batch are met with evidence
- No new security/data-integrity defects
- Advisory nits are either fixed or recorded under **Deferred hygiene**

It does **not** require a green full-repo suite, zero pre-existing warnings, or a nested full product
review.

## What "Passes" Means at Terminal Readiness

- Full suite (or configured full gate) green on the current tip
- Deferred hygiene drained or explicitly waived with reason
- Cumulative review clean of blockers (delta re-review only after revision)
- Landing / readiness checklist items for the run

---

## Headless App Testing

Do not open a host browser or run Playwright/Cypress unless the user explicitly asked. Browser
checks never block a run. Prefer unit/integration tests and `curl` against key endpoints.

If the user asked for browser proof, or configured an `e2e:` command under `## Tool Configuration`,
run only that named gate. Treat missing browsers, failed visual checks, or skipped E2E as advisory
unless the user also made that proof an acceptance criterion — and even then, record unavailability
honestly rather than stalling launch or landing.

---

## Subagent Delegation for Verbose Suites

For verbose test suites, consider delegating validation to a subagent so the output doesn't flood
the coordinator's context window. The subagent runs the selected (mid-run) or full (terminal)
gates, captures verbose output, and returns a pass/fail summary with key details.

Delegate validation when:

- The test suite produces many hundreds of lines of output
- Multiple test frameworks are running in sequence
- E2E tests produce screenshots or trace files

Don't delegate validation when the suite is small and fast.
