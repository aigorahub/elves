# Plan: Exact-HEAD project landing profiles

## Mission

Turn repository-specific landing rituals into tracked, deterministic readiness inputs. Ship a
landable Batch 1 that runs project checks at the exact pull-request head, dogfoods the mechanism on
Elves, and records the post-merge GitHub-release and X-draft follow-through requested by the
operator. Project checks may block readiness but never grant merge, tag, release, or posting
authority.

This plan refines the design drafted with Grok in the main checkout. The untracked source draft is
preserved there; this file is the authoritative acceptance contract for this run.

## Product decisions

- The tracked policy path is `.elves/landing-profile.json`.
- A missing profile is neutral so repositories without one retain generic Elves landing.
- A present invalid profile or a failed blocking check fails closed.
- Results are bound to the exact `HEAD`, resolved base commit, and profile content.
- The runner is generic; this repository's rituals live in its tracked profile.
- Post-merge checklist entries are declarative readiness output. Only the host may execute them
  after independently authorized merge/release actions.
- v2.13.0 is appropriate because this is a new public landing capability.

## Scope

### In scope

- A pure project-profile core plus a thin installed `landing_profile.py check` CLI.
- Minimal schema v1 with deterministic `path_touched` checks, blocking/advisory severity,
  `always`/`any_path_glob` conditions, and declarative `post_merge_checklist` entries.
- Exact-HEAD/base/profile result binding, structured JSON, and stable diagnostics without executing
  profile-directed subprocesses.
- Automatic integration with `elves_landing_check.py` and distinct host-owned project-readiness
  state in `landing_authority.py`.
- Installed Claude/Codex bundle shipment and hermetic regression coverage.
- An Elves dogfood profile for documentation, guide, changelog, and host-parity rituals.
- Repository rules saying an appropriate release-worthy merge is followed by a matching GitHub
  tag/release and a short X announcement draft; drafting never authorizes posting.
- Public/durable docs, v2.13.0 metadata, changelog, guide, and release-checklist alignment.

### Out of scope

- Observation capture, candidate generation, promotion UX, auto-promotion, or learned policy.
- Waivers, global preference keys, free-form LLM rubrics, or expensive-result caching.
- Richer `when` predicates, package publishing, deployment automation, or X posting.
- Executable/`command` profile gates until a later run can require a qualified recursive kernel
  boundary with read-only input, no network/procfs/host-home access, and complete descendant cleanup.
- Any worker ability to set readiness, merge, tag, release, post, mutate protected refs, or edit
  host-owned run memory.

## Build On

- `scripts/elves_landing_check.py` for exact session/plan/evidence validation and final reporting.
- `scripts/cobbler_runtime/landing_authority.py` for host-owned exact-HEAD readiness and invalidation.
- `scripts/release_checklist.py` for structured release findings and JSON output.
- `scripts/sync_installed_skills.py` and installed-bundle smokes for shipment identity.

## Batch 1 [B1]: Ship and dogfood exact-HEAD project landing profiles

**Tasks:**

- [x] Define and validate schema v1; implement deterministic diff selection and result digests.
- [x] Add `path_touched` evaluation and fail closed on executable/`command` profile kinds.
- [x] Integrate live project checks with landing validation and host-owned readiness attestation.
- [x] Ship the CLI/runtime in both installed host bundles with focused and integration tests.
- [x] Track an Elves landing profile and preserve ignored runtime state under `.elves/runtime/`.
- [x] Document the generic contract and Elves' post-merge release/X-draft rules.
- [x] Align the public release as v2.13.0 and run focused plus broad verification.

**Acceptance criteria:**

