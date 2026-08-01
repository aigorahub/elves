# Plan: v2.23 remaining open issues + Grok first-class host parity

## Mission

Close every remaining real open GitHub issue on `aigorahub/elves` (88, 92, 93, 94, 95, 96, 97, 98, 101) and close e2e/sync-test residue issues as non-product noise. Make **Grok Build a first-class host peer of Claude Code and Codex**: native `~/.grok/skills/elves` install, one-line install next to Claude/Codex, host-honest docs, and completed prewalk launch-path plumbing. Land a reviewed PR (and authorized merge) so the repo has **zero open product issues**.

## Scope

### In Scope

- **#237** (open PR): land Fugu calling guide + timeout salvage before or as B0 of this run if still open at staging.
- **#88** Native Grok skill install target (`~/.grok/skills/elves`) via `sync_installed_skills.py --target grok`, install_doctor/smoke, docs that treat Grok as a supported main driver (not “discovery only”).
- **#101** One-line install quick starts for **Claude Code, Codex, and Grok Build** (host-honest commands only; temporary-clone/sync remains fallback). Update README + guide first.
- **#95** Grok prewalk qualification launch path with the full continuity contract (see B2), not a thin resume flag check.
- **#96** Resume-prepare: **refuse** if the existing event log contains `blocked` or `run_complete`; no alternate “fully specified rebuild” path.
- **#92** Decompose `full_run.py`: extract monitor/await after characterization baseline; intentional #96 fix is separate and confined to resume-prepare.
- **#94** Native-lane structured confidence sidecar under `.elves/runtime/confidence/`.
- **#93** Confidence-calibration tracking with a locked bounded schema (below).
- **#97** Widen public persona wording guard with zero false positives on the current corpus.
- **#98** Enumerate host-native UI / third-party bypass surfaces; update redaction docs to honest claim boundaries.
- Close all remaining open **e2e/sync-test** GitHub issues (IDs recorded at staging) as residue **after merge**.
- Version bump + CHANGELOG (v2.23.0) + dual review before merge.

### Out of Scope

