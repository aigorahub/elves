# Plan: [Short Descriptive Title]

> A plan is the front end of the Human Sandwich. It's the part where the human decides what is
> worth working on and specifies the problem fully. This is the hardest part of any project and
> it is entirely yours. No AI can tell you what matters. That's your job.
>
> The agent treats this plan as the source of truth for what should be built. Host-native/legacy
> routes read it at the start of every batch and after compaction. A trusted full-run worker carries
> it in the complete packet and its internal loop; the parked host re-reads it only at terminal or
> safety wake. Write it precisely. A half hour spent on a good plan can unlock days of autonomous
> execution and months of equivalent output.
>
> This template shows you how to write a good plan. Replace all `[brackets]` with your content.
> Remove sections that don't apply. The example at the bottom shows a real-ish plan you can use
> as a reference.
>
> The plan is not the launch prompt. Commit this file, point the agent at it by path, and keep
> the later launch prompt short. If you find yourself re-pasting the whole plan into the launch
> prompt, you're overloading the run right when it should be building momentum.
>
> If documentation freshness matters for the project, call it out in the batches. Elves works best
> when the plan makes durable doc upkeep explicit instead of leaving it as invisible cleanup.
>
> If the run has a morning checkpoint, paid compute, or remote jobs, make sure the survival guide
> and launch prompt state those semantics explicitly. Do not make the agent infer whether a time is
> a delivery target or a hard stop.

---

## Mission

[2–3 sentences. What is being built or changed, and why? What does "done" look like from the user's
perspective? Avoid vague language like "improve" or "refactor". Be specific about observable outcomes.]

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

> Explicit out-of-scope items prevent scope creep during unattended runs. Be generous here.
> If in doubt, add it to Out of Scope and let the user re-scope later.

---

## Batches

> Each batch must be independently shippable: code, tests, docs, and passing review.
> Default batch size: what a team of 4 developers would accomplish in a 2-week sprint.
> If a batch feels too large, split it. The agent will also split batches that are too large.
> If a batch is likely to update README, config docs, learnings, or durable agent docs, say so.
>
> **Stable identity:** give each batch a stable `B#` id, each batch criterion a stable
> `B#-A#` id, and each branch-level Master Acceptance criterion a stable `M-A#` id. Never renumber
> an existing id after staging; add a new id instead. `B0` and `B1` are equally valid starts, and
> canonical batch ids are `B0` or `B1` and above—Elves does not reserve or prefer either starting
> convention, and leading-zero aliases are invalid.
> Acceptance rows may use either `- [ ] B0-A1: criterion text` or
> `- [ ] [B0-A1] criterion text`; the two spellings are equivalent, but defining the same id twice
> is still an error. Legacy plans remain readable: map `Batch 1`
> deterministically to `B1`, its nth criterion to `B1-An`, and the nth unlabelled master criterion
> to `M-An`, recording those aliases during reconciliation before claiming completion.
>
> Before any worker launch, staging parses this authoritative plan, reports malformed acceptance
> rows with a targeted replacement, and checks the session plus any worker packet against the
> plan's id-to-criterion mapping. Run the installed `acceptance_contract.py validate` helper;
> `sync-session --write` derives pending batch and Master Acceptance rows without overwriting
> evidence. The staged session also records a non-empty `run_id` and an exact 40-character
> `start_head`, which is the canonical machine-readable collision tripwire. An exact legacy
> `collision_tripwire` may be migrated by `sync-session`; conflicting values block launch.
> Missing, duplicate, or text-mismatched rows block launch. See
> [`schema-and-acceptance.md`](schema-and-acceptance.md) for the final session shape and the
> commit-session, landing-check, cleanup sequence.

### Batch 1 [B1]: [Name]

**Coordinator-to-implementer handoff (required when an external or less-capable worker implements):**

> The per-batch handoff block below always lives in the plan. A **consolidated standalone packet**
> is additionally a **staging deliverable** for any run that might be delegated — written at
> staging with its path recorded in Run Control and `worker_packet_path` (see
> [`schema-and-acceptance.md`](schema-and-acceptance.md)). The two are not substitutes. For a
> machine-checked cold handoff, explicitly opt into handoff v1 by recording the session `handoff`
> object and the matching leading Markdown or JSON packet capsule. Omit both to retain the v2.8
> advisory path; a capsule is not exact-session prewalk evidence.

