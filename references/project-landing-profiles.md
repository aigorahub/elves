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
`project_landing_checks_digest`. Worker reports cannot set either field.

## Schema v1

The profile has exactly `schema_version` and `checks`. Unknown keys fail closed. IDs are unique
lowercase slugs. Every check has a `when` condition:

- `{"kind": "always"}` always applies.
- `{"kind": "any_path_glob", "patterns": ["scripts/**"]}` applies when the exact
  merge-base-to-HEAD delta contains a matching repository-relative path.

Pre-land kinds require `severity` (`blocking` or `advisory`):

- `command` has a non-empty `argv` array and optional bounded `timeout_seconds`. It runs with
  `shell=False`, closed stdin, a minimal scrubbed environment, a hard timeout, and bounded redacted
  combined output. Shell executables, secret-like arguments, traversal, absolute paths, unsafe
  profile files, and unsupported shapes are rejected.
- `path_touched` has repository-relative `paths` globs and passes when at least one changed path
  matches. It expresses deterministic co-change and freshness rules without interpreting content.

`post_merge_checklist` has a bounded `description` and no severity. An applicable item is emitted
as declarative follow-through only; the runner never executes it.

## Exact identity and digest

The runner requires the profile to be a bounded ordinary non-symlink UTF-8 JSON file whose exact
bytes match `.elves/landing-profile.json` at the current `HEAD`. It resolves `HEAD`, the configured
base, and their merge base to exact commits, computes the changed paths once, runs applicable
checks, then verifies that `HEAD` did not move.

The canonical SHA-256 digest covers schema version, exact profile-content hash, exact HEAD, resolved
base, merge base, and normalized ordered outcomes. It excludes timestamps, absolute paths, and raw
command output. Changing the profile, HEAD, base identity, merge base, or outcome invalidates stale
readiness. Advisory failures remain visible but do not make the project input red; blocking failures
and any invalid present profile do.

## Elves dogfood policy

This repository tracks its own profile. Applicable changes require explanatory docs, the public
guide, changelog, and Claude/Codex parity surfaces; deterministic consistency and release-checklist
commands run without recursively invoking the full landing check or broad verifier.

For a reviewed release-worthy merge, the declarative checklist requires the host to verify the
matching immutable GitHub tag/release at the merged result and draft a concise, at-most-280-character
X announcement containing the value and release link. Neither action is automatic, and the draft is
never posted by the runner.
