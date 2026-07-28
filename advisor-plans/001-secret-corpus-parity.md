# Plan 001: Close the redaction parity gap and unify the secret corpora

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If anything
> in "STOP conditions" occurs, stop and report — do not improvise. When done, update
> the status row for this plan in `advisor-plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 9731fc3..HEAD -- scripts/cobbler_runtime/context.py scripts/cobbler_runtime/setup.py scripts/cobbler_agents.py scripts/cobbler_runtime/isolation.py scripts/openrouter_lens.py scripts/cobbler_runtime/manus.py scripts/notify.sh scripts/preflight.sh`
> If any listed file changed since `9731fc3`, compare the "Current state" excerpts
> against the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (patterns) / MED (deny-list union — see step 6)
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `9731fc3` (v2.17.1), 2026-07-27

## Why this matters

The repo redacts secrets at two boundaries: a Python corpus
(`context.SECRET_VALUE_PATTERNS`, used by run-artifact persistence AND by the release
secret scan in `verify_repo.py`) and a sed pipeline in `notify.sh`/`preflight.sh`. The
shell boundary redacts Slack incoming-webhook URLs and colon-less URL userinfo tokens
(`scheme://TOKEN@host`); the Python corpus redacts neither, so those shapes persist
verbatim into `.elves/**` run artifacts and pass the release scan. A separately drifted
pattern copy lives in `setup.py`, and four sites in `cobbler_agents.py` print JSON
payloads without the redaction pass that the module's own `_emit_json` applies. One
authoritative corpus plus a parity test ends the drift class.

## Current state

- `scripts/cobbler_runtime/context.py:105-131` — `SECRET_VALUE_PATTERNS`. First entry:

  ```python
  ("uri_userinfo", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")),
  ```

  Note the required `:` between user and password — `https://ghp_xxx@github.com` does
  NOT match. There is no Slack-webhook pattern in the tuple.
- `scripts/cobbler_runtime/context.py:24-49` — `_SECRET_NAME_MARKERS` tuple
  (`"KEY", "TOKEN", ... "BEARER"`); no `"WEBHOOK"` entry, so `ELVES_SLACK_WEBHOOK` is
  not classified secret by name.
- `scripts/notify.sh:38-39` (and the byte-identical block in `scripts/preflight.sh`,
  ~lines 35-40) — the shell rules that DO cover both shapes:

  ```
  -e 's#([a-z][a-z0-9+.-]*://)[^/@[:space:]]+@#\1[REDACTED]@#gI' \
  -e 's#(https://hooks\.slack\.[^/[:space:]]+/services/)[^/[:space:]]+/[^/[:space:]]+/[^/[:space:]?]+#\1[REDACTED]#gI' \
  ```

- `scripts/cobbler_runtime/setup.py:51-58` — a private drifted copy:

  ```python
  _SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
      re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*=\s*[\"']?[^$\"'\s#]+"),
      re.compile(r"\bsk-[A-Za-z0-9]{10,}"),
      re.compile(r"\bxai-[A-Za-z0-9]{10,}"),
      re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
      re.compile(r"/Users/[^\s\"']+"),
      re.compile(r"/home/[^\s\"']+"),
  )
  ```

  The token rules are narrower than context's (no `gho_`, `ghu_/ghs_`, `github_pat_`,
  `AKIA`, PEM); the two path rules are setup-specific and NOT in context — keep them.
- `scripts/cobbler_agents.py:246` — `def _emit_json(payload, *, exit_code, exact_secret_values=...)`
  is the redacting emitter. Four sites bypass it with
  `print(json.dumps(payload, indent=2, sort_keys=True))`: lines **348, 1969, 2097, 2125**.
- Deny lists (three, divergent): `scripts/cobbler_runtime/isolation.py:148-173`
  (`DEFAULT_EXCLUDED_FILE_NAMES` — has `.env*`, `models.toml`, `.netrc`, `.npmrc`,
  `.pypirc`, `credentials`, ...), `scripts/openrouter_lens.py:50-71`
  (`_SENSITIVE_FILE_NAMES` + `_SENSITIVE_PATH_PARTS` — has `.dockercfg`,
  `.git-credentials`, path parts `.aws .git .gnupg .ssh ...`),
  `scripts/cobbler_runtime/manus.py:41-58` (`SECRET_FILE_NAMES` — has `.pgpass`,
  `kubeconfig`).
- Conventions: errors are fail-closed `ValidationIssue` objects with stable snake_case
  codes (see `scripts/cobbler_runtime/schema.py`); tests are stdlib `unittest`, hermetic
  (no network); pure stdlib only — no new dependencies.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Compile | `python3 -m compileall -q scripts` | exit 0, no output |