- **Intent / why:** [why this batch exists]
- **Non-obvious rationale:** [architecture choices the worker must not rediscover from chat]
- **Build On targets:** [existing utilities/patterns to extend]
- **Owned surfaces:** [files/modules the worker may edit]
- **Forbidden surfaces:** [run memory, `.git`, credentials, other worktrees, out-of-scope paths]
- **Acceptance evidence:** [observable criteria with proof — not “make tests green”]
- **Failure modes / pitfalls:** [tool/version gotchas and recovery]
- **HEAD / run-doc paths / route-session identity / output format:** [tip, plan/survival/log paths, exact session if routed, handoff shape]

**Tasks:**
- [ ] [Specific implementable task]
- [ ] [Specific implementable task]
- [ ] [Specific implementable task]

**Acceptance criteria:**
- [ ] B1-A1: [Verifiable criterion. Should be checkable by running a command or reading a file.]
- [ ] [B1-A2] [Verifiable criterion]
- [ ] B1-A3: [Verifiable criterion]
- [ ] [B1-A4] [If this batch changes existing behavior, include one criterion that proves old behavior still works]
- [ ] [B1-A5] [If this batch splits a large/god file: include a measurable bar (LOC, facade boundary, module count) — structure/regex lock tests alone do not complete the batch unless you explicitly allow characterization-only here]

**Progress commits (Git history as operator UI):** on host-native/legacy routes, the host pushes
meaningful slices using `[<branch> · Batch N/total · Contract|Implement|Validate|Review|Close]
<concrete outcome>`. On trusted full-run, the exact registered `branch_progress` worker uses the
same schema only on its assigned feature branch while the host parks. Untrusted workers create only
audited detached handoff commits and never own refs/remotes/push/PR/run-memory. Protected refs, PR
actions, canonical memory, final review, and merge stay host-owned. Forbid vague subjects
(`Updates`, `progress`, `WIP`, bare `fixes`); `Close` requires acceptance evidence.

**Docs likely touched:**
- [README / config docs / learnings / `.ai-docs/*` / "none expected"]

**Risk:** `low` | `standard` | `high` — [one sentence on what is most uncertain]
**Caution:** [non-obvious trap; omit only if truly none]
**Affected surfaces:** [modules/files/packages this batch may change]
**Constitution impacts:** [flows/invariants at risk, or "none"]
**Review focus:** [what the terminal reviewer should scrutinize]
**Focused tests:** [modules or scenarios that prove this batch]
**Depends on:** [batch ids, or "none"]

> Plans express intent and acceptance — not implementation choreography. Elves records each
> completed criterion in `.elves-session.json` as
> `acceptance: [{id: "B1-A1", criterion, met, evidence}]`. Green tests without these stable-id proof
> rows do not make the batch landable. The legacy schema shorthand
> `acceptance: [{criterion, met, evidence}]` remains readable through deterministic stable-id alias
> mapping; new plans must write the ids explicitly. The staged session criterion text and any
> full-run packet criterion text must match the parsed plan row for that id before launch.

---

### Batch 2 [B2]: [Name]

**Tasks:**
- [ ] [Specific implementable task]
- [ ] [Specific implementable task]

**Acceptance criteria:**
- [ ] [B2-A1] [Verifiable criterion]
- [ ] [B2-A2] [Verifiable criterion]
- [ ] [B2-A3] [If this batch changes existing behavior, include one regression-preservation check]
- [ ] [B2-A4] [If this is a split/god-file batch: measurable size/facade criterion, not only structure locks]

**Docs likely touched:**
- [README / config docs / learnings / `.ai-docs/*` / "none expected"]

**Risk:** `low` | `standard` | `high` — [one sentence]
**Caution:** [trap or "none"]
**Affected surfaces:** [list]
**Constitution impacts:** [list or "none"]
**Review focus:** [list]
**Focused tests:** [list]
**Depends on:** [ids or "none"]

---

### Batch 3 [B3]: [Name]

**Tasks:**
- [ ] [Specific implementable task]
- [ ] [Specific implementable task]

**Acceptance criteria:**
- [ ] [B3-A1] [Verifiable criterion]
- [ ] [B3-A2] [Verifiable criterion]
- [ ] [B3-A3] [If this batch changes existing behavior, include one regression-preservation check]

