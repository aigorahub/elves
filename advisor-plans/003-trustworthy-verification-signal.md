# Plan 003: Make the verification signal honest on every host

> **Executor instructions**: Follow step by step; run every verification command and
> confirm the expected result before continuing. On any STOP condition, stop and
> report. When done, update this plan's row in `advisor-plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 9731fc3..HEAD -- tests/test_provider_shortcuts.py scripts/run_fugu.sh scripts/run_grok.sh scripts/run_devin.sh scripts/verify_repo.py .ai-docs/context-index.md .ai-docs/gotchas.md README.md`
> On changes, re-verify excerpts; mismatch = STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests / dx
- **Planned at**: commit `9731fc3` (v2.17.1), 2026-07-27

## Why this matters

Three related defects make "is the repo healthy?" answer wrongly depending on host:
(1) on a stock-macOS Python 3.9 host the suite reports 25 failures + 2 errors instead
of skips, because `run_fugu.sh`'s embedded Python uses 3.10+ union syntax and the tests
that spawn it never gate on the interpreter floor; (2) the runner scripts themselves
crash with a raw `TypeError` at `<stdin>` instead of a floor message; (3) the canonical
gate `verify_repo.py --ci` refuses to run without a hand-typed `--version`, and the
version literal already went seven releases stale in `.ai-docs` (a clean tree fails the
stale command three ways). After this plan: sub-floor hosts skip cleanly, runners print
a clear floor message, the gate self-resolves its version, and no doc needs a version
literal in the gate command. The repo floor also becomes a documented user-facing fact.

## Current state

- `tests/test_provider_shortcuts.py:137` — `class LocalCliRunnerTests(unittest.TestCase):`
  and `:1550` — `class RemoteApiRunnerTests(unittest.TestCase):`. Neither class (nor the
  module) gates on `sys.version_info`; their tests spawn `scripts/run_*.sh` via a
  `run_script` helper.
- The repo's own correct pattern, `tests/test_installed_bundle_smoke.py:27-31`:

  ```python
  @unittest.skipIf(
      sys.version_info < (3, 10),
      "installed_bundle_smoke requires Python >= 3.10 (repo floor); skipping on older interpreter",
  )
  ```

- `scripts/run_fugu.sh:160` — `exec python3 - "${PYTHON_ARGS[@]}" <<'PY'` with no floor
  guard before it; the heredoc's 3.10+ syntax (e.g. `section: str | None = None`)
  produces `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` at
  def time on 3.9. `run_grok.sh` and `run_devin.sh` use the same
  `exec python3 - ... <<'PY'` shape (smaller heredocs; check whether their bodies are
  3.9-fatal too — guard them regardless, for uniformity).
- The message style to imitate exists in `scripts/sync_installed_skills.py` (~:498):
  it prints a "requires Python >= 3.10 (repo floor); found X.Y" error and exits.
- `scripts/verify_repo.py:1756-1758` — the `--version` option, help text "Pin release
  checklist to this version (required for --ci/final readiness)"; `:1830` —
  `parser.error("--ci and --final-readiness require --version")`. The version is
  passed through to the release checklist at `:319` (`cmd.extend(["--version", version])`).
- `scripts/consistency_engine.py:22-24`:

  ```python
  def read_frontmatter_version(path: Path) -> str | None:
      match = re.search(r'^\s*version:\s*"([^"]+)"\s*$', read_text(path), re.MULTILINE)
      return match.group(1) if match else None
  ```

  `SKILL.md` frontmatter carries `version: "2.17.1"` (also `AGENTS.md:2`). Check how
  `verify_repo.py` already imports sibling script modules (top of file) and mirror it.