- New optional providers beyond Claude/Codex/Grok as main drivers.
- Full MCP/OS-level redaction interception (investigation + honesty only for #98).
- Rewriting Parallelves topology.
- Porting the runtime to Rust.
- Opening `launch_ready` from qualification evidence alone.

## Product decisions (locked for this run)

1. **Grok is a first-class main driver** for install, docs, doctor, and prewalk plumbing. Remove wording that calls native Grok install “optional discovery only” or “unsupported as orchestrator”.
2. **#93 schema (versioned, bounded JSONL):** each record has run identity, timestamp, host/provider, model, effort, normalized confidence or explicit `missing`, outcome category from a fixed enum (e.g. `landed_clean`, `terminal_blocker_product`, `terminal_blocker_infra`, `abandoned`), no raw `unsure_about` free text. Atomic/locked append, malformed-tail skip, file-size/record cap. Calibration-relevant outcomes exclude pure infra/credential landing blocks from “overconfidence” scoring when category is `terminal_blocker_infra`. Never blocks landing; never grants authority. Path: gitignored `.elves/runtime/confidence-calibration.jsonl` (or equivalent under `.elves/runtime/`).
3. **#94 sidecar:** `.elves/runtime/confidence/<batch-or-run>.json` written by native worker close path / host reconcile when trailers exist; read by confidence-guided review table builders.
4. **#95 live canary auth:** supported canary precondition is explicit **`XAI_API_KEY` (or legacy named key) + installed `grok` binary**. Shared-file OAuth is **unavailable** for this canary path and must be recorded as such (not treated as authenticated). Live canary at effort `high` when precondition holds; otherwise honest unavailable evidence. Offline fakes always required. Qualification never opens `launch_ready` alone.
5. **#101 one-liners:** host-honest wrappers calling `sync_installed_skills.py`. Published Grok quick start uses **explicit `--target grok`**. Document `--target all` as **update-only for already-installed roots** unless host-presence detection is implemented and tested; prefer not to invent fragile “Grok present” heuristics unless a reliable check exists.
6. **#96:** fail-closed refuse only (no rebuild of terminal sessions).
7. **Issue close order:** prepare close comments during the run; **close product and residue issues only after authorized merge**, each with merged PR URL and merge SHA. Enumerate residue issue numbers at staging.
8. **e2e issues:** close after merge with residue disposition; never implement.

## Batches

### B0 · Land open Fugu guide PR (if still open)

- [ ] [B0-A1] PR #237 merged to main (or tip includes Fugu salvage + calling guide) with green CI. Verify live PR status at staging.
- [ ] [B0-A2] Working branch for this plan is based on that tip.
- [ ] [B0-A3] At staging, record exact open e2e/sync-test issue numbers with residue justification (for B6 close-after-merge).

### B1 · Grok first-class install + three-host one-liners (#88, #101)

- [ ] [B1-A1] `sync_installed_skills.py` supports `--target grok` writing `~/.grok/skills/elves` with the same managed bundle as Claude/Codex (no Claude alias install under Grok).
- [ ] [B1-A2] `--check`/`--apply` include Grok; tests cover grok target create/check/drift. `--target all` behavior documented as update-only for existing roots; Grok one-liner uses explicit `--target grok` so first install always works.
- [ ] [B1-A3] `install_doctor` validates Grok skill root when installed; smoke forbids archives; smoke that Grok skill tree is discoverable under `~/.grok/skills/elves` layout.
- [ ] [B1-A4] README + guide show **three** copy-paste one-liners (Claude, Codex, Grok) first; temporary-clone fallback retained; update/uninstall documented.
- [ ] [B1-A5] First-class Grok wording on **all** durable public surfaces that currently contradict it, including at least: SKILL.md, AGENTS.md, README.md, guide/index.html, references/host-parity.md, references/prewalk.md, references/model-onboarding.md, docs/cobbler.md, and active-skill-root / install_doctor examples. Consistency pins reject obsolete claims such as “Grok Build as main driver is unsupported”, “refuse to stage from Grok”, “managed targets remain Claude and Codex only”, and native Grok install described only as optional discovery.

### B2 · Grok prewalk launch path (#95)

- [ ] [B2-A1] Launch path materializes bounded prompt-file input and validates non-yolo auth/permission profile end-to-end in code (API-key canary precondition per product decision 4).
- [ ] [B2-A2] Offline automated proof of full continuity contract:
  1. one prompt-file delivery on the guide turn;
  2. only `Continue.` on execution resume;
  3. identical session and worktree;
  4. explicit guide→execution model/effort change;
  5. one logical stream and guide-only fact retention;
  6. no packet replay or post-edit cold fallback;
  7. failed or unavailable qualification never activates the qualified path;
  8. artifacts bind to installed version/build.
- [ ] [B2-A3] Live canary at effort `high` when `XAI_API_KEY` + `grok` are present; otherwise honest unavailable reason. Qualification evidence alone never opens single-phase `launch_ready`.

### B3 · full_run: characterize → extract → #96 refuse (#92, #96)

Order is mandatory:

- [ ] [B3-A1] Characterization coverage for monitor/await (and related follow/streaming helpers) **before any behavior edit or move** of those surfaces.
- [ ] [B3-A2] Extract monitor/await (and safe follow/streaming helpers) from `full_run.py` into a dedicated module with **no intentional behavior change**; public CLI entrypoints unchanged; existing + characterization tests green.
- [ ] [B3-A3] #96 confined to resume-prepare (outside extracted monitor/await): before writing or replacing any state, packet, report, transcript, or event, resume-prepare validates the existing event log and **refuses** if it contains `blocked` or `run_complete`. Separate regressions for both terminal types: state/report/events remain byte-for-byte unchanged; no new `run_started`.

### B4 · Confidence sidecar + calibration (#94, #93)

- [ ] [B4-A1] Native-lane JSON confidence sidecar written and consumed for the confidence-guided review table (Claude/Codex path).
- [ ] [B4-A2] Cross-run calibration store implements product decision 2 (schema, caps, outcome categories, atomic append).
- [ ] [B4-A3] Elves Report can surface a short trend section when data exists. Docs state confidence/calibration are triage only, never landing authority.

### B5 · Public wording + redaction honesty (#97, #98)

- [ ] [B5-A1] Public wording guard covers known miss shapes (`Fable-powered`, `runs on Fable`, bare persona claims for Claude/Anthropic where appropriate) with zero false positives on the existing consistency corpus.
- [ ] [B5-A2] Redaction/docs enumerate host-native UI and third-party bypass surfaces and state honest non-coverage; no claim of OS/MCP interception that does not exist.

### B6 · Release, merge, then issue board empty

- [ ] [B6-A1] CHANGELOG + version bump (v2.23.0) + dual review (Fugu + independent agent) + landable PR with green CI.
- [ ] [B6-A2] Authorized merge to main (user authorized this finite run to merge when ready).
- [ ] [B6-A3] **After merge only:** close issues 88, 92–98, 101 each with merged PR URL + merge SHA and batch evidence.
- [ ] [B6-A4] **After merge only:** close every e2e/sync-test residue ID recorded at staging with residue disposition + merge SHA (or “closed as residue; no code change” if merge was unrelated).
- [ ] [B6-A5] Worktree teardown; product open-issue count is zero.

## Master Acceptance

- [ ] [M-A1] No open product GitHub issues remain on `aigorahub/elves` after authorized merge and close pass.
- [ ] [M-A2] Grok has parity install path with Claude and Codex: `--target grok`, one-liner, doctor, first-class main-driver wording on all surfaces listed in B1-A5.
- [ ] [M-A3] #92 extraction ships without intentional behavior change beyond #96; full_run-related tests pass.
- [ ] [M-A4] #96 is fail-closed refuse for terminal event logs, with regressions for `blocked` and `run_complete`.
- [ ] [M-A5] Confidence sidecar + calibration match locked schemas; never grant landing authority.
- [ ] [M-A6] #97 and #98 land with consistency green and honest redaction docs.
- [ ] [M-A7] Reviewed PR merged to main under this run’s user authorization.
- [ ] [M-A8] #95 ships offline tests proving bounded prompt-file delivery, exact create→resume continuity (full contract in B2-A2), fail-closed launch gating, and no packet replay; live canary attempted under API-key precondition or honest unavailable reason recorded; qualification evidence alone never opens single-phase `launch_ready`.

## Risk

- **standard–high** for #92 (large move) and #95 (live Grok dependency).
- **standard** for install/docs (#88/#101) and confidence (#93/#94).
- **low** for #96, #97, #98 once scoped as above.

## Caution

- Do not invent Codex/Grok plugin CLI syntax.
- Do not open `launch_ready` from qualification evidence alone.
- Characterization tests before moving `full_run` monitor/await code; #96 is a separate resume-prepare change after extraction or clearly isolated commits.
- Keep secret redaction fail-closed; docs-only honesty for bypass surfaces.
- Do not close GitHub issues before merge.

## Affected surfaces

- `scripts/sync_installed_skills.py`, `install_doctor.py`, `installed_bundle_smoke.py`, install tests
- `scripts/cobbler_runtime/full_run.py` + new monitor/await module
- `scripts/cobbler_runtime/prewalk.py`, `native_worker.py`, `worker_routing.py`, `host_profiles.py` as needed
- `scripts/consistency_policy.py` (#97 + Grok wording pins)
- README, guide/index.html, SKILL.md, AGENTS.md, references/host-parity.md, prewalk.md, model-onboarding.md, docs/cobbler.md, redaction docs
- CHANGELOG, version fields
- GitHub issue close comments (post-merge)

## Focused tests

- Install target grok + three-host one-liner docs consistency pins
- full_run resume-prepare terminal session refuse regressions
- full_run monitor/await after extraction
- prewalk Grok full continuity with fakes
- confidence sidecar + calibration schema bounds
- wording guard corpus (zero false positives)
- `check_repo_consistency.py` green

## Review focus

- Host honesty (Claude/Codex/Grok install claims across all durable docs)
- No behavior change in full_run extraction beyond isolated #96 refuse
- Confidence never becomes authority
- Issue board empty of product work only after merge

## Dependencies

- B0 before B1 if #237 still open.
- B1 before B2.
- B3 order: characterize → extract → #96 refuse.
- B6 last; issue closes after merge only.

## Run control preferences (for staging)

- **Mode:** finite
- **Work driver:** host-native or trusted full-run (prefer available native worker)
- **Merge:** authorized after dual review + green CI + readiness (user requested zero open issues when done)
- **Fugu:** plan reviewed 2026-08-01 (`/tmp/fugu-plan-v223.log`); findings incorporated in this revision
- **Close issues:** after merge only

## Fugu plan review (completed)

Source: Ultra review of `PLAN-v2.23-remaining-open-issues.md` (log `/tmp/fugu-plan-v223.log`).

| Severity | Finding | Disposition in this revision |
|---|---|---|
| P1 | No Master Acceptance for #95 | Added M-A8 |
| P1 | B2 missing full continuity contract | Expanded B2-A2 |
| P1 | #96 “or fully specified” vs fail-closed | Locked refuse-only B3-A3 + M-A4 |
| P1 | Close issues before merge | B6 close-after-merge only; B0 enumerates residue IDs |
| P2 | `--target all` skips missing Grok root | Explicit `--target grok` one-liner; all=update-only |
| P2 | Durable docs still deny Grok | B1-A5 expands surface list + consistency pins |
| P2 | #93 schema underspecified | Product decision 2 locks schema |
| P3 | B3 characterization after #96 | B3 order: characterize → extract → #96 |

No P0 findings.
