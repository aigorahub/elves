# Project landing profiles

A repository may track `.elves/landing-profile.json` to turn its own deterministic release and
documentation rituals into exact-HEAD readiness inputs. The profile can block readiness; it can
never grant merge, protected-ref, tag, release, connector, secret, or posting authority. A missing
profile is neutral, so existing repositories keep generic Elves landing behavior.

## Run the profile

From a source checkout:

```bash
python3 scripts/landing_profile.py check --repo-root . --base origin/main --json
```

From an installed bundle, resolve the active Elves skill root and keep the target repository as the
working directory:

```bash
python3 "$ELVES_SKILL_ROOT/scripts/landing_profile.py" check \
  --repo-root . --base origin/main --json
```

`elves_landing_check.py --repo-root .` runs the same live check automatically. When a profile is
present, host readiness must record both `project_landing_checks_green: true` and the matching
`project_landing_checks_digest`. The host recomputes the live result from the tracked profile and
exact repository identities; `worker_report` fields cannot set, replace, or override either value.

## Learning loop (observe → propose → promote)

Host-owned learning state lives under gitignored `.elves/runtime/landing-profile/`. It is not
readiness authority and never auto-writes the tracked profile.

```bash
# Record an exact-HEAD observation, optionally with an explicit candidate proposal.
python3 "$ELVES_SKILL_ROOT/scripts/landing_profile.py" observe \
  --repo-root . --base origin/main \
  --note "docs always move with scripts" \
  --propose-id docs-with-scripts \
  --propose-when 'scripts/**' \
  --propose-paths 'docs/**' \
  --propose-severity advisory

# Synthesize candidates from explicit statements and co-occurrence (min support default 2).
python3 "$ELVES_SKILL_ROOT/scripts/landing_profile.py" propose --repo-root . --json

# Promote one candidate into tracked .elves/landing-profile.json (operator commits the result).
python3 "$ELVES_SKILL_ROOT/scripts/landing_profile.py" promote \
  --repo-root . --id docs-with-scripts --severity advisory
```

There is no auto-promotion. Candidates must be schema-v1 check shapes. Executable/`command` shapes
remain unsupported. Co-occurrence proposals default to advisory severity; choose severity at
promote time.

### Exact-HEAD waivers

A host may waive one blocking check at the exact current HEAD:

```bash
python3 "$ELVES_SKILL_ROOT/scripts/landing_profile.py" waive \
  --repo-root . --id docs-required \
  --reason "temporary docs lag on this head only"
```

A waived blocking failure becomes `status=waived` and is bound into the result digest. Moving HEAD
invalidates the waiver. Waivers never authorize merge, tag, release, or posting.

## Schema v1

The profile has exactly `schema_version` and `checks`. Unknown keys fail closed. IDs are unique
lowercase slugs. Every check has a `when` condition:

- `{"kind": "always"}` always applies.
- `{"kind": "any_path_glob", "patterns": ["scripts/**"]}` applies when the exact
  merge-base-to-HEAD delta contains a matching repository-relative path.

The only pre-land kind is `path_touched`. It requires `severity` (`blocking` or `advisory`), has
repository-relative `paths` globs, and passes when at least one changed path matches. It expresses
deterministic co-change and freshness rules without interpreting content. Executable kinds,
`command`, `argv`, shell, environment, working-directory, and timeout shapes are unsupported and
fail closed with `profile_executable_check_unsupported`. Schema v1 never launches a
profile-directed subprocess. The runner's fixed internal local Git reads resolve identity and
changed paths; they are not profile-configurable gates. Glob matching uses bounded dynamic
programming rather than backtracking, and a conservative total-work budget fails closed before an
oversized profile/delta combination is evaluated.

`post_merge_checklist` has a bounded `description` and no severity. An applicable item is emitted
as declarative follow-through only; the runner never executes it.

## Exact identity and digest

The runner requires the profile to be a bounded ordinary non-symlink UTF-8 JSON file whose exact
bytes match `.elves/landing-profile.json` at the current `HEAD`. It resolves `HEAD`, the configured
base, and their merge base to exact commits, computes the changed paths once, evaluates applicable
declarations, then verifies that `HEAD` did not move.

The canonical SHA-256 digest covers schema version, exact profile-content hash, exact HEAD, resolved
base, merge base, and normalized ordered outcomes. It excludes timestamps, absolute paths, and raw
runtime output. Changing the profile, HEAD, base identity, merge base, or outcome invalidates stale
readiness. Advisory failures remain visible but do not make the project input red; blocking failures
and any invalid present profile do.

## Trust boundary

Same-user implementation-worker isolation remains the protocol trust model inherited from landing
authority; a project profile is not a sandbox or a signed authority channel. That trust does not
let a worker self-attest project readiness: strict landing recomputes the live profile result at the
exact repository identity, and worker-reported green/digest fields are stripped before host control
state is evaluated. Adding signed host authority is outside schema v1.

## Elves dogfood policy

This repository tracks its own profile. Applicable changes require explanatory docs, the public
guide, changelog/release metadata, and Claude/Codex parity surfaces through deterministic path
co-change rules. The host separately runs the existing repository consistency and release-checklist
tools during ordinary landing verification; the profile never invokes them.

For a reviewed release-worthy merge, the declarative checklist requires the host to verify the
matching immutable GitHub tag/release at the merged result and draft a concise, at-most-280-character
X announcement containing the value and release link. Neither action is automatic, and the draft is
never posted by the runner.
