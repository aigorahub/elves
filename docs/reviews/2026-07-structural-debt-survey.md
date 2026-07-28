# Structural debt survey — v2.10 → v2.17.1 growth audit

- **Date:** 2026-07-27. **Base:** v2.17.1 (`9731fc3`).
- **Method:** four parallel read-only auditors (correctness+security, tech-debt+DX,
  tests+performance, docs+migrations), each briefed with the repo's decided tradeoffs
  (host-parity restating surfaces, stdlib-only, fail-closed `ValidationIssue` idiom,
  serial-by-default Parallelves, the anti-accretion rule, open TODO items) so settled
  decisions were not re-reported. Every finding below was then re-verified by the driver
  against the cited lines; vetting corrections are recorded in section 5. Several claims
  were verified by execution, not just reading (the preflight abort, the redaction gaps,
  bash-3.2 compatibility, suite timings).
- **Prompt for this survey:** "the repo has evolved over time, so it might have become a
  bit of a jangled mess." Executor-ready plans for the top five findings are in
  `advisor-plans/` (see section 7).

## 1. Measured baseline (this machine: macOS, stock Python 3.9.6, bash 3.2)

| Measurement | Result |
|---|---|
| Full suite | 1401 tests, 320 s in-suite / 6 m 12 s wall |
| Verdict on a 3.9 host | FAILED: 25 failures + 2 errors (all `test_provider_shortcuts`) + 44 skips |
| Slowest modules | `test_cobbler_agents_leases` 87 s, `test_full_run_supervisor` 81 s, `test_worker_cli_lifecycle` 39 s — 65% of suite |
| `check_repo_consistency.py` | 0.31 s |
| `release_checklist.py --allow-unreleased` | 0.25 s |
| Repo mass | `scripts/cobbler_runtime/` ~51k lines, `scripts/` ~24k, `tests/` ~47k (49 modules), `references/` ~10k |

## 2. Verdict: where it is and is not a mess

**Not a mess.** The core architecture held up well under the v2.12–v2.17 sprint: the
isolation substrate is genuinely shared across all four provider lanes (only the thin
provider-home prologue is per-lane); the import graph has zero runtime cycles across 45
runtime modules; `schema.py` is a clean high-fan-in contract module; there is no
commented-out code and no stray TODO/FIXME in source; the big Python modules
(`full_run.py` 7837, `cobbler_agents.py` 3318, `audit.py` 4144, `verify_repo.py` 2026)
have taken **zero commits since v2.12** — their size is a comprehension cost, not a defect
source; the test-hermeticity guard (fd-0 closed at descriptor level) is exemplary; the
alias sync marker gate is conservative and correct; and `provider_supervisor.py` already
demonstrates the correct pattern for "embedded program as a real lintable file."

**The mess, where it exists, is concentrated and specific:**

1. **`run_fugu.sh` is the epicenter.** 1,762 of its 1,921 lines are Python inside a quoted
   heredoc — the repo's largest and fastest-churning source file (8 commits since v2.12,
   while the god modules took none), invisible to `compileall`, `bash -n`, any linter, any
   unit test, and any editor traceback. It imports five private symbols from another
   module with no tool able to check the contract. It is also why a 3.9 host shows 27 red
   tests instead of skips.
2. **Safety-relevant constants have forked.** Three divergent secret-file deny lists, a
   redaction corpus maintained in parallel in bash and Python that has already drifted
   (Slack webhooks redacted at the shell boundary, not in Python — and the release gate
   shares the Python gap), two independent copies of the Darwin ctypes process-inspection
   ABI, nine git-invocation helpers with four hardening postures, three dotenv parsers
   with three safety postures.
3. **The drift-guard machinery guards reactively.** 137 pin groups / 1,440 entries, 43%
   of which are the same phrase hand-pinned per surface; two documented drift incidents
   (v2.16.1, v2.17.1) shipped one release apart despite the pins, because coverage is
   only ever as complete as the last incident.
