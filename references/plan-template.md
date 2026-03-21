# Plan: [Short Descriptive Title]

> A plan is the front end of the Human Sandwich — the part where the human decides what is worth
> working on and specifies the problem fully. This is the hardest part of any project and it is
> entirely yours. No AI can tell you what matters. That's your job.
>
> The agent treats this plan as the source of truth for what should be built. It is read at the
> start of every batch and after every compaction. Write it precisely. A half hour spent on a
> good plan can unlock days of autonomous execution and months of equivalent output.
>
> This template shows you how to write a good plan. Replace all `[brackets]` with your content.
> Remove sections that don't apply. The example at the bottom shows a real-ish plan you can use
> as a reference.

---

## Mission

[2–3 sentences. What is being built or changed, and why? What does "done" look like from the user's
perspective? Avoid vague language like "improve" or "refactor" — be specific about observable outcomes.]

Example:
> Refactor the authentication layer to use short-lived JWTs (15m access tokens + 7d refresh tokens),
> replacing the current server-side session-cookie approach. All 142 existing auth tests must pass.
> The public `/api/*` request/response shapes must not change.

---

## Scope

### In Scope
- [Specific thing that will change]
- [Specific thing that will change]
- [Specific thing that will change]

### Out of Scope
- [Thing that will NOT be touched, even if it seems related]
- [Thing that will NOT be touched]
- [Thing that will NOT be touched]

> Explicit out-of-scope items prevent scope creep during unattended runs. Be generous here —
> if in doubt, add it to Out of Scope and let the user re-scope later.

---

## Batches

> Each batch must be independently shippable: code, tests, docs, and passing review.
> Default batch size: what a team of 4 developers would accomplish in a 2-week sprint.
> If a batch feels too large, split it. The agent will also split batches that are too large.

### Batch 1: [Name]

**Tasks:**
- [ ] [Specific implementable task]
- [ ] [Specific implementable task]
- [ ] [Specific implementable task]

**Acceptance criteria:**
- [ ] [Verifiable criterion — should be checkable by running a command or reading a file]
- [ ] [Verifiable criterion]
- [ ] [Verifiable criterion]

**Risk:** [One sentence — what is most likely to go wrong, or what has the highest uncertainty?]

---

### Batch 2: [Name]

**Tasks:**
- [ ] [Specific implementable task]
- [ ] [Specific implementable task]

**Acceptance criteria:**
- [ ] [Verifiable criterion]
- [ ] [Verifiable criterion]

**Risk:** [One sentence]

---

### Batch 3: [Name]

**Tasks:**
- [ ] [Specific implementable task]
- [ ] [Specific implementable task]

**Acceptance criteria:**
- [ ] [Verifiable criterion]
- [ ] [Verifiable criterion]

**Risk:** [One sentence]

---

> Add more batches as needed. Keep them in dependency order — later batches can depend on earlier
> ones, but try to minimize inter-batch dependencies.

---

## Non-Negotiables

> The agent treats these as hard constraints. Violations are never acceptable regardless of
> how they might otherwise speed up the work. Keep this list short — 3–6 items maximum.
> Long non-negotiable lists are either over-specified or contain things that are really just
> preferences, not rules.

- [Hard constraint — e.g., "Never modify the public REST API response shapes"]
- [Hard constraint — e.g., "All commits must pass lint and typecheck"]
- [Hard constraint — e.g., "Do not install new dependencies without noting them in Decisions made"]
- The agent never merges. The PR is for the user to review and merge on return.

---

## Test Strategy

> Tell the agent which tests matter most and how to run them. If you have a preferred test
> isolation strategy (e.g., always run unit tests only, never integration tests), say so here.

- **Primary gate:** [e.g., "All unit tests — `npm test`"]
- **Secondary gate (if applicable):** [e.g., "Integration tests — `npm run test:integration`"]
- **E2E (if applicable):** [e.g., "Playwright — `npx playwright test`"]
- **Minimum coverage threshold (if applicable):** [e.g., "Must not decrease coverage below 80%"]
- **Known flaky tests (skip or ignore):** [e.g., "`tests/integration/email.test.ts` — mocks SMTP, unreliable in CI"]

---

## Batch Sizing

> Remove this section to use the default (4 devs × 2 weeks).

```yaml
team-size: [N]
sprint-length: [N weeks]
```

---

## Notes

> Anything else the agent needs to know. Context about the codebase, known gotchas, design
> decisions already made, external dependencies, environment setup, links to relevant docs.

