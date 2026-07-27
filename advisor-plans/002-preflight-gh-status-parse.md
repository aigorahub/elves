# Plan 002: Make preflight's gh-identity extraction total so the checklist never self-aborts

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving on. On any STOP condition,
> stop and report. When done, update this plan's row in `advisor-plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 9731fc3..HEAD -- scripts/preflight.sh tests/test_preflight_sh.py`
> On any change to these files since `9731fc3`, re-verify the excerpts below first;
> mismatch = STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `9731fc3` (v2.17.1), 2026-07-27

## Why this matters

`preflight.sh` is the operator's last check before an unattended overnight run. It runs
under `set -euo pipefail`, and its GitHub-identity extraction uses a `grep -o` pipeline
that exits non-zero whenever `gh auth status` phrases the login line without the word
`account` (e.g. `Logged in to github.com as <user>`). Under `pipefail`, that kills the
entire script at section 2 of 14 with a bare exit 1 — no push dry-run, no validation
gates, no summary — and the exit code masquerades as "critical preflight failure". This
was reproduced on a real machine. The fix is to make the extraction total (never
pipeline-fail) and to cover the alternate wording in the test fixture.

## Current state

- `scripts/preflight.sh:15` (approx.) — the file sets `set -euo pipefail`.
- `scripts/preflight.sh:201-202`:

  ```bash
  if echo "$GH_STATUS" | grep -q "Logged in"; then
    GH_USER=$(echo "$GH_STATUS" | grep -o "account [^ ]*" | head -1 | awk '{print $2}')
  ```

  The guard admits any output containing `Logged in`; the extraction then requires the
  literal `account ` and pipeline-fails otherwise, and a bare `VAR=$(pipeline)`
  assignment propagates that failure under `set -e` + `pipefail`.
- `tests/test_preflight_sh.py:38` — the fake `gh` in the test fixture prints
  `Logged in to github.com account test-user`, i.e. only the wording that happens to
  survive.
- Two other pipeline assignments in the same file should be audited for the same class
  while here: around lines 339 and 711 (locate with
  `grep -n '=\$(.*|' scripts/preflight.sh`).
- Conventions: bash 3.2-compatible only (macOS stock bash — no `declare -A`, no
  `mapfile`, no `${var,,}`); the repo verifies shell with `bash -n` via
  `scripts/verify_repo.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Shell syntax | `bash -n scripts/preflight.sh` | exit 0 |
| Focused tests | `python3 -m unittest tests.test_preflight_sh` | OK |
| Consistency | `python3 scripts/check_repo_consistency.py` | exit 0 |

## Scope

**In scope:**
- `scripts/preflight.sh` (the extraction at ~:201-202; the two audited assignments only
  if they exhibit the same failing class)
- `tests/test_preflight_sh.py`

**Out of scope:**
- Any other section of preflight; `scripts/notify.sh`; changing the meaning of exit
  codes documented at the top of `preflight.sh`.

## Git workflow

- Branch: `advisor/002-preflight-gh-status-parse`
- Single commit; imperative subject, e.g. "Tolerate both gh auth status wordings in
  preflight identity extraction".
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Make the extraction total

Replace line 202 with a single `awk` program that handles both wordings and always
exits 0:

```bash
GH_USER=$(echo "$GH_STATUS" | awk '/account /{for(i=1;i<=NF;i++) if($i=="account"){print $(i+1); exit}} /Logged in to .* as /{for(i=1;i<=NF;i++) if($i=="as"){print $(i+1); exit}}')
```

Then guard the empty case immediately after (matching the file's existing pass/fail
helper style — read how nearby sections call `pass`/`fail`/`warn` and use the same
helpers): if `GH_USER` is empty, report the identity as "unknown" via the file's warn
path rather than failing the section.

**Verify**: `bash -n scripts/preflight.sh` → exit 0, and:

```bash
GH_STATUS="Logged in to github.com as alt-user (keyring)"; echo "$GH_STATUS" | awk '/account /{for(i=1;i<=NF;i++) if($i=="account"){print $(i+1); exit}} /Logged in to .* as /{for(i=1;i<=NF;i++) if($i=="as"){print $(i+1); exit}}'
```

→ prints `alt-user`; repeat with `...github.com account acc-user` → prints `acc-user`.

### Step 2: Audit the sibling pipeline assignments

Run `grep -n '\$(' scripts/preflight.sh | grep '|'` and inspect each `VAR=$(...|...)`
assignment (the audit flagged ~:339 and ~:711). For each whose right-hand side can
exit non-zero on benign input (a `grep` that may not match), append `|| true` inside
the substitution or restructure to `awk`. Do not touch assignments whose non-zero exit
is intentionally fatal (leave a one-line code comment only where you changed behavior).

**Verify**: `bash -n scripts/preflight.sh` → exit 0.

### Step 3: Cover the alternate wording in tests

In `tests/test_preflight_sh.py`, add a test whose fake `gh` prints
`Logged in to github.com as alt-user` (model it on the existing fixture at :38 — copy
the existing test's structure for building the fake-bin dir and PATH). Assert the
script proceeds past the identity section: the simplest robust assertion is that the
output contains evidence of a later section (pick a stable later-section string from
the script, e.g. its summary header) AND does not exit with the abort signature.

**Verify**: `python3 -m unittest tests.test_preflight_sh` → OK, with the new test
counted (test count increases by ≥1 vs. `git stash`-free baseline; read the runner's
"Ran N tests" line).

## Test plan

- New test: alternate `gh auth status` wording → preflight continues past section 2.
- Existing tests remain untouched and green.
- Pattern: the existing fake-`gh` fixture in `tests/test_preflight_sh.py`.

## Done criteria

- [ ] `bash -n scripts/preflight.sh` exits 0
- [ ] `python3 -m unittest tests.test_preflight_sh` → OK, ≥1 new test
- [ ] `grep -n 'grep -o "account' scripts/preflight.sh` → no matches
- [ ] Manual probe from Step 1 prints the user for BOTH wordings
- [ ] `git status` shows only the two in-scope files modified
- [ ] `advisor-plans/README.md` status row updated

## STOP conditions

- The code at ~:201-202 doesn't match the excerpt (drifted).
- The script's pass/fail helper structure makes the empty-GH_USER warn path ambiguous —
  report the options rather than guessing.
- A sibling assignment's non-zero exit turns out to be load-bearing for a documented
  exit-code contract.

## Maintenance notes

- `gh` wording changes again someday; the awk form is wording-tolerant but a third
  format would need a third clause — the new test is the place to add it.
- Reviewer focus: bash-3.2 compatibility of the awk one-liner (no GNU-only features
  used) and that the empty-user path warns rather than fails.