| Consistency | `python3 scripts/check_repo_consistency.py` | exit 0 |
| Focused tests | `python3 -m unittest tests.test_dispatch_isolation tests.test_notify_sh` | OK (skips allowed) |
| Full suite (needs Python ≥3.10) | `python3 -m unittest discover -s tests -t .` | `OK (skipped=...)`, 0 failures/errors |
| Release gate | `python3 scripts/release_checklist.py --allow-unreleased` | exit 0 |

## Scope

**In scope (only files you may modify):**
- `scripts/cobbler_runtime/context.py`
- `scripts/cobbler_runtime/setup.py`
- `scripts/cobbler_agents.py`
- `scripts/cobbler_runtime/isolation.py`
- `scripts/openrouter_lens.py`
- `scripts/cobbler_runtime/manus.py`
- `tests/test_secret_redaction_parity.py` (create)
- Existing test modules ONLY where a fixture asserts on the old pattern/list contents.

**Out of scope:**
- `scripts/notify.sh` and `scripts/preflight.sh` — the shell rules are correct today;
  this plan makes Python match them, not the reverse. Do not edit the sed pipeline.
- `scripts/verify_repo.py` — it imports the shared corpus and inherits the fix.
- Any change to what `redact_text` returns for currently-matched shapes.

## Git workflow

- Branch: `advisor/001-secret-corpus-parity`
- One commit per step or logical pair; imperative one-line subjects matching `git log`
  style (e.g. "Add Slack webhook and colon-less userinfo redaction patterns").
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the two missing patterns to `SECRET_VALUE_PATTERNS`

In `context.py`, add to the tuple (keep existing entries untouched):

```python
("slack_webhook", re.compile(r"(?i)https://hooks\.slack\.[^/\s]+/services/[^/\s]+/[^/\s]+/[^\s?\"']+")),
("uri_userinfo_bare", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[A-Za-z0-9._~%+-]{8,}@")),
```

Keep the existing `uri_userinfo` entry as-is. The bare rule requires ≥8 token chars so
`https://user@host` mailto-style short userinfo is untouched.

**Verify**: `python3 -c "from pathlib import Path; import sys; sys.path.insert(0,'scripts'); from cobbler_runtime.context import redact_text; t=redact_text('x https://hooks.slack.example/services/T000/B000/deadbeefdeadbeef y https://ghp_0123456789abcdefghij@github.com/o/r'); print(t)"`
→ output contains `[REDACTED]` at least twice and contains neither `deadbeef` nor `ghp_`.
(If `redact_text` has a different signature, read its def in `context.py` and adapt the
probe — the assertion is what matters.)

### Step 2: Add `WEBHOOK` to `_SECRET_NAME_MARKERS`

Append `"WEBHOOK",` to the tuple at `context.py:24-49`.

**Verify**: `python3 -c "import sys; sys.path.insert(0,'scripts'); from cobbler_runtime.context import is_secret_env_name; print(is_secret_env_name('ELVES_SLACK_WEBHOOK'))"` → `True`.
(If the helper has a different name, grep `context.py` for `_SECRET_NAME_MARKERS`
consumers and probe that function.)

### Step 3: Replace `setup.py`'s drifted copy

In `setup.py`, delete the four token regexes from `_SECRET_VALUE_PATTERNS` and build it
as the shared corpus plus the setup-local path rules:

```python
from .context import SECRET_VALUE_PATTERNS as _SHARED_SECRET_PATTERNS

_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    *(pattern for _name, pattern in _SHARED_SECRET_PATTERNS),
    re.compile(r"/Users/[^\s\"']+"),
    re.compile(r"/home/[^\s\"']+"),
)
```

Match the module's existing import style (it is inside `cobbler_runtime`, so a relative
import is correct if siblings use one — check the file's other imports first).

**Verify**: `python3 -m compileall -q scripts` → exit 0, then
`python3 -m unittest tests.test_cobbler_agents_setup 2>/dev/null || python3 -m unittest discover -s tests -t . -p "test_*setup*.py"` → OK.
(If no setup-specific test module exists, note that in the commit message.)

### Step 4: Route the four bare prints through `_emit_json`

At `cobbler_agents.py` lines 348, 1969, 2097, 2125, replace
`print(json.dumps(payload, indent=2, sort_keys=True))` with a call to `_emit_json`
matching its signature at :246 (pass the exit code the surrounding code currently uses —
read each site's context; if the site does not exit, use the variant/argument that only
prints, or refactor `_emit_json` minimally to allow `exit_code=None`). Line numbers may
be ±5 after steps 1–3; locate by grepping
`grep -n "json.dumps(payload, indent=2, sort_keys=True)" scripts/cobbler_agents.py`.

**Verify**: the grep above returns 0 matches; `python3 -m compileall -q scripts` → exit 0.

### Step 5: Add the parity test

Create `tests/test_secret_redaction_parity.py` (stdlib unittest, hermetic):

- Build a corpus of synthetic secret strings, one per named pattern in
  `SECRET_VALUE_PATTERNS` (use clearly fake values, e.g. `ghp_` + 20 `x`s — never real
  shapes from the environment).