4. **The verification signal lies on some hosts.** No floor guard in the runner scripts,
   floor gates on only 2 of 19 entry-point scripts, a canonical gate command that
   requires a hand-typed version (already seven releases stale in `.ai-docs`), and a
   6-minute serial suite paid in full by all four CI cells.

## 3. Top findings by leverage

| # | Finding | Cat | Impact | Effort | Risk | Conf | Plan |
|---|---------|-----|--------|--------|------|------|------|
| 1 | Redaction parity gap: Slack webhooks + colon-less URL tokens survive into persisted artifacts; release gate shares the gap; drifted pattern copy in `setup.py`; 4 unredacted JSON print sites | security | secrets persist in run artifacts | S/M | LOW | HIGH | 001 |
| 2 | `preflight.sh` aborts at section 2/14 on alternate `gh auth status` wording (reproduced here) | bug | operators lose the entire preflight before unattended runs | S | LOW | HIGH | 002 |
| 3 | Suite has no honest verdict on <3.10 hosts (25F/2E instead of skips); runners crash with raw `TypeError`; gate command requires hand-typed version and is 7 releases stale in `.ai-docs` | tests/dx | false red locally, false confidence from stale docs | S | LOW | HIGH | 003 |
| 4 | `run_fugu.sh` heredoc: 1,762 untooled Python lines, private cross-module imports, top churn file | debt | largest file invisible to every tool | M/L | MED | HIGH | 004 |
| 5 | `tar.extractall` fail-open fallback on 3.10.0–3.10.11 / 3.11.0–3.11.3 (inside the supported floor) with a caller-supplied ref | security | unfiltered extraction in the API-compat gate | S | LOW | MED | 005 |
| 6 | ~20 subprocess sites ignore the repo's own bounded/stdin-closed contract (`ps`, git, curl, the API-snapshot inspector) | bug | wedged unattended runs with no `TimeoutExpired` to classify | M | MED | HIGH | backlog |
| 7 | `.elves-session.json` written non-atomically two different ways while the hardened atomic idiom sits one module away | bug | truncated/lost landing-authority state on crash or concurrency | M | MED | HIGH | backlog |
| 8 | `run_grok.sh` is the only provider lane with no wall clock and no process-group containment | bug | hung Grok CLI blocks forever; descendants orphaned | M | MED | HIGH | backlog |
| 9 | Consistency-pin corpus needs an inverted (phrase → surface-set) form; `check_repo_consistency.main()` is one 660-line function with 11 inline loop copies and one provably dead check | debt | drift guard is reactive; two incidents in two releases | M | LOW | HIGH | backlog |
| 10 | Secret-file deny lists (3), Darwin ctypes ABI (2), git helpers (9/4 postures), dotenv parsers (3) — forked safety constants | debt | fixes land in one copy and miss the others | S–M each | MED | HIGH | 001 covers lists; rest backlog |
| 11 | Suite economics: 65% of 6 min in 3 modules; 43 real git-repo builds in one module; CI pays serial cost ×4 cells | perf | devs stop running the suite; CI is first signal | M | MED | HIGH | backlog |
| 12 | 90 Ruff `noqa` directives but no linter configured or run anywhere; `bash -n` is the only shell gate for 3.3k shell lines | dx | suppressions maintained for a tool that never runs | S | LOW | HIGH | backlog |
| 13 | Native-worker identity-timeout teardown lacks the Darwin EPERM tolerance + TERM→KILL→reap escalation every sibling has | bug | raw `PermissionError` replaces the stable error code; orphaned provider | S | LOW | HIGH | backlog |
| 14 | Docs drift siblings of the v2.17.1 `--max` fix: SKILL.md grammar line missing `--write`/`--include`; `--` separator and repeatable `--include` documented nowhere; `worker.parallel` absent from `config.json.example`; glossary missing ~12 post-v2.14 coined terms | docs | canonical surface teaches an incomplete grammar | S–M | LOW | HIGH | backlog |

