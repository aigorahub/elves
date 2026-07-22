# Plan: Landing profile learning loop (Batch 2)

## Mission

Complete the project-landing-profile roadmap deferred from v2.13.0 Batch 1: host-owned
observation capture, deterministic candidate synthesis, explicit promotion into the tracked
profile, and exact-HEAD waivers. Keep the trust model identical to schema v1 — project checks may
block readiness; they never grant merge, tag, release, protected-ref, connector, secret, or posting
authority. Schema v1 still never launches profile-directed subprocesses.

## Product decisions

- Observation packets and candidate ledgers live under gitignored
  `.elves/runtime/landing-profile/`. They are not readiness authority.
- Only an explicit host `promote` rewrites tracked `.elves/landing-profile.json`. There is no
  auto-promotion.
- Candidate checks are always schema-v1 shapes (`path_touched` or `post_merge_checklist`).
  Executable shapes remain unsupported and fail closed.
- Exact-HEAD waivers are host-owned runtime state bound to one check id and one HEAD. Moving HEAD
  invalidates them. Waivers can clear a blocking failure for readiness only; they never authorize
  merge.
- Co-occurrence proposals are advisory by default. Operators choose severity at promote time.
- Missing observations/candidates is neutral. Corrupt runtime files fail the learning command
  closed without mutating the tracked profile.
- Release as **v2.14.0** (new public learning capability on top of v2.13.0 profiles).

## Scope

### In scope

- Runtime observation store with exact HEAD/base/merge-base and bounded changed paths.
- Explicit operator-proposed check statements on `observe`.
- Deterministic co-occurrence synthesis (`propose`) into a candidate ledger.
- `candidates` listing and `promote` into tracked `.elves/landing-profile.json`.
- Exact-HEAD `waive` / waiver application inside profile evaluation digests.
- CLI surface on `scripts/landing_profile.py` plus focused hermetic tests.
- Docs, guide, changelog, host parity, dogfood profile path updates, v2.14.0 metadata.

### Out of scope

- Executable/`command` gates and any profile-directed subprocesses.
- Unsupervised auto-promotion or machine-global preference keys that invent policy.
- Free-form LLM rubrics, expensive-result caching, package publish/deploy automation, X posting.
- Changing merge methods, acceptance identity, or worker immutability.

## Acceptance

- [x] [B2-A1] `observe` records a bounded, deterministic observation under
      `.elves/runtime/landing-profile/` without writing the tracked profile.
- [x] [B2-A2] `propose` synthesizes schema-valid candidate checks from explicit statements and
      co-occurrence, never inventing executable gates, never auto-writing the tracked profile.
- [x] [B2-A3] `promote --id` validates and appends a candidate into `.elves/landing-profile.json`
      only when the resulting profile validates; duplicate ids fail closed.
- [x] [B2-A4] Exact-HEAD waivers clear only the named check at the named HEAD, appear in the
      result digest, and do not grant merge or survive a HEAD move.
- [x] [B2-A5] Existing missing-profile neutrality and schema-v1 evaluation remain unchanged for
      repositories that never use learning commands.
- [x] [B2-A6] Focused tests plus docs/version/guide/host-parity/dogfood updates land at v2.14.0.

## Non-negotiables

- Regular merge commit only when landing (no squash/rebase).
- No worker ability to set readiness, merge, waive, or promote.
- No profile-directed subprocess execution.