**Docs likely touched:**
- [README / config docs / learnings / `.ai-docs/*` / "none expected"]

**Risk:** `low` | `standard` | `high` — [one sentence]
**Caution:** [trap or "none"]
**Affected surfaces:** [list]
**Constitution impacts:** [list or "none"]
**Review focus:** [list]
**Focused tests:** [list]
**Depends on:** [ids or "none"]

---

> Add more batches as needed. Keep them in dependency order. Later batches can depend on earlier
> ones, but try to minimize inter-batch dependencies.

---

## Master Acceptance

> Branch-level outcomes use stable `M-A#` ids. These are not duplicates of batch gates: they prove
> the whole run is landable. Legacy unlabelled Master Acceptance rows map deterministically by
> document order (`M-A1`, `M-A2`, …) and retain that alias once recorded.

- [ ] [M-A1] [Observable end-to-end outcome for the whole plan]
- [ ] [M-A2] [Cumulative regression/readiness outcome]
- [ ] [M-A3] [Documentation, migration, or operator outcome]

---

## Lanes

> Optional. Omitting this section means serial (the default). When present, it declares
> Parallelves lanes (`references/parallelves.md`): the machine grammar is the fenced yaml-shaped
> block below — a `lanes:` list where each lane carries `id`, `name`, `depends_on`,
> `owned_surfaces`, and `batches`, plus a `trunk:` batch list built serially before lanes fork.
> Declaring lanes never launches anything: `worker.parallel=auto` may only recommend them when
> the width test passes, and every decline records a concrete reason.

```yaml
trunk:
  - B1
lanes:
  - id: L1
    name: Validator core
    depends_on: []
    owned_surfaces:
      - scripts/validator/
      - tests/test_validator.py
    batches:
      - B2
  - id: L2
    name: Docs and template
    depends_on: []
    owned_surfaces:
      - docs/validator.md
    batches:
      - B3
```

---

## Non-Negotiables

> The agent treats these as hard constraints. Violations are never acceptable regardless of
> how they might otherwise speed up the work. Keep this list short (3–6 items maximum).
> Long non-negotiable lists are either over-specified or contain things that are really just
> preferences, not rules.

- [Hard constraint, e.g., "Never modify the public REST API response shapes"]
- [Hard constraint, e.g., "All commits must pass lint and typecheck"]
- [Hard constraint, e.g., "Do not install new dependencies without noting them in Decisions made"]
- The user owns whether Elves may merge. Default is user-merges; merge-on-green or an explicit
  reviewed-PR landing command (`\land-pr` or `/land-pr`) is the only opt-in. In either opt-in path,
  Elves lands a regular merge commit (never a squash) only after final readiness.

---

## Test Strategy

> Tell the agent which tests matter most and how to run them. If you have a preferred test
> isolation strategy (e.g., always run unit tests only, never integration tests), say so here.

- **Primary gate:** [e.g., "All unit tests: `npm test`"]
- **Secondary gate (if applicable):** [e.g., "Integration tests: `npm run test:integration`"]
- **E2E (if applicable):** [e.g., "Playwright: `npx playwright test`"]
- **Minimum coverage threshold (if applicable):** [e.g., "Must not decrease coverage below 80%"]
- **Known flaky tests (skip or ignore):** [e.g., "`tests/integration/email.test.ts` (mocks SMTP, unreliable in CI)"]
- **Durable doc expectations (if applicable):** [e.g., "Promote reusable lessons to learnings; update `.ai-docs/gotchas.md` when a hidden dependency is discovered"]

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
- [If the run uses a checkpoint, pods, remote jobs, or long-lived servers, note that the survival guide must state checkpoint semantics, actual stop conditions, and active compute explicitly]
- [If the repo should become more AI-friendly during the run, say what "better context" means here]

---
---

# EXAMPLE: Auth System Refactor

> Below is a complete, filled-in example of what a good plan looks like.
> This is for reference only. Delete everything from this line down before handing your plan to the agent.

---

## Mission

Replace the server-side session-cookie authentication system with short-lived JWT access tokens
(15-minute TTL) plus rotating refresh tokens (7-day TTL, stored in Redis). All 142 existing auth
tests must pass unchanged. The public `/api/*` request and response shapes must not change.
Only the internal token mechanics change.

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

### Batch 1 [B1]: JWT Core

