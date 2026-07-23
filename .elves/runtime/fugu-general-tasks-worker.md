# Worker packet: Fugu general tasks

## Intent and why

Implement the single authoritative batch in `docs/plans/fugu-general-tasks.md`: make Fugu a
general provider route, retain an explicit review workflow, safely widen eligible context, and
support user-authorized implementation only through a disposable writable workspace with an
audited host handoff.

## Non-obvious rationale

Snapshot breadth does not itself consume provider tokens; hiding relevant files makes review and
investigation incomplete. The host/Fugu agents choose relevance, while the safety kernel decides
admissibility. General-task output must not inherit review-only severity/verdict instructions.
Provider writes must never cross directly into the actual checkout.

## Build On targets

- `scripts/run_fugu.sh`
- `scripts/cobbler_runtime/isolation.py`
- `tests/test_provider_shortcuts.py`
- relevant `tests/test_dispatch_isolation.py`
- `references/provider-shortcuts.md`
- installed-bundle sync/smoke and repository consistency/release tooling

## Owned surfaces

Fugu runner; narrowly shared isolation support; focused provider/isolation tests; SKILL, AGENTS,
README, guide, CHANGELOG, provider/durable docs; release metadata and existing generated shipment
surfaces when required.

## Forbidden surfaces

Other provider behavior; real-checkout provider writes; credentials; Git/PR/merge/tag/release/post
authority; protected refs; canonical run memory (`.elves-session.json`, survival guide, execution
log); unrelated roadmap work; test weakening.

## Acceptance evidence

Prove B1-A1 through B1-A7 exactly as written in `docs/plans/fugu-general-tasks.md`. At minimum:
focused hermetic provider tests, macOS/Linux isolation policy tests, unsafe context/output cases,
read-only review behavior, general prompt behavior, writable handoff/no-host-mutation behavior,
regular/deep/Ultra preservation, installed bundle smokes, docs consistency, v2.15.0 release
checklist, and canonical verification or a precise host-owned remaining-proof list.

## Failure modes and pitfalls

- Treating every task as review despite new grammar.
- Silently omitting untracked files or silently admitting ignored/credential material.
- Symlink, hard-link, special-file, path traversal, oversized, or race-prone handoff output.
- Allowing snapshot writes in review/read-only modes or host writes from the provider sandbox.
- Weakening no-procfs, environment scrubbing, sandbox qualification, timeouts, or group cleanup.
- Ultra synthesis changing the task or losing the exact session.
- Updating one host surface but leaving SKILL/AGENTS/README/guide/installed docs stale.

## HEAD, run docs, route identity, and output

- Launch head: `1d90246b97b5e11211525e71b6a9ff5091c6cc10`
- Branch: `codex/fugu-general-tasks`
- Worktree: `/Users/john/aigora/dev/elves-fugu-general-tasks`
- Plan: `docs/plans/fugu-general-tasks.md`
- Prewalk: off; this is a fresh ordinary implementation turn.
- Use concrete Elves history subjects. Push at least one meaningful `Implement` slice before the
  single acceptance-backed `Close` commit.
- Maintain the untracked progress ledger at `.elves/runtime/worker-progress-B1.md`.
- Never edit canonical run memory or perform PR/merge/release actions.
- Finish with changed surfaces, commands/results, acceptance mapping, residual risks, exact HEAD,
  and `Confidence: <level>` with a truthful unsure list.

## Acceptance definitions

- [ ] [B1-A1] `$elves fugu <task>` and equivalent natural language execute a general Fugu task whose prompt and output contract follow the requested work rather than forcing repository-review severities or a clean-review verdict.
- [ ] [B1-A2] `$elves fugu review <scope>` and equivalent natural language retain an explicit read-only review contract with base/change evidence, ordered actionable findings, exact file/line references, and a deterministic no-findings response.
- [ ] [B1-A3] The Fugu context bundle safely admits regular non-ignored untracked files and exact host-selected relevant paths while continuing to exclude ignored dependency/cache/build trees, credentials, Git/Elves operational state, executable agent configuration, symlinks, hard links, special files, and out-of-repository paths with visible bounded diagnostics.
- [ ] [B1-A4] A user-authorized Fugu implementation task may write only inside its disposable kernel-isolated workspace and yields a bounded, audited handoff that the host can inspect; no provider process directly mutates the host checkout or gains Git, PR, merge, tag, release, posting, secret, or protected-ref authority.
- [ ] [B1-A5] Regular, deep, and Ultra profiles preserve their documented model/effort and hard-wall behavior in both task types, including exact-session Ultra synthesis, closed input, credential scrubbing, no Linux procfs, qualified macOS/Linux boundaries, and fail-closed cleanup.
- [ ] [B1-A6] Focused provider/isolation tests, installed Claude/Codex bundle smokes, repository consistency, the v2.15.0 release checklist, and the canonical verifier pass at the exact pull-request head against the immutable base.
- [ ] [B1-A7] SKILL, AGENTS, README, guide, changelog, provider references, installed surfaces, and durable guidance consistently explain general Fugu tasks, explicit review mode, context selection, isolated-write handoff, authority limits, and v2.15.0.

Host-owned Master Acceptance remains outside worker authority.