- Assert every corpus entry is changed by `context.redact_text`.
- Pipe the same corpus through the shell boundary:
  run `bash -c 'source /dev/stdin <<EOF ... EOF'`-free approach — simplest is
  `subprocess.run(["bash", "-c", "printf '%s' \"$1\" | <the redact function>"], ...)` is
  fragile; instead extract the sed program: run
  `subprocess.run(["bash", "-c", "printf '%s\\n' " + shlex.quote(line) + " | bash " + shlex.quote(str(repo_root / 'scripts' / 'notify.sh')) + " --redact-stdin"], ...)`
  ONLY if `notify.sh` exposes such a mode — it does not today, so instead assert
  **name parity**: parse `notify.sh` and `preflight.sh` text and assert that for each of
  a fixed list of shape names (`slack_webhook`, `uri_userinfo`, `bearer`, `sk-`,
  `ghp_`), both a shell `-e 's#...#'` rule and a Python pattern exist. Model the test
  structure on `tests/test_notify_sh.py` (it already invokes the scripts and asserts
  redaction end-to-end for two shapes).
- Add one end-to-end case to the corpus check: the Slack URL and the bare-userinfo URL
  from step 1's probe.

**Verify**: `python3 -m unittest tests.test_secret_redaction_parity` → OK, ≥6 tests.

### Step 6: Unify the deny lists (careful — behavior-widening)

Create shared constants in `context.py`: `SECRET_FILE_NAMES`, `SECRET_FILE_GLOBS`,
`SECRET_PATH_PARTS`, each the **union** of the three existing lists (read all three in
full first; the excerpts above are heads, not complete lists). Then make
`isolation.DEFAULT_EXCLUDED_FILE_NAMES`, `openrouter_lens._SENSITIVE_FILE_NAMES`/
`_SENSITIVE_PATH_PARTS`, and `manus.SECRET_FILE_NAMES` consume the shared constants
(keeping any genuinely site-specific extras as explicit local additions, e.g.
`isolation`'s `models.toml` and `ELVES_SESSION_BASENAME`).

The union WIDENS `isolation.py`'s snapshot exclusions (e.g. `.git-credentials`,
`.pgpass`, `kubeconfig` newly excluded). Run the isolation tests and inspect any
failure: a fixture that plants one of the newly-excluded names and expects it copied
must be updated to acknowledge the exclusion — that is the intended behavior change.
Any OTHER kind of failure is a STOP condition.

**Verify**: `python3 -m unittest tests.test_dispatch_isolation` → OK;
`python3 -m unittest discover -s tests -t .` (on ≥3.10) → 0 failures/errors.

## Test plan

- New: `tests/test_secret_redaction_parity.py` — corpus round-trip through
  `redact_text`; shape-name parity between shell and Python lists; Slack + bare-userinfo
  regression cases. Pattern: `tests/test_notify_sh.py`.
- Updated: any isolation fixture that plants newly-excluded filenames.
- All synthetic values only. Never place a real-looking live credential in a fixture.

## Done criteria

- [ ] `python3 -m compileall -q scripts` exits 0
- [ ] `python3 -m unittest tests.test_secret_redaction_parity` passes with ≥6 tests
- [ ] `grep -n "json.dumps(payload, indent=2, sort_keys=True)" scripts/cobbler_agents.py` → no matches
- [ ] `grep -c "slack_webhook" scripts/cobbler_runtime/context.py` ≥ 1
- [ ] `grep -n "_SECRET_VALUE_PATTERNS: tuple" scripts/cobbler_runtime/setup.py` shows the shared-import form (no standalone `sk-`/`ghp_` literals remain in `setup.py`)
- [ ] Full suite on ≥3.10: 0 failures, 0 errors
- [ ] `git status` shows no modifications outside the in-scope list
- [ ] `advisor-plans/README.md` status row updated

## STOP conditions

- The `context.py` excerpts above don't match the live file (drifted base).
- Step 6 causes a test failure that is NOT a fixture planting a newly-excluded filename.
- `_emit_json`'s signature cannot accommodate a print-only call without changing its
  behavior for existing callers.
- You find yourself wanting to edit `notify.sh`/`preflight.sh` — out of scope.

## Maintenance notes

- Rotation: any Slack webhook or URL-embedded token that previously passed through
  `.elves/**` artifacts should be rotated — redaction fixes forward, not backward.
- Future patterns must be added to `context.SECRET_VALUE_PATTERNS` AND the shell rules;
  the parity test now fails if only one side is edited — keep it that way.
- Reviewer focus: the bare-userinfo pattern's ≥8-char floor (false-positive control) and
  step 6's isolation-test diffs.
- Deferred: converging the two shell copies themselves (generate the sed program from
  Python) — tracked as backlog item D-04-followup in the survey.