- [Note 1]
- [Note 2]
- [Note 3]

---
---

# EXAMPLE: Auth System Refactor

> Below is a complete, filled-in example of what a good plan looks like.
> This is for reference only — delete everything from this line down before handing your plan to the agent.

---

## Mission

Replace the server-side session-cookie authentication system with short-lived JWT access tokens
(15-minute TTL) plus rotating refresh tokens (7-day TTL, stored in Redis). All 142 existing auth
tests must pass unchanged. The public `/api/*` request and response shapes must not change —
only the internal token mechanics change.

---

## Scope

### In Scope
- New JWT issuance, verification, and refresh logic in `src/auth/`
- Redis integration for refresh token storage and rotation
- Middleware update to accept Bearer tokens instead of session cookies
- Update all auth-related unit and integration tests

### Out of Scope
- Password reset flow (separate project)
- OAuth / social login (not touched)
- Frontend changes (the API shape is unchanged, so frontend requires no updates)
- Admin user impersonation feature

---

## Batches

### Batch 1: JWT Core

**Tasks:**
- [ ] Add `jsonwebtoken` and `ioredis` dependencies
- [ ] Implement `src/auth/jwt.ts` — sign, verify, decode helpers with configurable TTL
- [ ] Implement `src/auth/refresh.ts` — issue, rotate, revoke refresh tokens in Redis
- [ ] Unit tests for all new functions (target: 95% coverage of new files)

**Acceptance criteria:**
- [ ] `npm test -- --testPathPattern=auth/jwt` passes
- [ ] `npm test -- --testPathPattern=auth/refresh` passes
- [ ] `npm run typecheck` passes
- [ ] No new lint errors

**Risk:** Redis availability in CI — if Redis isn't available, integration tests will fail.
Check `.github/workflows/` for a Redis service container before starting.

---

### Batch 2: Middleware Swap

**Tasks:**
- [ ] Update `src/middleware/authenticate.ts` to accept `Authorization: Bearer <token>` header
- [ ] Keep backward-compatible session-cookie fallback behind `AUTH_LEGACY=true` env flag
- [ ] Update `src/routes/auth.ts` — `/login` returns JWT + sets refresh token cookie
- [ ] Update `src/routes/auth.ts` — `/refresh` endpoint returns new access token

**Acceptance criteria:**
- [ ] All 142 existing auth tests pass: `npm test -- --testPathPattern=auth`
- [ ] Manual smoke: `curl -H "Authorization: Bearer <token>" http://localhost:3000/api/me` returns 200
- [ ] `AUTH_LEGACY=true npm test` also passes (backward compat verified)

**Risk:** The fallback flag adds conditional complexity — ensure it doesn't bleed into production
paths. Review carefully.

---

### Batch 3: Cleanup and Docs

**Tasks:**
- [ ] Remove old session-store code from `src/lib/session.ts` (keep file, just remove session logic)
- [ ] Update `docs/auth.md` with new token lifecycle diagram
- [ ] Add `AUTH_LEGACY` flag documentation to `docs/configuration.md`
- [ ] Mark old session-related env vars as deprecated in `.env.example`

**Acceptance criteria:**
- [ ] Full test suite passes: `npm test`
- [ ] `docs/auth.md` accurately describes the new token flow
- [ ] No references to removed session functions remain in non-legacy code paths

**Risk:** Low — documentation and cleanup only.

---

## Non-Negotiables

- Never modify the public `/api/*` response shapes
- All commits must pass `npm run lint` and `npm run typecheck`
- Do not install new dependencies without noting them in **Decisions made** in the execution log
- Do not touch the password reset flow or OAuth routes — those are in a separate project
- The agent never merges. PR is for user review.

---

## Test Strategy

- **Primary gate:** `npm test` (Jest, unit + integration)
- **E2E:** Not applicable for this change — API shape is unchanged
- **Minimum coverage:** Must not decrease below current 78%
- **Known flaky:** `tests/integration/email.test.ts` — skip with `--testPathIgnorePatterns=email`

---

## Notes

- Redis is available in dev via `docker-compose up redis` — CI has a Redis service container configured
- The `ioredis` mock library is already installed as a dev dependency (`ioredis-mock`)
- JWT secret is already in `.env.example` as `JWT_SECRET` — do not hardcode
- Refresh token cookie name should be `__Host-refresh` for security (prefix enforces Secure + no domain)