## 4. Full finding registry (condensed; all driver-vetted)

### Correctness

- **C-01 preflight gh-parse abort** — `preflight.sh:201-202` under `set -euo pipefail`:
  `grep -o "account [^ ]*"` exits 1 on `Logged in to github.com as <user>` wording, killing
  sections 3–14. Only the matching wording is tested (`tests/test_preflight_sh.py:38`).
  Reproduced. → plan 002.
- **C-02 native_worker teardown** — `native_worker.py:1100-1107` catches only
  `ProcessLookupError`; Darwin EPERM escapes and replaces `native_worker_identity_timeout`;
  single SIGTERM, no grace/KILL/reap. The correct idiom exists at `implement.py:1616-1624`
  and `run_fugu.sh:1242-1255`. S/LOW/HIGH.
- **C-03 unbounded subprocess sites** — the written contract (`leases.py:281-296`:
  bounded, stdin-closed, hardened env) is ignored by `public_api_snapshot.py:1276,1334`
  (runs repo modules, no timeout), `isolation.py:273,298` (git ls-files, inherited stdin —
  while `:363` does it right), `full_run.py:1941,2020` + `native_worker.py:468` (`ps` on
  the monitor hot path), `elves_landing_check.py:1086`, `delegated_git.py:58`,
  `workspace_guard.py:322`, and `notify.sh:148` / `preflight.sh:508,604` curl/fetch with
  no `--max-time`. ~20 sites. Fix: route git through `leases.run_git`; add
  timeouts/stdin=DEVNULL; consistency grep to prevent regression. M/MED/HIGH.
- **C-04 session-file writes** — `workspace_guard.py:466` bare `write_text` (non-atomic,
  unlocked read-modify-write, symlink-following) and `elves_landing_check.py:1435-1437`
  predictable tmp name + `write_text` + `os.replace`; the hardened idiom exists at
  `provider_auth.py:1296-1345` and the shared helper at `storage.py:386-465`
  (`atomic_write_json` + `directory_lock`). M/MED/HIGH.
- **C-05 run_grok.sh unbounded** — `run_grok.sh:170-176`: no timeout, no
  `start_new_session`, no teardown; every sibling lane enforces a wall budget and
  containment (`run_fugu.sh:1228-1278`, `run_devin.sh:82-116`,
  `dispatch_external.py:1223-1281`). M/MED/HIGH.
- **C-06 supervisor error erasure** — `dispatch_external.py:466`: successful `scan()`
  unconditionally sets `self.error = None`, erasing identity failures recorded by
  `run_fugu.sh:688-698`; `root_absence_proven` conflates "absent" with "identity read
  failed"; `settle()` drops `supervision_error` on non-success paths. S/MED/MED.
- **C-07 refused-launch reap swallow** — `provider_auth.py:1018-1034`: reap timeout
  swallowed, then pid/pgid/fingerprint nulled → unattributable possibly-live supervisor;
  file-unlink failures raise but reap failures don't. Also a misplaced docstring (no-op)
  at :1003-1005. S/LOW/MED.
- **C-08 stdin write before deadline** — `run_fugu.sh:1341-1347` writes the (unbounded,
  caller-controlled) prompt into a pipe before arming `wait_deadline`; a non-draining
  provider blocks the launcher outside the budget the file spends 700 lines defending.
  S/LOW/MED.

### Security

