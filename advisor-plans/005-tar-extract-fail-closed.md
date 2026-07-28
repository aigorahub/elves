# Plan 005: Make the API-snapshot tar extraction fail closed on interpreters without `filter=`

> **Executor instructions**: Follow step by step; verify each step before continuing.
> On any STOP condition, stop and report. When done, update this plan's row in
> `advisor-plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 9731fc3..HEAD -- scripts/cobbler_runtime/public_api_snapshot.py`
> On changes, re-verify the excerpt; mismatch = STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `9731fc3` (v2.17.1), 2026-07-27

## Why this matters

The public-API compatibility gate captures a baseline by extracting
`git archive --format=tar <base_ref>` into a temp directory. The extraction requests
the `data` member filter but falls back to a completely **unfiltered** `extractall` when
the interpreter raises `TypeError` — and `tarfile`'s `filter=` keyword only exists from
Python 3.10.12 / 3.11.4. The repo's supported floor is 3.10, so interpreters inside the
support window (3.10.0–3.10.11, 3.11.0–3.11.3) silently drop the safety filter. Because
`base_ref` is caller-supplied, a hostile ref in a fetched branch could carry symlink or
absolute-path members and write outside the temp root as the running user. Fail closed
instead: on interpreters without `filter=`, validate members by hand or refuse with the
repo's standard `ValidationIssue`.

## Current state

- `scripts/cobbler_runtime/public_api_snapshot.py:1701-1704`:

  ```python
  try:
      tar.extractall(temp_root, filter="data")
  except TypeError:  # pragma: no cover - Python < 3.12 compatibility
      tar.extractall(temp_root)
  ```

- Context: `_capture_snapshot_from_ref(repo_root, *, base_ref)` (~:1684) runs
  `_run_git(repo_root, ["archive", "--format=tar", base_ref])` and opens the result as
  a tarfile; extraction happens inside a `tempfile.TemporaryDirectory` rooted path
  (`temp_root`).
- Error idiom to match: fail-closed `ValidationIssue("snake_case_code", "message")`
  from `scripts/cobbler_runtime/schema.py` — grep this module for its existing
  `ValidationIssue` usages and reuse the local raising/diagnostic style (this module
  may return `(None, reason)` tuples instead of raising — read
  `_capture_snapshot_from_ref`'s error returns and match them).
- Tests for this module: locate with `grep -rln "public_api_snapshot" tests/` (expect
  `tests/test_public_api_snapshot.py`); model new tests on its existing fixtures.
- Conventions: stdlib only; hermetic tests (build the tar bytes in-memory or in a
  TemporaryDirectory; no network).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Compile | `python3 -m compileall -q scripts` | exit 0 |
| Focused tests | `python3 -m unittest tests.test_public_api_snapshot` (adjust to the located module name) | OK |
| Full suite (≥3.10) | `python3 -m unittest discover -s tests -t .` | 0 failures/errors |

## Scope

**In scope:** `scripts/cobbler_runtime/public_api_snapshot.py`; its test module.

**Out of scope:** any other `tarfile` usage in the repo (sweep and report locations if
you find siblings — `grep -rn "extractall" scripts/` — but do not change them here);
the `git archive` invocation itself; snapshot semantics.

## Git workflow

- Branch: `advisor/005-tar-extract-fail-closed`
- One commit. Imperative subject, e.g. "Fail closed when tar member filtering is
  unavailable in the API-snapshot gate". Do NOT push/PR unless instructed.

## Steps

### Step 1: Replace the fallback with hand-validation

Replace the excerpt with logic that (a) tries `extractall(temp_root, filter="data")`;
(b) on `TypeError`, iterates `tar.getmembers()` and validates each member BEFORE a
plain `extractall`: reject (via this module's established error-return style, stable
code e.g. `api_snapshot_tar_member_unsafe`) any member that is not a regular file or
directory, any name that is absolute or contains `..` path segments, and any name whose
resolved destination (`(temp_root / name).resolve()`) does not stay under
`temp_root.resolve()`. Only if every member passes, call
`tar.extractall(temp_root, members=validated)`. Keep the happy path (modern
interpreters) byte-identical.

**Verify**: `python3 -m compileall -q scripts` → exit 0.

### Step 2: Tests — both branches

In the located test module add:

1. **Filter-unavailable path is safe**: monkeypatch the `TarFile.extractall` first call
   to raise `TypeError` (or patch a module-level wrapper if one exists) and feed a tar
   built in-memory (`tarfile.open(fileobj=io.BytesIO(...), mode="w")`) containing a
   symlink member and a `../escape` member → assert the unsafe-member error code is
   returned/raised and NOTHING was written outside `temp_root`.
2. **Filter-unavailable path extracts clean archives**: same monkeypatch, tar with only
   regular files/dirs → snapshot capture succeeds.
3. **Modern path unchanged**: without the monkeypatch, a clean archive succeeds (this
   may already be covered — if an existing test exercises `_capture_snapshot_from_ref`,
   cite it in the commit instead of duplicating).

**Verify**: focused module → OK, ≥2 new tests.

## Test plan

As step 2. Fixtures are in-memory tars; no real hostile content beyond `..` names and a
symlink member — no runnable exploit strings.

## Done criteria

- [ ] `grep -n "except TypeError" scripts/cobbler_runtime/public_api_snapshot.py` no
      longer shows a bare `tar.extractall(temp_root)` fallback
- [ ] Focused test module OK with ≥2 new tests; full suite (≥3.10) 0 failures/errors
- [ ] `python3 -m compileall -q scripts` exit 0
- [ ] `git status` clean outside scope; `advisor-plans/README.md` row updated

## STOP conditions

- The excerpt doesn't match (drift), or extraction happens in more places than the one
  cited (report the inventory first).
- The module's error style is neither raise-`ValidationIssue` nor `(None, reason)` —
  report what it is before adapting.
- Monkeypatching the first `extractall` call proves impossible without restructuring
  the function — propose the minimal seam (e.g. extract a `_extract_members` helper)
  and proceed only if it stays behavior-identical.

## Maintenance notes

- If the repo's floor ever rises to ≥3.12 (see survey DEP-01), the fallback branch can
  be deleted outright — leave a comment noting that.
- Reviewer focus: the destination-containment check uses resolved paths (symlink-aware)
  and the happy path is untouched.
