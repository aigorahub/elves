# Plan: General Fugu tasks and explicit review mode

## Mission

Make Fugu a general Elves provider route instead of an always-review shortcut. “Use Fugu” should
delegate the requested task with task-appropriate output and host-selected safe context, while
“Fugu review” should retain the opinionated, read-only repository-review contract. Fugu may work
only inside a disposable kernel-isolated workspace and never receives host Git, credential,
protected-ref, PR, release, or landing authority.

## Product decisions

- Provider selection and task type are independent: Fugu is the provider; general, review, and
  isolated-write are task capabilities.
- General Fugu tasks are read-only unless the surrounding user request independently authorizes
  implementation and the host selects the isolated-write route.
- Review mode remains read-only and retains change/base evidence, severity ordering, exact
  file/line findings, and the explicit clean verdict.
- Safe non-ignored worktree context, including untracked source, is eligible by default. The host
  may add exact relevant paths, but the safety kernel remains the final admissibility check.
- Fugu never edits the host checkout. Isolated-write output is exported as a bounded, audited
  handoff for host inspection and import.
- This public capability is released as v2.15.0.

## Scope

### In scope

- Distinct general-task and explicit-review invocation grammar for Claude, Codex, natural language,
  and the installed runner.
- Task-appropriate general prompts without review-only severity or verdict requirements.
- Safe non-ignored untracked context and bounded host-selected exact-path context.
- Read-only review/general lanes plus an explicitly selected writable disposable lane whose result
  is exported without mutating the host checkout.
- Stable output auditing for unsafe paths, symlinks, special files, hard links, policy exclusions,
  and size/count limits.
- Preservation of the qualified macOS/Linux kernel boundary, credential projection, no-procfs
  protection, bounded process cleanup, and host-only Git/landing authority.
- Focused, isolation, installed-bundle, documentation, guide, changelog, and v2.15.0 release proof.

### Out of scope

- Direct provider writes to the host checkout.
- Provider commits, pushes, branches, PR actions, merges, tags, releases, social posting, secrets,
  approval bypasses, or protected-ref access.
- Automatically applying a Fugu handoff without host inspection.
- Broad inclusion of ignored dependency, cache, build, environment, or credential trees.
- Turning Fugu into the default Elves implementation worker.

## Build On

- `scripts/run_fugu.sh` for launcher profiles, prompts, hard deadlines, and exact-session Ultra
  synthesis.
- `scripts/cobbler_runtime/isolation.py` for secure snapshot construction and qualified kernel
  boundaries.
- `tests/test_provider_shortcuts.py` and `tests/test_dispatch_isolation.py` for transport and
  filesystem regression proof.
- `scripts/sync_installed_skills.py`, installed-bundle smoke tests, repository consistency, and
  the release checklist for public shipment.

## Batch 1 [B1]: Separate general tasks from review and safely widen Fugu capability

**Coordinator-to-implementer handoff:**

- **Intent / why:** Let users select Fugu for investigation, design, implementation, and other
  bounded repository tasks without forcing every response through the review rubric.
- **Non-obvious rationale:** Snapshot breadth is not prompt-token consumption; relevance belongs
  to the host/Fugu agents while immutable exclusions and kernel isolation belong to the safety
  layer. Writable work must remain disposable and cross back only as audited evidence.
- **Build On targets:** the existing Fugu runner, shared isolation utilities, provider shortcut
  tests, installed bundle shipment, and public docs.
- **Owned surfaces:** Fugu runner, narrowly shared isolation support, provider shortcut/isolation
  tests, SKILL/AGENTS/README/guide/changelog/provider references, release metadata, and durable
  provider guidance.
- **Forbidden surfaces:** real-checkout provider writes, worker/landing authority, unrelated
  providers, credentials, protected refs, PR/merge/release/post actions, and unrelated roadmap work.
- **Acceptance evidence:** focused hermetic provider tests, sandbox escape/write tests, exact
  invocation/prompt assertions, bounded handoff tests, installed smokes, consistency/release
  checks, canonical verifier, Fugu terminal review, and independent cumulative review.
- **Failure modes / pitfalls:** prompt wording that still forces review, silently missing untracked
  files, ignored secret inclusion, symlink/hard-link output attacks, writable macOS/Linux boundary
  drift, unbounded output, Ultra synthesis losing task identity, or host mutation before review.
- **HEAD / run docs / route identity / output:** start at
  `1d90246b97b5e11211525e71b6a9ff5091c6cc10` on `codex/fugu-general-tasks`; authoritative plan,
  survival guide, execution log, session, and packet paths are recorded below; prewalk is off; use
  concrete Elves commits and end with acceptance evidence plus `Confidence:` trailers.