- **S-01 redaction parity** — `context.py:105-131` lacks a Slack-webhook pattern and its
  `uri_userinfo` requires a colon, so `scheme://<token>@host` shapes pass; the shell
  boundary (`notify.sh:38-39`, `preflight.sh:37-48`) redacts both (verified by executing
  both paths). The release gate (`verify_repo.py:1456,1550`) imports the same Python
  corpus, doubling the gap. `_SECRET_NAME_MARKERS` lacks `WEBHOOK`, so
  `ELVES_SLACK_WEBHOOK` is never exact-value-collected. A drifted narrower copy lives at
  `setup.py:51-58` despite `context.py:133-136`'s "cannot silently drift apart" note.
  Provider stdout/stderr and audit payloads persist post-`redact_text`
  (`dispatch_results.py:141-166`, `native_worker.py:793`, `audit.py:1069,1150,1240`).
  Related hygiene: `cobbler_agents.py` has a redacting `_emit_json` (:246) but four sites
  print payloads with bare `json.dumps` (:348, :1969, :2097, :2125). Rotate any webhook
  or URL-embedded token that has passed through run artifacts. → plan 001.
- **S-02 tar fail-open** — `public_api_snapshot.py:1701-1704`: `filter="data"` with
  `except TypeError: tar.extractall(temp_root)`; `filter=` exists only from 3.10.12 /
  3.11.4, so floor-supported interpreters silently extract unfiltered from a
  caller-supplied `git archive` ref. → plan 005.
- **S-03 endpoint validation** — `run_devin.sh:29,119-129` and `manus.py:657,677-687`
  attach bearer/API-key headers to unvalidated env-supplied base URLs (no https/host
  check); `manus.py:757-771` PUTs attachment bodies to a fully response-controlled
  `upload_url`. Neither env override is documented anywhere. S/LOW/MED.
- **S-04 append TOCTOU** — `landing_profile_learn.py:266-286`: `lstat` validation then
  name-based `open(path, "ab")` + symlink-following `chmod`; the repo's own
  `O_NOFOLLOW`+`fstat` idiom (`storage.py:1225-1240`, `isolation.py:567-605`,
  `provider_supervisor.py:109-156`) treats worktree-resident files as untrusted.
  S/LOW/MED.
- **Negative results:** no shell injection (zero `shell=True`/`eval`/`exec` in Python;
  the one shell `eval` is the user's own `ELVES_NOTIFY_CMD` with a recorded decision
  comment), no committed credentials, no prompt-injection-shaped content anywhere.

### Tech debt & architecture

- **D-01 fugu heredoc** (→ plan 004) and **D-02 lane convergence** — `manus.py` +
  6-line shim is the converged pattern; grok (161 embedded lines) and devin (213) should
  follow after fugu; then lift the common provider-home prologue into one helper.
- **D-03 Darwin ctypes duplication** — `dispatch_external.py:66-140` vs
  `implement.py:177-251`: byte-identical `ctypes.Structure` layouts differing in ~6
  lines; two `_darwin_process_record()`s with the same magic `18`. Memory-safety-relevant.
  S/MED/HIGH.
- **D-04 deny-list fork** — `isolation.py:148-173` / `openrouter_lens.py:50-71` /
  `manus.py:41-58` each hold entries the others lack (details in plan 001).
- **D-05 three dotenv parsers** — hardened (`run_fugu.sh:362`), unhardened-and-shipped
  (`openrouter_lens.py:78`, writes into `os.environ`), names-only (`onboard.py:361`).
  S/LOW/HIGH.
- **D-06 nine git helpers, four postures** — byte-identical pair
  (`preflight_worktree.py:29` = `worktree_gc.py:31`), hardened reference
  (`leases.py:290` + `audit.py:106`), different hardening (`landing_profile.py:802`),
  none (`elves_landing_check.py:1086`, `delegated_git.py:58`, `workspace_guard.py:320`).
  `tests/__init__.py:6-11` records the 3-hour-freeze incident this class causes. M/MED/HIGH.
- **D-07 pin corpus shape** — 1,440 entries / 1,020 phrases; 199 phrases pinned 2–8×
  (43% of corpus); engine has no phrase→surface-set broadcast form
  (`consistency_engine.py:41`); two shipped drift incidents (`72ae480`, `7d61cd1`)
  despite pins; one flag addition touched 11 files (`1f8ab5e`). M/LOW/HIGH.