- Stale literals that fail on a clean tree: `.ai-docs/context-index.md:138` and `:144`
  plus `.ai-docs/gotchas.md:59` all say `python3 scripts/verify_repo.py --version 2.10.0`
  (README's maintainer block correctly says 2.17.1 today, ~:402-407).
- The Python floor is user-facing documented nowhere; `README.md` install/quick-start
  sections and `guide/index.html` install blocks state no minimum.
- Conventions: stdlib-only; bash 3.2-safe shell; `guide/index.html` prose must not use
  em dashes (PRODUCT.md rule) if you touch it.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused (this plan's core) | `python3 -m unittest tests.test_provider_shortcuts` | on <3.10: OK with skips, 0 failures; on ≥3.10: OK |
| Shell syntax | `bash -n scripts/run_fugu.sh scripts/run_grok.sh scripts/run_devin.sh` | exit 0 |
| Gate (≥3.10 host) | `python3 scripts/verify_repo.py --ci` | runs without `--version`, same result as with it |
| Consistency | `python3 scripts/check_repo_consistency.py` | exit 0 |
| Release gate | `python3 scripts/release_checklist.py --allow-unreleased` | exit 0 |

## Scope

**In scope:** `tests/test_provider_shortcuts.py`, `scripts/run_fugu.sh`,
`scripts/run_grok.sh`, `scripts/run_devin.sh`, `scripts/verify_repo.py`,
`.ai-docs/context-index.md`, `.ai-docs/gotchas.md`, `README.md` (one sentence),
`guide/index.html` (one sentence in the install block), and — only if the consistency
checker pins one of the edited sentences — `scripts/consistency_policy.py` in the same
change (repo coupling rule).

**Out of scope:** extracting the heredoc (plan 004); `run_manus.sh` (pure shim, no
heredoc); adding floor guards to every Python script (backlog DX-03 sweep); changing
CI workflow files.

## Git workflow

- Branch: `advisor/003-trustworthy-verification-signal`
- Commit per step; imperative subjects. Do NOT push/PR unless the operator instructed.

## Steps

### Step 1: Floor-skip the provider-shortcut classes

Add the `@unittest.skipIf(sys.version_info < (3, 10), ...)` decorator (copy the exact
style from `tests/test_installed_bundle_smoke.py:27-31`, reason text naming
`run_fugu.sh`'s embedded Python) to BOTH `LocalCliRunnerTests` and
`RemoteApiRunnerTests`. Ensure `import sys` exists in the module.

**Verify** (on this 3.9 host if available, else note):
`python3 -m unittest tests.test_provider_shortcuts` → `OK (skipped=55)` (all tests
skipped, 0 failures, 0 errors). On a ≥3.10 host: unchanged pass.

### Step 2: Floor-guard the three runner scripts

In each of `run_fugu.sh`, `run_grok.sh`, `run_devin.sh`, immediately before the
`exec python3 - ... <<'PY'` line, insert (bash-3.2-safe, no new deps):

```bash
python3 - <<'FLOOR' || exit 2
import sys
if sys.version_info < (3, 10):
    sys.stderr.write(
        "run_%s requires Python >= 3.10 (repo floor); found %d.%d\n"
        % ("SCRIPTNAME", sys.version_info[0], sys.version_info[1])
    )
    raise SystemExit(1)
FLOOR
```

with `SCRIPTNAME` per file (or an equivalent single-line `python3 -c` guard — either
is fine; the heredoc form avoids quoting hazards). Keep each script's existing exit
codes for other failures untouched.

**Verify**: `bash -n` all three → exit 0. On a 3.9 host:
`scripts/run_fugu.sh --help 2>&1 | head -2` → the floor message, exit 2 — NOT a
TypeError. (If `--help` short-circuits before the guard, test with a harmless task
argument instead; the assertion is "floor message, not traceback".)

### Step 3: Default `verify_repo --version` from SKILL.md frontmatter

In `verify_repo.py`: where `--ci`/`--final-readiness` currently `parser.error` on a
missing `--version` (:1830 area), instead resolve a default:
`read_frontmatter_version(repo_root / "SKILL.md")` — import it the same way the file
imports other sibling-module helpers (check its existing imports; both
`consistency_engine` and `release_checklist` expose `read_frontmatter_version`-style
helpers — use whichever the file already has access to without new sys.path tricks).
Only if resolution returns `None`, keep the existing `parser.error`. Update the
`--version` help text to say "(defaults to SKILL.md frontmatter version)".

**Verify** (≥3.10 host): `python3 scripts/verify_repo.py --ci` runs and reports the
same gates as `python3 scripts/verify_repo.py --ci --version 2.17.1`. On this 3.9 host
the suite gate will fail for unrelated floor reasons — verify only that argument
parsing no longer errors: `python3 scripts/verify_repo.py --ci 2>&1 | head -3` shows a
gate starting, not an argparse error.

### Step 4: Fix the stale doc literals

Replace the three stale commands: `.ai-docs/context-index.md:138` and `:144`, and
`.ai-docs/gotchas.md:59` — drop the `--version 2.10.0` argument entirely (now valid
per step 3), keeping any other flags (`--final-readiness --session <session-path>`).

**Verify**: `grep -rn "2\.10\.0" .ai-docs/` → no matches;
`python3 scripts/check_repo_consistency.py` → exit 0.

### Step 5: Document the floor, user-facing

Add one sentence "Requires Python 3.10 or newer." to the README quick-start/install
section (near the first `sync_installed_skills.py` command) and one equivalent plain
sentence to `guide/index.html`'s install block (match surrounding prose style; NO em
dashes or emoji per PRODUCT.md). Run the consistency checker; if it flags a pinned
sentence you edited, update the corresponding pin in `scripts/consistency_policy.py`
in the same commit (coupling rule).

**Verify**: `python3 scripts/check_repo_consistency.py` → exit 0;
`python3 scripts/release_checklist.py --allow-unreleased` → exit 0.

## Test plan

- Step 1 IS the test change (floor skips). Add no other tests; assert final counts:
  on 3.9: `test_provider_shortcuts` → 55 skipped / 0 failed; full discovery on 3.9 →
  0 failures, 0 errors (skips grow by ~55).
- On ≥3.10 nothing changes: same pass/fail totals as before the plan.

## Done criteria

- [ ] 3.9 host: `python3 -m unittest tests.test_provider_shortcuts` → OK, 0 failures/errors
- [ ] 3.9 host: `python3 -m unittest discover -s tests -t .; echo "exit=$?"` → `exit=0` (capture the exit status directly, not through a pipe)
- [ ] `bash -n` clean on all three runners; a 3.9 invocation prints the floor message
- [ ] ≥3.10 host (or CI): `verify_repo.py --ci` works with no `--version`
- [ ] `grep -rn "2\.10\.0" .ai-docs/` → empty
- [ ] README and guide each state the 3.10 floor once
- [ ] consistency + release checklist exit 0
- [ ] `advisor-plans/README.md` row updated

## STOP conditions

- Excerpted lines don't match (drift).
- `verify_repo.py` cannot import a frontmatter reader without sys.path surgery —
  report the import options instead of hacking paths.
- The consistency checker flags edits whose pins you cannot confidently update.
- Step 1's skip leaves ANY failure on the 3.9 host (means another module shares the
  problem — report which).

## Maintenance notes

- Plan 004 (heredoc extraction) will later make the fugu Python importable; the floor
  guard in the shim stays correct after that move.
- The versionless gate command means release docs never carry a version literal again;
  reviewer should confirm CI still passes its explicit `--version` (workflow unchanged).
- Deferred: a shared `require_python_floor()` for all 19 script entry points (survey
  DX-03) and CI capture of the suite exit code without pipes.
