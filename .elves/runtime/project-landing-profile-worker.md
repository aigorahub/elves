# Worker packet: project landing profile Batch 1

## Identity and route

- Run: `project-landing-profile-20260722`
- Branch: `codex/project-landing-profile`
- Worktree: `/Users/john/aigora/dev/elves-project-landing-profile`
- Start head: `35449718c173f737a7b0dad209accfe86b55b5a9`
- Plan: `docs/plans/project-landing-profile.md`
- Worker: GPT-5.6 (`gpt-5.6-sol`) at high reasoning
- Scope: implement all and only Batch 1; coordinator owns run memory and landing

## Intent and why

Elves already proves plan acceptance and generic landing authority, but this repository's actual
docs, guide, changelog, parity, and release rituals live in operator memory. Make those rituals a
tracked exact-HEAD readiness input that other repositories can opt into without weakening generic
landing or granting any new authority.

This run must dogfood the feature. It is a public capability and should land with aligned v2.13.0
metadata. The tracked post-merge rules must require an appropriate immutable GitHub tag/release and
a short X announcement draft while making clear that the runner never merges, releases, or posts.

## Prewalk trajectory

The packet is delivered once in this guide turn. On the first turn:

1. Read the repo instructions, plan, landing/prewalk/schema references, relevant code, and tests.
2. Write a bounded private TODO/checkpoint under `.elves/runtime/prewalk/project-landing-profile-20260722/`.
3. Make one meaningful implementation edit in an owned surface.
4. Run the narrowest useful check for that edit.
5. Record exact head/diff/test state in the private checkpoint and stop without committing.

The coordinator will validate the checkpoint and send exactly `Continue.` to this same agent. On
continuation, execute the TODO without asking for the packet again. This exact-agent trajectory is
not evidence that the repository's native-worker transport is behaviorally qualified.

## Build On

- `scripts/elves_landing_check.py`: session/plan/evidence validation, strict tracked-file checks,
  report plumbing, and exact repository identity.
- `scripts/cobbler_runtime/landing_authority.py`: distinct readiness fields, digest inputs,
  invalidation, and merge guard.
- `scripts/release_checklist.py`: structured findings and JSON output.
- `scripts/verify_repo.py` and `scripts/cobbler_runtime/context.py`: bounded subprocess,
  environment allowlisting/scrubbing, output bounding, and redaction patterns.
- `scripts/acceptance_contract.py`: thin installed CLI/runtime separation pattern.
- `scripts/sync_installed_skills.py` and `scripts/installed_bundle_smoke.py`: installed shipment.
- Existing tests: `test_elves_landing_check.py`, `test_landing_authority.py`,
  `test_installed_bundle_smoke.py`, `test_release_checklist.py`, and verifier/consistency tests.

## Required architecture

- Track `.elves/landing-profile.json`; adjust `.gitignore` to keep the profile tracked while all
  runtime/candidate/session material below `.elves/` remains ignored.
- Put pure reusable logic in `scripts/cobbler_runtime/landing_profile.py` and a thin installed CLI
  in `scripts/landing_profile.py` with a `check` command and deterministic JSON output.
- Minimal schema v1:
  - check kinds `command`, `path_touched`, and declarative-only `post_merge_checklist`;
  - severity `blocking` or `advisory` for pre-land checks;
  - conditions `always` and `any_path_glob`;
  - commands are argv arrays, never shell strings.
- Resolve `HEAD` and base to exact commits. Compute the merge-base/delta deterministically and
  verify the head remains unchanged after checks.
- Bound profile size/shape/counts/strings, output, time, and subprocesses. Reject symlinked or
  irregular profiles, unsafe paths, unsupported keys/kinds, and malformed UTF-8/JSON.
- Run commands with `shell=False`, closed stdin, a scrubbed minimal environment, a hard timeout,
  and bounded/redacted diagnostics. Do not expose secrets through profile args or output.
- Make the canonical digest cover profile content, exact head, resolved base/merge-base identity,
  and normalized outcomes. Exclude timestamps, absolute paths, and raw output.
- Missing profile is neutral. Present-invalid or blocking-failed is not green. Advisory failures
  remain visible but non-blocking.
- Integrate the live result into `elves_landing_check.py` and add distinct host-owned
  `project_landing_checks_green` / digest state throughout landing authority, attestation,
  invalidation, proof-scope digesting, and merge guard. Do not fold it into generic acceptance.
- A worker must not be able to assert/alter project readiness. No check may grant merge, tag,
  release, posting, protected-ref, connector, or secret authority.