- [x] [B1-A1] A repository with no landing profile retains generic landing behavior, while a present malformed, symlinked, irregular, oversized, or unsupported profile fails closed with a stable diagnostic.
- [x] [B1-A2] A schema-v1 profile supports deterministic blocking, advisory, skipped, and path-touched outcomes plus declarative post-merge items, rejects executable or command checks as unsupported, and performs no profile-directed subprocess execution.
- [x] [B1-A3] Project results and their canonical digest bind profile bytes, exact `HEAD`, resolved base commit, and normalized check outcomes; a moved head, changed base, changed profile, or stale digest cannot satisfy readiness.
- [x] [B1-A4] Project landing state is a distinct host-evaluated readiness input whose live green/digest cannot be set or overridden by worker reports, and it never grants merge, tag, release, protected-ref, or posting authority.
- [x] [B1-A5] The tracked Elves profile automatically exercises documentation freshness, public-guide freshness, changelog honesty, and Claude/Codex parity on applicable diffs, while preserving generic behavior for projects without a profile.
- [x] [B1-A6] Both installed host bundles contain and can execute the new CLI, focused profile/landing/authority/shipment tests pass, and the canonical repository verifier passes at the exact pull-request head against the immutable base.
- [x] [B1-A7] SKILL, AGENTS, README, guide, changelog, landing references, and durable AI docs align at v2.13.0 and state that an appropriate authorized merge is followed by a matching immutable GitHub tag/release plus a short X announcement draft, never an automatic post.

**Owned surfaces:** `.gitignore`, `.elves/landing-profile.json`, profile runtime/CLI, landing check,
landing authority, focused tests, install shipment/smokes, SKILL, AGENTS, README, CHANGELOG, guide,
landing/schema/runtime references, and durable `.ai-docs` guidance.

**Forbidden surfaces:** observation/promotion machinery, preferences, worker routing, provider
shortcuts, merge methods, protected refs, release/post APIs inside the runner, executable profile
checks, and unrelated TODO items.

**Risk:** high — this changes the exact gate used immediately before merge; review proved arbitrary
profile subprocesses cannot be made safe with string validation or post-hoc mutation checks.

**Review focus:** path/symlink confinement, schema bounds, absence of profile-directed process
launch, deterministic digests, exact-base invalidation, worker immutability, missing-profile
compatibility, installed runtime imports, and authority wording.

**Focused tests:** `tests.test_landing_profile`, `tests.test_elves_landing_check`,
`tests.test_landing_authority`, installed-bundle/sync tests, consistency, release checklist, and
the canonical verifier.

**Depends on:** none.

## Master Acceptance

- [x] [M-A1] The authoritative plan, session, and worker packet retain exact stable-id/criterion parity, and every B1 criterion carries exact-head evidence before landing.
- [x] [M-A2] Independent cumulative and revision-delta review reports no unresolved actionable findings, including security and authority review of project-declared policy.
- [x] [M-A3] The canonical repository verifier and landing check pass on the exact reviewed pull-request head against the unchanged immutable base.
- [x] [M-A4] The pull request is mergeable by a regular merge commit with required checks green, clean worktree identity, and no unresolved review feedback.

## Future roadmap (not acceptance for this run)

Later runs may add observation packets, candidate synthesis, explicit promotion, exact-head waivers,
richer conditions, and host-authorized post-merge helpers. None is required or implied by Batch 1.

## Post-merge completion covenant

After the authorized regular merge commit, if v2.13.0 remains the reviewed release version, create
and verify an immutable `v2.13.0` GitHub tag/release at that merge result, then write a concise X
announcement draft containing the value and release link. Do not post it.

## Non-negotiables

- The user-authorized landing method is a regular merge commit only; never squash or rebase.
- The coordinator owns run memory, PR state, terminal review, merge, release, and X draft.
- The GPT-5.6-high worker owns only the implementation surfaces and its assigned feature branch.
- No profile-directed subprocess execution in schema v1.
- No claim that this run behaviorally qualifies the repo's native-worker prewalk transport.

## Security review amendment

The staged design originally included arbitrary argv checks. Independent review demonstrated a
detached-child escape and showed that environment scrubbing, executable-name blacklists, process
groups, and repository mutation snapshots cannot prevent same-user filesystem reads, network
effects, or post-check descendants. The authoritative B1 contract therefore removes executable
checks instead of documenting an unsafe boundary. A later version may add them only behind a
qualified recursive kernel sandbox; host-run release/consistency verification remains outside the
profile and inside the ordinary reviewed landing ceremony.
