# Plan: Provider convenience shortcuts

## Mission

Ship host-honest Fugu, Manus, Grok, and Devin convenience routes for Claude Code and Codex. The
routes must use documented provider transports, preserve Elves' authority and isolation boundaries,
return bounded results, and be fully inspectable through installed skill files and public docs.

## Scope

### In scope

- Installed runner scripts and Claude aliases for all four providers.
- Codex `$elves …` and natural-language parity without invented top-level slash commands.
- Project-aware, isolated Fugu and Grok execution; bounded Manus and Devin remote execution.
- Manus roster orchestration and a reliable project-aware Fugu Ultra review profile.
- Hermetic regression coverage, task guide, reference, adapter, and changelog updates.

### Out of scope

- Making any paid provider the default Elves worker.
- Granting merge, protected-ref, approval-bypass, connector, secret, or knowledge authority.
- Claiming control over undocumented Manus internal subagent topology.

## Batch 1 [B1]: Implement and harden provider shortcuts

**Tasks:**

- [x] Implement installed provider runners and host-specific invocation surfaces.
- [x] Harden filesystem, credential, timeout, resume, and paid-task recovery boundaries.
- [x] Align Claude/Codex documentation and add hermetic transport and isolation tests.
- [x] Prove the project-aware Fugu Ultra route with the real `codex-fugu` CLI.

**Acceptance criteria:**

- [x] [B1-A1] Claude and Codex expose host-honest Fugu, Manus, Grok, and Devin shortcuts that resolve installed runners without inventing Codex slash commands.
- [x] [B1-A2] Fugu regular, deep, and Ultra profiles use official codex-fugu with tracked-source filesystem and credential isolation; Ultra completes through bounded exact-session synthesis.
- [x] [B1-A3] Manus ordinary, Wide-first, deterministic fan-out, attachment, and duplicate-safe resume flows use official bounded private v2 tasks with exact roster coverage.
- [x] [B1-A4] Grok and Devin use documented CLI or API surfaces with bounded non-bypass execution and explicit secret and knowledge constraints.
- [x] [B1-A5] Hermetic shortcut, isolation, installation, and supported-Python tests cover success, failure, timeout, and stale-state paths.
- [x] [B1-A6] README, guide, changelog, SKILL, AGENTS, host-parity, aliases, and shortcut reference remain aligned for Claude and Codex.

**Docs likely touched:** README, guide, changelog, SKILL, AGENTS, provider reference, host parity,
and Claude aliases.

**Risk:** high — provider-directed tooling combines paid external execution, project context, and
credential-bearing launchers.

**Review focus:** command correctness, exact timeout accounting, paid-task duplication, credential
projection, tracked-source isolation, and Claude/Codex parity.

**Focused tests:** `tests.test_provider_shortcuts`, `tests.test_dispatch_isolation`,
`tests.test_storage_isolation_git`, installed-bundle smokes, consistency, and the canonical verifier.

**Depends on:** none.

## Master Acceptance

- [ ] [M-A1] The canonical repository verifier passes on the exact pull-request head against the immutable pull-request base.
- [ ] [M-A2] Independent cumulative and revision-delta review reports no unresolved actionable findings.
- [ ] [M-A3] The pull request is mergeable by a regular merge commit with current required checks green, an unchanged base, and a clean exact-head worktree.

## Non-negotiables

- Optional provider calls never broaden Elves landing or protected-ref authority.
- Credential-bearing launchers and model-directed tools remain separated by explicit isolation.
- Paid remote mutations never retry after an ambiguous response without durable reconciliation.
- The user alone authorizes the final regular merge commit.