- **D-08 checker shape** — `check_repo_consistency.py`: one 660-line `main()`, 11 inline
  reimplementations of `find_missing_phrases`, 25 hand-maintained success `print`s,
  `import *` from the policy. M/LOW/HIGH.
- **D-09 dead Codex-Goals check** — `CODEX_GOALS_SECTION_HEADINGS = {}` (empty) makes the
  22-line check at `check_repo_consistency.py:262-283` unable to ever fire. Populate or
  delete. S/LOW/HIGH (see vetting note, §5).
- **D-10 full_run.py seams** — decomposition already TODO #92; concrete seams mapped
  (streaming decode ~590 lines at :5273-5866; process fingerprint ~570; redaction+bounded
  I/O ~390; `monitor_full_run` alone 810). **De-prioritized on evidence**: 0 commits since
  v2.12 — extract the streaming cluster only when the file must change again.
- **D-11 cobbler_agents shape** — 926-line `build_parser`; `cmd_worker` 414 lines,
  `cmd_implement` 348 with 13-way if-chains; session-resolution policy inline in the CLI
  layer. Stable (0 commits since v2.12) → mechanical split when next touched. M/LOW/HIGH.
- **D-12 context.py junk drawer** — 654 lines, 15 importers, five concerns (secrets,
  env allowlist, packets, path containment, writers); docstring frames it as
  Council-specific which 14/15 importers are not. Split → `secrets.py` + `paths.py` with
  re-export shims. M/LOW/HIGH.
