# Plan 004: Bring run_fugu.sh's embedded Python under tooling, then extract it to a real module

> **Executor instructions**: Follow step by step; run every verification command and
> confirm the expected result before continuing. This plan has two phases — the gate
> (steps 1–2, safe and small) and the extraction (steps 3–7, larger). If the extraction
> hits a STOP condition, ship the gate phase alone and report. When done, update this
> plan's row in `advisor-plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 9731fc3..HEAD -- scripts/run_fugu.sh scripts/verify_repo.py scripts/cobbler_runtime/dispatch_external.py scripts/sync_installed_skills.py scripts/installed_bundle_smoke.py tests/test_provider_shortcuts.py`
> On changes, re-verify excerpts; mismatch = STOP. (Plan 003 touches
> `run_fugu.sh`/`test_provider_shortcuts.py` — its floor guard and skip decorators are
> expected drift; anything else is not.)

## Status

- **Priority**: P2
- **Effort**: M (gate: S; extraction: M/L)
- **Risk**: MED
- **Depends on**: recommended after `003-trustworthy-verification-signal.md` (clean
  suite signal); hard dependency: none
- **Category**: tech-debt
- **Planned at**: commit `9731fc3` (v2.17.1), 2026-07-27

## Why this matters

`scripts/run_fugu.sh` is 1,921 lines, of which ~1,760 are Python inside a quoted
heredoc — the repo's largest and most-edited source file (8 commits since v2.12; the
big Python modules took zero). That Python is invisible to every tool: `compileall`
only globs `*.py`, `bash -n` treats a quoted heredoc as an opaque string (verified
empirically), no linter or unit test can reach it, and tracebacks point at `<stdin>`.
It also imports five private `_`-prefixed symbols from `cobbler_runtime.dispatch_external`
— a cross-module private contract nothing checks. The repo already solved this problem
once: `scripts/provider_supervisor.py`'s docstring explains the "real, lintable,
compilable file whose source is loaded at launch" pattern, and the newest lane
(`run_manus.sh`, 6 lines → `cobbler_runtime/manus.py` with `build_parser()`/`main()`)
is the converged architecture. This plan first adds a syntax gate for ALL heredocs
(cheap, permanent), then moves the fugu body to `scripts/cobbler_runtime/fugu.py`.

## Current state

- `scripts/run_fugu.sh:160` — `exec python3 - "${PYTHON_ARGS[@]}" <<'PY'`; the heredoc
  closes at line 1921 (`^PY$`). Bash builds `PYTHON_ARGS` around lines 140–159
  (fixed positional values — mode, profile, write flag, task text, etc. — plus a
  variadic tail `PYTHON_ARGS+=("${INCLUDE_PATHS[@]}")`); the Python side reads them
  from `sys.argv`. **Read both sides and write down the exact positional contract
  before moving anything.**
- `scripts/run_fugu.sh:201-207` (heredoc-relative ~line 41) — the private imports:

  ```python
  from cobbler_runtime.dispatch_external import (  # noqa: E402
      _DescendantSupervisor,
      _darwin_process_record,
      _require_darwin_generation_signaling,
      _require_darwin_recursive_containment,
      _terminate_supervised_descendants,
  )
  ```

- `scripts/verify_repo.py` — `compile_scripts` globs `scripts.rglob("*.py")` (~:256);
  `check_shell` runs `bash -n` over the `SHELL_SCRIPTS` list (~:275, list at ~:49).