**Tasks:**

- [ ] Separate general-task and explicit-review grammar and prompts.
- [ ] Safely admit non-ignored untracked and host-selected context.
- [ ] Add isolated-write handoff behavior without host-checkout mutation.
- [ ] Preserve and prove sandbox, credential, cleanup, and authority boundaries.
- [ ] Update all public/installed docs and release metadata to v2.15.0.
- [ ] Run focused, canonical, Fugu, independent, PR, and landing verification.

**Acceptance criteria:**

- [ ] [B1-A1] `$elves fugu <task>` and equivalent natural language execute a general Fugu task whose prompt and output contract follow the requested work rather than forcing repository-review severities or a clean-review verdict.
- [ ] [B1-A2] `$elves fugu review <scope>` and equivalent natural language retain an explicit read-only review contract with base/change evidence, ordered actionable findings, exact file/line references, and a deterministic no-findings response.
- [ ] [B1-A3] The Fugu context bundle safely admits regular non-ignored untracked files and exact host-selected relevant paths while continuing to exclude ignored dependency/cache/build trees, credentials, Git/Elves operational state, executable agent configuration, symlinks, hard links, special files, and out-of-repository paths with visible bounded diagnostics.
- [ ] [B1-A4] A user-authorized Fugu implementation task may write only inside its disposable kernel-isolated workspace and yields a bounded, audited handoff that the host can inspect; no provider process directly mutates the host checkout or gains Git, PR, merge, tag, release, posting, secret, or protected-ref authority.
- [ ] [B1-A5] Regular, deep, and Ultra profiles preserve their documented model/effort and hard-wall behavior in both task types, including exact-session Ultra synthesis, closed input, credential scrubbing, no Linux procfs, qualified macOS/Linux boundaries, and fail-closed cleanup.
- [ ] [B1-A6] Focused provider/isolation tests, installed Claude/Codex bundle smokes, repository consistency, the v2.15.0 release checklist, and the canonical verifier pass at the exact pull-request head against the immutable base.
- [ ] [B1-A7] SKILL, AGENTS, README, guide, changelog, provider references, installed surfaces, and durable guidance consistently explain general Fugu tasks, explicit review mode, context selection, isolated-write handoff, authority limits, and v2.15.0.

**Docs likely touched:** SKILL, AGENTS, README, guide, CHANGELOG, provider shortcuts, durable
provider guidance, and any generated installed-surface manifests required by existing shipment.

**Risk:** high — this widens an external provider from a fixed read-only review into a
task-sensitive route with optional isolated writes.

**Caution:** Do not weaken the outer filesystem sandbox or let convenience flags bypass
credential/path policy. A successful provider task is evidence, never host authority.

**Affected surfaces:** provider invocation, Fugu prompt/runner, isolation snapshot and write
policy, handoff export, tests, installed bundles, documentation, and release metadata.

**Constitution impacts:** preserve the thin safety kernel, test integrity, external-writer import
discipline, and host-only protected-ref/landing authority.

**Review focus:** task-mode ambiguity, snapshot completeness, secret/ignored-path exclusion,
cross-platform writable containment, hostile output audit, host mutation, Ultra task fidelity,
timeout cleanup, and documentation parity.

**Focused tests:** `tests.test_provider_shortcuts`, relevant `tests.test_dispatch_isolation`,
installed-bundle/sync tests, consistency, release checklist, and the canonical verifier.

**Depends on:** none.

## Master Acceptance

- [ ] [M-A1] The authoritative plan, session, and worker packet retain exact stable-id/criterion parity, and every B1 criterion carries exact-head evidence before landing.
- [ ] [M-A2] Fugu review mode and an independent cumulative reviewer report no unresolved actionable security, correctness, context-completeness, authority, or documentation findings.
- [ ] [M-A3] The canonical repository verifier and strict landing check pass on the exact reviewed pull-request head against the unchanged immutable base.
- [ ] [M-A4] The pull request is mergeable by a regular merge commit with required checks green, a clean worktree, no unresolved feedback, and v2.15.0 release follow-through ready.

## Non-negotiables

- The user-authorized landing method is a regular merge commit only; never squash or rebase.
- Fugu never reads or writes the host checkout from inside its model-directed sandbox.
- Provider output never grants Git, PR, landing, release, secret, connector, or posting authority.
- Unsafe or ambiguous context/output fails closed with a visible reason rather than being silently
  admitted or silently treated as complete.
- Prewalk is off for this run.

## Post-merge completion covenant

After the authorized regular merge, create and verify immutable `v2.15.0` GitHub tag/release at the
exact merge result if the reviewed version remains appropriate. Draft a concise X announcement
containing the release value and link; do not post it.