- **D-13 unreferenced meta-tooling** — `pr_portfolio_report.py` (302 + test) reachable
  from no documented workflow; the repo's own anti-accretion rule makes it the deletion
  candidate. Confirm intent first (MED confidence it's deliberate). All other suspects
  (openrouter_lens, install_doctor, preflight_worktree, worktree_gc, workspace_guard)
  verified referenced.
- **D-14 CLI/envelope inconsistency** — four argparse conventions, five JSON "did it
  pass" envelopes, `ValidationIssue` in 1/19 top-level scripts, and the four unredacted
  print sites (folded into plan 001). Standardize opportunistically.

### Tests & performance

- **T-01 floor skips** (→ plan 003): `test_provider_shortcuts` classes gate on sandbox
  and platform but never `sys.version_info`; the correct pattern exists at
  `test_installed_bundle_smoke.py:29-30`.
- **T-02 heredoc invisible to gates** — verified empirically that `bash -n` passes a
  script whose quoted heredoc contains invalid Python; `compile_scripts` only globs
  `*.py`. Cheap gate: slice `<<'PY'` blocks and `py_compile` them (step 0 of plan 004).
- **T-03 focused-gate map** — `verify_repo.py:375-424` maps 7 of 27 scripts and no shell;
  unmapped paths silently fall back to one unrelated module
  (`tests.test_architecture_evidence`). Convention-based resolution + escalate-on-unmapped.
  S/LOW/HIGH.
- **T-04 provider test split** — `test_provider_shortcuts.py`: 2,961 lines, 32 commits
  since v2.10.4 (2.6× any other test file), four providers serialized in one file; split
  per provider with shared fixtures in `tests/support/`. M/LOW/HIGH.
- **T-05 timing-flake siblings** — `test_full_run_supervisor.py:3562-3568` (2 s budget
  minus 1 s grace for a reap), five 1 s-budget/2 s-assert bash-spawn tests in
  `test_provider_shortcuts.py` (:1612,:1652,:2863,:2888,:2912), 3 s marker waits at
  :3543,:3696; several use `time.time()` not `monotonic()`. Budget-relative bounds +
  one `_wait_until` helper. S/LOW/HIGH-shape.
- **T-06 mkdtemp leaks** — `test_dispatch_isolation.py:3114,3160,3313` lack cleanup
  (Linux-only paths). Three `addCleanup` lines.
- **T-07 guide validation** — six pin groups but no structural check for
  `guide/index.html`; `check_markdown_links` roots exclude `guide/` and parse only
  Markdown links. Stdlib `HTMLParser` well-formedness + anchor-resolution gate. S/LOW/HIGH.
- **P-01 suite sharding** — 65% of 320 s in 3 modules; every CI cell pays full serial
  cost; `check_unit_test_modules` already accepts module lists → shard matrix axis.
  M/MED/HIGH.
- **P-02 repo-build overhead** — `test_cobbler_agents_leases._init_repo` = 5 git
  processes × 43 sites (87 s); same shape in `test_worker_cli_lifecycle` (39 s). Template
  repo in `setUpClass` + `copytree` per test. M/MED/HIGH.
- **P-03 CI workflow** — the 26-entry `paths:` list duplicated verbatim under
  `pull_request` and `push` (drift hazard; YAML anchor). Gate dedup/caching verified
  already sound.

### Docs & migrations

- **DOC-01 stale gate literals** — `.ai-docs/context-index.md:138,144` +
  `gotchas.md:59` pin `--version 2.10.0`, which fails on a clean tree (three mismatches);
  README carries 2.17.1. Root cause is the hand-typed version (fixed by plan 003's
  default). → plan 003.
- **DOC-02 grammar drift siblings** — `SKILL.md:213` lacks `[--write] [--include PATH]`
  in the copy-ready line (all five other surfaces have it); review-form rows omit profile
  flags on two surfaces; only the alias file's grammar is pinned
  (`consistency_policy.py:1141`), leaving 5/6 surfaces unguarded. S/LOW/HIGH.
- **DOC-03 undocumented grammar** — `--` separator (the escape for tasks starting with
  the word "review", implemented at `run_fugu.sh:78-88`) and repeatable `--include`
  appear on zero doc surfaces; scope is `[scope...]` in the script but `<scope>` in all
  docs. Adopt the script's own usage string as canonical. S/LOW/HIGH.
- **DOC-04 context-index staleness** — omits 17/47 reference files, all four provider
  runners, and ~14 test modules — precisely the v2.12+ additions; it is the designated
  "first map" for agents. M/LOW/HIGH.
- **DOC-05 config example** — `worker.parallel` (first-class validated preference,
  `preferences.py:25,32`) missing from `config.json.example`'s worker block and its
  `_comment` enumeration; documented on seven other surfaces. S/LOW/HIGH.
- **DOC-06 glossary backfill** — README:11-12 promises coined terms are defined in the
  glossary; ~12 post-v2.14 terms are absent (landing profile, Readiness Gate, entropy
  check, capability scan, context packet, fitted answer, harness loop, Wide Research,
  landing authority, Fugu/Manus lane names). The four Cobbler harness-loop terms are
  repeated verbatim in 8 of 11 aliases and defined nowhere. M/LOW/HIGH.
- **DOC-07 guide em dash** — exactly one U+2014 at `guide/index.html:580` vs PRODUCT.md's
  ban; no guard exists; guide is otherwise WCAG-basics clean (verified: landmarks, skip
  link, focus-visible, reduced-motion). S/LOW/HIGH.
- **DOC-08 orphaned ADR** — `references/parallel-unittest-deferral.md` has zero inbound
  links; its four enablement conditions are exactly what suite sharding (P-01) needs.
  Link it from the context index or fold into gotchas. S/LOW/HIGH.
- **DEP-01 floor economics** — deprecation scan clean through 3.15 (import surface listed
  in the audit); nothing blocks a 3.11+ floor bump, which would delete the 535-line
  `toml_compat.py`+test shim (5 importers, 7-file blast radius); the 3.10 floor is stated
  nowhere user-facing and enforced in 2/19 scripts. Floor bump is a user-base decision;
  the doc sentence and guards are plan 003.
- **DEP-02 external CLI pin registry** — Grok version literals scattered across 6 doc
  surfaces and ~10 code sites with one real duplication:
  `sessions.py:1202` defines `GROK_HEADLESS_WORKTREE_RESUME_BROKEN_VERSIONS` while
  `adapters.py:1909` re-derives the same predicate inline — adding a version to one
  misses the other. `references/host-parity.md:51` is the natural registry. Also: no
  documented minimums for git/gh/jq/curl; all six shell scripts verified bash-3.2-safe
  (empirically), a guarantee worth one documented line so nobody breaks it. M/MED/HIGH.

## 5. Vetting corrections

- **D-09 precision:** `CODEX_GOALS_SECTION_HEADINGS` is an empty literal;
  `CODEX_GOALS_SECTION_PHRASES` is *not* (it opens a populated dict). The check is inert
  because the empty HEADINGS makes the scanned text set empty — the conclusion stands,
  one evidence line was imprecise.
- **Driver's own error, kept for the record:** this survey's driver earlier reported the
  local suite as "exit 0" after running `unittest | tail -5` — the observed exit code was
  `tail`'s, not unittest's. The suite actually fails 25+2 on 3.9 hosts (T-01). That false
  green is itself the strongest argument for plan 003 and for preferring
  `verify_repo.py --ci` over ad-hoc pipelines; the claim was corrected in
  `docs/reviews/2026-07-routing-caching-compaction.md` the same day.
- All other spot-checked citations (~30 across the four reports) matched the cited lines
  exactly.

## 6. Direction options (maintainer's call, grounded)

1. **Confidence-calibration ledger (TODO #93/#94).** The signal shipped in v2.10 and its
   first field use produced a concrete calibration datum (a worker reporting
   high-confidence/nothing-unsure over three real defects). A per-(model, effort) ledger
   of reported-vs-found would let review depth follow measured calibration rather than
   fixed policy — the natural completion of the routing table. Effort: M, product
   decision first (as TODO already notes).
2. **Provider-lane platform.** After plan 004 and the grok/devin migrations (D-02), the
   shared prologue (isolated provider home + credential grant + sandbox wrap + wall
   budget + containment) becomes one helper — at which point adding a provider is a thin
   module plus a catalog entry rather than a new dialect. The v2.12–v2.17 cadence
   suggests more providers are coming; this is the difference between linear and constant
   cost per provider. Effort: M after 004.
3. **Compaction stewardship P1–P4** — already proposed with full analysis in
   PR #200 (`docs/reviews/2026-07-routing-caching-compaction.md`); pending maintainer
   selection. Complements this survey's context-management findings.
4. **Parallelves Phase 2 (TODO Live).** Session-schema lane staging validation is the
   next honest increment; v1's advisory `lanes` recording was designed for exactly this
   follow-on. Effort: M, its own planned run.

## 7. What to execute

Executor-ready plans (self-contained, verification-gated) are in `advisor-plans/`:

| Plan | Finding | Effort |
|---|---|---|
| `001-secret-corpus-parity.md` | S-01 + D-04 + the four unredacted prints | S/M |
| `002-preflight-gh-status-parse.md` | C-01 | S |
| `003-trustworthy-verification-signal.md` | T-01 + DX floor guards + gate default + DOC-01 | S |
| `004-extract-fugu-heredoc.md` | D-01 + T-02 (gate first, then extraction) | M/L |
| `005-tar-extract-fail-closed.md` | S-02 | S |

Selected as the top five by leverage (impact ÷ effort, security first) because the user
was away at selection time; everything else above is backlog with fix sketches sufficient
to plan from. Recommended next wave after these: C-03 (bounded subprocess sweep), C-04
(atomic session writes), C-05 (grok containment), D-06 (git helper consolidation), then
the pin-machinery pair D-07/D-08.

## 8. Sources

Four auditor reports (2026-07-27, driver-vetted), measured baselines from this machine,
`git log v2.10.4..HEAD` churn analysis, and the repo's own intent docs (`PRODUCT.md`,
`TODO.md`, `.ai-docs/*`, SKILL.md anti-accretion rule). No source files were modified in
the production of this survey.