- The exemplar pattern: `scripts/provider_supervisor.py:1-13` docstring ("lives OUTSIDE
  the cobbler_runtime package on purpose … a real, lintable, compilable file") and
  `scripts/run_manus.sh` (6-line shim) → `scripts/cobbler_runtime/manus.py`
  (`build_parser()` ~:1372, `main()` ~:1416).
- Ship lists that must move in lockstep with any new file: `scripts/sync_installed_skills.py`
  (allowlist entries — `"scripts/run_fugu.sh"` at ~:55; `cobbler_runtime/` ships
  recursively per the module docstring) and `scripts/installed_bundle_smoke.py`
  (`REQUIRED_TOP_LEVEL_RUNTIME_PATHS` at ~:47-64; note
  `tests/test_sync_installed_skills.py:247` proves new `cobbler_runtime/` modules ship
  with no allowlist edit — so a `cobbler_runtime/fugu.py` destination needs no ship-list
  change, only the smoke's required-paths list if you add one).
- Behavior pin: ~32 end-to-end `run_script("run_fugu.sh", ...)` spawns in
  `tests/test_provider_shortcuts.py` (they require Python ≥3.10 per plan 003).
- Conventions: `from __future__ import annotations` at top of every module; fail-closed
  `ValidationIssue` (`cobbler_runtime/schema.py`); stdlib only; no behavior changes in
  this plan — it is a mechanical move.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Compile | `python3 -m compileall -q scripts` | exit 0 |
| Shell syntax | `bash -n scripts/run_fugu.sh` | exit 0 |
| Behavior pin (≥3.10 host) | `python3 -m unittest tests.test_provider_shortcuts` | OK, same pass count as pre-change baseline |
| Bundle smoke | `python3 -m unittest tests.test_installed_bundle_smoke tests.test_sync_installed_skills` | OK |
| Full suite (≥3.10) | `python3 -m unittest discover -s tests -t .` | 0 failures/errors |
| Consistency | `python3 scripts/check_repo_consistency.py` | exit 0 |

Record the pre-change baseline of `tests.test_provider_shortcuts` (exact "Ran N /
failures" line) BEFORE step 3.

## Scope

**In scope:** `scripts/run_fugu.sh`, `scripts/cobbler_runtime/fugu.py` (create),
`scripts/cobbler_runtime/dispatch_external.py` (public aliases only),
`scripts/verify_repo.py` (the heredoc gate), `scripts/installed_bundle_smoke.py` (only
if a required-path entry is needed), `tests/test_provider_shortcuts.py` (only if an
assertion pins the literal `<stdin>` path or heredoc line numbers),
`tests/test_verify_repo.py`-equivalent module for the new gate (locate with
`grep -rln "check_shell" tests/`).

**Out of scope:** ANY behavior change to the fugu lane (flags, output, exit codes,
sandbox semantics); `run_grok.sh`/`run_devin.sh` (explicit follow-up, not this plan);
`aliases/**`, docs surfaces (grammar text does not change).

## Git workflow

- Branch: `advisor/004-extract-fugu-heredoc`
- Commit the gate phase and the extraction phase separately. Imperative subjects.
- Do NOT push/PR unless the operator instructed it.

## Steps

### Step 1 (gate): Compile embedded heredoc Python in `verify_repo`

Add to `verify_repo.py` a check (alongside `check_shell`) that, for each file in
`SHELL_SCRIPTS`, extracts every `<<'PY'` … `^PY$` block and compiles it with
`py_compile.compile` (write to a temp dir; map error line numbers by adding the
heredoc's starting line so messages point at the real file:line). Register it wherever
`check_shell` is registered so `--ci` runs it.

**Verify**: `python3 scripts/verify_repo.py --ci 2>&1 | grep -i heredoc` shows the gate
ran (on a ≥3.10 host); temporarily plant `def broken(:` inside the fugu heredoc, rerun,
confirm the gate FAILS naming `run_fugu.sh` and a line number, then revert the plant.

### Step 2 (gate): Add the gate's unit test

In the test module that covers `verify_repo` checks, add: a shell fixture with a valid
heredoc passes; one with invalid Python fails with the mapped line number. Model on the
neighboring `check_shell` tests.

**Verify**: focused module → OK, ≥2 new tests.

### Step 3 (extraction): Create `scripts/cobbler_runtime/fugu.py`

Move the heredoc body (lines 161–1920 of `run_fugu.sh`) verbatim into the new module.
Add at top: the repo-standard `from __future__ import annotations`, a module docstring
modeled on `provider_supervisor.py:1-13` explaining the shim relationship, and a
`main(argv: list[str] | None = None) -> int` that reproduces the current `sys.argv`
positional consumption exactly (adapter only — do NOT convert to argparse in this
plan; that is a behavior-affecting follow-up). Keep the five `dispatch_external`
imports as-is for now.

**Verify**: `python3 -m compileall -q scripts` → exit 0 (the body now compiles as a
real module).

### Step 4 (extraction): Shrink `run_fugu.sh` to a shim

Replace lines 160–1921 with an exec of the module, preserving the existing bash
argument parsing and `PYTHON_ARGS` construction byte-for-byte:

```bash
exec python3 "$(dirname "$0")/cobbler_runtime/fugu.py" "${PYTHON_ARGS[@]}"
```

Mirror how `run_manus.sh` resolves its module path (read it; use the same idiom —
including any `ELVES_SKILL_ROOT`-style resolution it performs — so installed-bundle
layouts keep working). Keep the plan-003 floor guard before the exec.

**Verify**: `bash -n scripts/run_fugu.sh` → exit 0; wc -l shows the file is now ≈160
lines of bash.

### Step 5 (extraction): Promote the five private imports

In `dispatch_external.py`, add public aliases next to the private defs
(`DescendantSupervisor = _DescendantSupervisor`, etc., with a one-line comment naming
`fugu.py` as the consumer), and switch `fugu.py`'s import to the public names. Do not
rename the originals; do not touch other consumers.

**Verify**: `python3 -m compileall -q scripts` → exit 0;
`grep -n "import (\|_DescendantSupervisor" scripts/cobbler_runtime/fugu.py` shows only
public names imported.

### Step 6 (extraction): Ship-list and smoke alignment

`cobbler_runtime/fugu.py` ships automatically (recursive dir); confirm via the existing
proof test. If `installed_bundle_smoke.py`'s required-paths style expects call-site
deps listed, add the entry there following the `provider_supervisor.py` precedent
(`sync_installed_skills.py:38` comment style).

**Verify**: `python3 -m unittest tests.test_sync_installed_skills tests.test_installed_bundle_smoke` → OK.

### Step 7 (extraction): Behavior pin

Run the provider-shortcuts module (≥3.10) and compare against the step-0 baseline —
identical pass/fail/skip counts. If any test greps for `<stdin>` or heredoc line
numbers in output, update that assertion (mechanical) and note it in the commit.

**Verify**: `python3 -m unittest tests.test_provider_shortcuts` → same "Ran N" and
result line as baseline; full suite → 0 failures/errors.

## Test plan

- New: heredoc-compile gate tests (step 2).
- Behavior is pinned by the existing ~32 e2e spawns — no assertion changes except
  path-literal mechanical updates (step 7).
- Follow-up (NOT this plan): unit tests importing `fugu.py` functions directly —
  becomes possible for the first time after this lands.

## Done criteria

- [ ] `python3 -m compileall -q scripts` exits 0 and now covers the fugu body
- [ ] Planted-syntax-error probe fails the new gate with a mapped file:line (then reverted)
- [ ] `bash -n scripts/run_fugu.sh` exits 0; file ≈160 lines
- [ ] `tests.test_provider_shortcuts` counts identical to recorded baseline (≥3.10)
- [ ] Bundle smoke + sync tests OK
- [ ] Full suite (≥3.10) 0 failures/errors; consistency exit 0
- [ ] `git status` clean outside scope; `advisor-plans/README.md` row updated

## STOP conditions

- The bash→Python positional argv contract is ambiguous at any position (report the
  mapping table you derived instead of guessing).
- Any provider-shortcuts test fails after extraction for a reason other than a
  `<stdin>`/line-number literal.
- Installed-bundle smoke demands structural changes beyond adding one path entry.
- You are tempted to "improve" the moved code (argparse, refactors, type fixes) — that
  is out of scope; verbatim move only.

## Maintenance notes

- Follow-ups this unlocks (survey items): migrate `run_grok.sh`/`run_devin.sh` to the
  same shape (D-02), then lift the shared provider-home prologue into one helper;
  convert `fugu.py` argv to `build_parser()` like `manus.py`; direct unit tests for
  `PinnedOutputFile`/`RuntimeBudget`/`PhaseContainment`.
- Reviewer focus: byte-identical body move (diff the extracted region against the old
  heredoc), shim path resolution under installed-bundle layout, and that the public
  aliases don't widen `dispatch_external`'s intended API (public-API snapshot gate will
  flag the additions — that flag is expected and should be approved as intentional).