- Ship the thin CLI and runtime in both installed host layouts and prove it runs outside the source
  tree.

## Dogfood profile

Encode deterministic Elves checks for:

- documentation freshness on shipped behavior changes, requiring a real explanatory surface and
  running repository consistency;
- `guide/index.html` freshness for public workflow/invocation changes;
- honest changelog/release alignment using the existing release checklist;
- Claude/Codex host parity using repository consistency and co-change rules where useful;
- declarative post-merge steps: if this reviewed change carries a release bump, verify the matching
  immutable GitHub tag/release after host-authorized merge and draft a <=280-character X
  announcement with value plus link. Never post it.

Avoid a dogfood recursion where the profile invokes the full landing check or broad verifier that
invokes the profile again.

## Owned surfaces

- `.gitignore`, `.elves/landing-profile.json`
- `scripts/landing_profile.py`, `scripts/cobbler_runtime/landing_profile.py`
- landing check and landing authority integration
- focused profile/landing/authority/install/consistency tests
- installed shipment and smoke contracts
- SKILL, AGENTS, README, CHANGELOG, guide, landing/schema/runtime references, and relevant `.ai-docs`

## Forbidden surfaces

- Do not edit `.elves-session.json`, the survival guide, execution log, worker packet, or other
  host-owned run memory.
- Do not touch Grok's untracked plan in the main checkout or work outside this dedicated worktree.
- Do not implement observations, candidates, promotion, auto-promotion, waivers, preference keys,
  LLM rubrics, rich PR-label conditions, or caching.
- Do not redesign worker routing/full-run/provider shortcuts.
- Do not merge, create/modify PRs, tag, publish a release, use an X API/composer, or post.
- Do not squash/rebase, force-push, reset, clean, delete user work, or mutate protected refs.

## Acceptance identity

- **B1-A1:** A repository with no landing profile retains generic landing behavior, while a present malformed, symlinked, irregular, oversized, or unsupported profile fails closed with a stable diagnostic.
- **B1-A2:** Schema-v1 blocking, advisory, skipped, command, and path-touched results are deterministic and structured; commands use argv without a shell, closed stdin, a scrubbed environment, bounded output, and a hard timeout.
- **B1-A3:** Project results and their canonical digest bind profile bytes, exact `HEAD`, resolved base commit, and normalized check outcomes; a moved head, changed base, changed profile, or stale digest cannot satisfy readiness.
- **B1-A4:** Project landing state is a distinct host-owned readiness input that workers cannot assert or mutate, and it never grants merge, tag, release, protected-ref, or posting authority.
- **B1-A5:** The tracked Elves profile automatically exercises documentation freshness, public-guide freshness, changelog honesty, and Claude/Codex parity on applicable diffs, while preserving generic behavior for projects without a profile.
- **B1-A6:** Both installed host bundles contain and can execute the new CLI, focused profile/landing/authority/shipment tests pass, and the canonical repository verifier passes at the exact pull-request head against the immutable base.
- **B1-A7:** SKILL, AGENTS, README, guide, changelog, landing references, and durable AI docs align at v2.13.0 and state that an appropriate authorized merge is followed by a matching immutable GitHub tag/release plus a short X announcement draft, never an automatic post.

Master criteria M-A1 through M-A4 remain host-owned because they require run-memory evidence,
independent review, exact PR state, and mergeability.

## Failure modes to defend

- Profile missing vs invalid are accidentally treated the same.
- Base branch movement silently changes the evaluated delta or leaves a stale attestation green.
- A symlink/path traversal or shell string executes outside repository policy.
- Commands inherit credentials or leak unbounded output.
- Raw output/timestamps/absolute paths make result digests nondeterministic.
- Advisory checks block, blocking checks warn, or skipped checks disappear from the report.
- A worker-provided session field forges host readiness.
- Installed bundles omit the CLI or depend on repo-only helpers at runtime.
- Dogfood checks recurse or make generic installations Elves-specific.
- Post-merge wording is mistaken for automatic release/post permission.

## Verification and git handback

Run focused tests while building, then the broad canonical verifier at v2.13.0 against
`origin/main`. Use precise phase commits and push only this feature branch. Do not create the final
acceptance/Close record yourself; return:

1. concise implementation summary;
2. commits pushed and exact head;
3. focused and broad commands/results;
4. acceptance mapping B1-A1..B1-A7;
5. changed-surface inventory;
6. residual risks or review focus;
7. explicit confirmation that no PR/merge/release/X-post action was taken.