**Tasks:**
- [ ] Add `jsonwebtoken` and `ioredis` dependencies
- [ ] Implement `src/auth/jwt.ts`: sign, verify, decode helpers with configurable TTL
- [ ] Implement `src/auth/refresh.ts`: issue, rotate, revoke refresh tokens in Redis
- [ ] Unit tests for all new functions (target: 95% coverage of new files)

**Acceptance criteria:**
- [ ] [B1-A1] `npm test -- --testPathPattern=auth/jwt` passes
- [ ] [B1-A2] `npm test -- --testPathPattern=auth/refresh` passes
- [ ] [B1-A3] `npm run typecheck` passes
- [ ] [B1-A4] No new lint errors

**Risk:** Redis availability in CI. If Redis isn't available, integration tests will fail.
Check `.github/workflows/` for a Redis service container before starting.

---

### Batch 2 [B2]: Middleware Swap

**Tasks:**
- [ ] Update `src/middleware/authenticate.ts` to accept `Authorization: Bearer <token>` header
- [ ] Keep backward-compatible session-cookie fallback behind `AUTH_LEGACY=true` env flag
- [ ] Update `src/routes/auth.ts`: `/login` returns JWT + sets refresh token cookie
- [ ] Update `src/routes/auth.ts`: `/refresh` endpoint returns new access token

**Acceptance criteria:**
- [ ] [B2-A1] All 142 existing auth tests pass: `npm test -- --testPathPattern=auth`
- [ ] [B2-A2] Manual smoke: `curl -H "Authorization: Bearer <token>" http://localhost:3000/api/me` returns 200
- [ ] [B2-A3] `AUTH_LEGACY=true npm test` also passes (backward compat verified)

**Risk:** The fallback flag adds conditional complexity. Ensure it doesn't bleed into production
paths. Review carefully.

---

### Batch 3 [B3]: Cleanup and Docs

**Tasks:**
- [ ] Remove old session-store code from `src/lib/session.ts` (keep file, just remove session logic)
- [ ] Update `docs/auth.md` with new token lifecycle diagram
- [ ] Add `AUTH_LEGACY` flag documentation to `docs/configuration.md`
- [ ] Mark old session-related env vars as deprecated in `.env.example`

**Acceptance criteria:**
- [ ] [B3-A1] Full test suite passes: `npm test`
- [ ] [B3-A2] `docs/auth.md` accurately describes the new token flow
- [ ] [B3-A3] No references to removed session functions remain in non-legacy code paths

**Risk:** Low. Documentation and cleanup only.

---

## Master Acceptance

- [ ] [M-A1] JWT login, refresh, and authenticated API access work end-to-end.
- [ ] [M-A2] Existing auth behavior remains available under `AUTH_LEGACY=true` with all 142 tests.
- [ ] [M-A3] Public `/api/*` shapes are unchanged and operator documentation is current.

---

## Non-Negotiables

- Never modify the public `/api/*` response shapes
- All commits must pass `npm run lint` and `npm run typecheck`
- Do not install new dependencies without noting them in **Decisions made** in the execution log
- Do not touch the password reset flow or OAuth routes. Those are in a separate project.
- The user owns whether Elves may merge. Default is user-merges; opt-ins are merge-on-green or the
  reviewed-PR landing command (`\land-pr` or `/land-pr`), both after final readiness.

---

## Test Strategy

- **Primary gate:** `npm test` (Jest, unit + integration)
- **E2E:** Not applicable for this change. API shape is unchanged.
- **Minimum coverage:** Must not decrease below current 78%
- **Known flaky:** `tests/integration/email.test.ts`. Skip with `--testPathIgnorePatterns=email`.

---

## Notes

- Redis is available in dev via `docker-compose up redis`. CI has a Redis service container configured.
- The `ioredis` mock library is already installed as a dev dependency (`ioredis-mock`)
- JWT secret is already in `.env.example` as `JWT_SECRET`. Do not hardcode.
- Refresh token cookie name should be `__Host-refresh` for security (prefix enforces Secure + no domain)


<!-- v2.3 risk/proof policy pins -->
- thin safety kernel; risk low|standard|high independent of trust trusted|untrusted
- validate once, verify changes, attest final
- impact-selected proof during work; broad proof once at terminal readiness and explicit high-risk checkpoints
- mid-run nonblocking new/unresolved PR feedback; terminal waits for required checks
