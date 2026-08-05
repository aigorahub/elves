# Worker packet: v2.24 prime-agent harvest (consolidated, standalone)

You are the implementing worker for one trusted full-run on the Elves repository itself.
This packet is sent once and is self-contained; the plan it points to travels in the worktree.

## 1. Intent / why

Ship Elves v2.24.0: five performance mechanisms adapted (with attribution, without vendoring)
from PrimeIntellect-ai/prime-agent — worktree-fingerprint futile-re-drive detection, a learnings
ledger with history/rollback/digest, an observed-usage ledger surfaced into Session Budget /
Elves Report / calibration, worker-death salvage previews, and an opt-in operator-owned
continuity resume watchdog — plus contract-language harvests and release. Full intent, scope,
and locked product decisions: `docs/plans/v2.24-prime-agent-harvest.md` (**read it first; it is
authoritative**).

## 2. Non-obvious rationale (do not rediscover)

- Ideas were adversarially compared against Elves' written refusals; the plan's Out of Scope
  items (steer messaging, quota inference, kernel substrate, recursion depth, daemon tier) are
  **deliberate rejections** — do not port them "while you're in there".
- Fail-closed asymmetries are the design: fingerprint error ⇒ `changed`; unknown usage ⇒ literal
  `unobserved`; watchdog never resumes terminal/unverifiable runs. Reviewers will treat any
  inversion as a blocker (plan Non-Negotiables).
- `learnings.md` must stay freehand-editable markdown; the ledger manages only id-tagged entries
  and must preserve unmanaged content byte-for-byte (Product decision 2).
- The continuity watchdog exists to survive the "machine sleeps" failure mode without making
  Elves a scheduler: the OS owns the timer; Elves ships templates + CLI + doctor checks, default
  off; the consistency pin is revised, not deleted (Product decision 5).
- Batch order B1→B4 exists because both touch the full-run monitor surfaces; B5 documents shipped
  behavior; B6 is deliberately last-but-one and `high` risk.

## 3. Build On targets (extend, don't create)

- `scripts/cobbler_runtime/schema.py` (typed contracts), `storage.py` (atomic private storage),
  `sessions.py:238,472` (`UsageRecord`, `parse_usage_payload`), `host_profiles.py` (per-host
  transport registry), `behavior_policy.py` (wake enums), `context.py` (redaction corpus),
  `confidence_sidecar.py` (flock + caps + additive JSONL idiom to mirror), `full_run.py` /
  `full_run_monitor.py` (labor-completeness + wake paths), `implement.py` (legacy bounded),
  `native_worker.py` (follow logs), `fugu.py` (existing salvage markers), `install_doctor.py`,
  `cobbler_agents.py` (CLI hub — append-only verb additions).
- Templates/contracts: `references/learnings-template.md`, `survival-guide-template.md` (§Session
  Budget, line ~137), `e2e-chat-to-land.md` (§Labor completeness; re-drive budget at lines
  ~101/144/185), `review-subagent.md`, `operations-guide.md`, `glossary.md`, consistency corpus
  via `check_repo_consistency.py` / `consistency_policy.py`.
- Upstream design references (consult-only): re-clone `https://github.com/PrimeIntellect-ai/prime-agent`
  shallow to a scratch dir and pin/verify SHA `c98941a2a5cf40faecf9b4648ac3c304abf48fd3`; the
  plan's Notes list exact file:line anchors per mechanism. Reread, understand, **reimplement** —
  never copy code or prompts into this repo.

## 4. Owned surfaces (you may edit)

- New: `scripts/cobbler_runtime/worktree_fingerprint.py`, `scripts/cobbler_runtime/learnings_ledger.py`,
  `scripts/resume_watchdog.py`, new tests under `tests/`.
- Existing, within plan scope: the Build On modules above where integration requires it;
  `references/*.md` and `guide/` surfaces the plan names; `SKILL.md` / `AGENTS.md` / `README.md`
  bounded edits with consistency pins in the same commit; `CHANGELOG.md`; version strings per
  `release_checklist.py`; `.elves-session.json` acceptance evidence for your batches.

## 5. Forbidden surfaces

- Run memory beyond your acceptance evidence: the survival guide, this packet, and the execution
  log are host-owned (append batch entries to the execution log only as the contract allows).
- `.git` internals, protected refs, tags, merges, PR operations, remotes config, other worktrees
  (`elves-audit-follow-ups`, `elves-parallelves`), `main`, credentials, `~/.config/elves`,
  anything outside this worktree. Never `git reset --hard` / force-push / rebase shared branches.
- No new runtime dependencies (stdlib only). No files copied from the prime-agent clone.

## 6. Acceptance evidence (what "done" means)

- Every `B#-A#` row in the plan met with recorded evidence in `.elves-session.json`
  (`acceptance: [{id, criterion, met, evidence}]`) and M-A1–M-A6 reconciled at terminal.
- Gates: `python3 scripts/verify_repo.py --ci` green at every batch Close;
  `python3 scripts/check_repo_consistency.py` green after docs batches;
  `verify_repo.py --final-readiness` + `elves_landing_check.py` clean at the attested tip.
- Commit grammar: `[feat/v2.24-prime-agent-harvest · Batch N/8 · Contract|Implement|Validate|Review|Close] <concrete outcome>`;
  ≥1 pushed non-Close progress slice per batch (first due at first failing test or surface
  change); exactly one acceptance-backed Close per batch carrying a `Confidence:` trailer
  (honest `unsure_about` items; empty list is a positive assertion).

## 7. Failure modes / pitfalls

- **Doc-drift tax:** every normative sentence restated on another surface needs its consistency
  pin in the same commit, or `check_repo_consistency.py` fails late and expensively.
- Tests are hermetic by construction here: children run with fd-0 devnull + explicit timeouts;
  never read suite verdicts through a pipe; timing-sensitive tests need the existing hardened
  patterns (generous floors, event-driven waits) or they flake in CI's 4 cells.
- `verify_repo.py --ci` compiles heredoc bodies too — keep any embedded scripts lint-clean.
- Public-API snapshot: additive CLI verbs may trip the snapshot test; intentional additions go
  through `api-break-approvals.json`, never by weakening the test.
- macOS vs Linux: watchdog templates must be generated + dry-run-testable without root; mock OS
  interaction; nothing installs by default.
- Progress ledger: maintain `.elves/runtime/worker-progress-<batch>.md` from first orientation.

## 8. HEAD / run docs / identity / output format

- **START_TIP (collision tripwire):** `5b374fdf8cdfe53f11b724fb6c58f7c858210484`. Unexplained
  tip movement = hard stop.
- **Worktree:** `/Users/ruthbrown-ennis/research/dev/elves-v2-24-prime-agent-harvest`;
  **branch:** `feat/v2.24-prime-agent-harvest` (your only push target; remote `origin` =
  `RBrownHOPE/elves` — upstream push is denied and is not yours to attempt).
- **Run docs:** plan `docs/plans/v2.24-prime-agent-harvest.md`; survival guide
  `docs/elves/v2.24-prime-agent-harvest-survival.md`; execution log
  `docs/elves/execution-log-v2.24-prime-agent-harvest.md`; session `.elves-session.json`;
  shared `docs/elves/learnings.md`.
- **Output:** commit/push progress slices as above; final completion report per the full-run
  event contract (`references/schema-and-acceptance.md`) — completeness, per-batch acceptance
  ids with evidence, files touched, gates run, honest diff summary, confidence with
  `unsure_about`. Silence is not success; emit heartbeats.
