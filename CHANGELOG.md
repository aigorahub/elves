# Changelog

All notable changes to the Elves skill are documented here.

## [1.3.2] - 2026-03-25

### Remaining review suggestions: operational completeness

#### New sections
- **Merge Conflicts:** What to do when `git push` fails due to a diverged remote (fetch and merge, never rebase, resolve or Hard Stop). Added to both SKILL.md and AGENTS.md.

#### Expanded sections
- **Scout Mode:** Added prioritization guidance (risk-reducing first, then quality, then leave ambiguous items), validation gate requirement, commit format (`[branch · Scout]`), and when-to-stop rules. Applied to both SKILL.md and AGENTS.md.
- **Entropy Check:** Added cadence scaling guidance (check after batch 2-3 for short plans, every 3 for long, stretch to 4-5 if reviews are clean).
- **AGENTS.md Planning phase:** Added full planning section with interactive and autonomous modes, architecture survey, and references to plan-template.md and kickoff-prompt-template.md. Was the biggest content gap between the two files.

#### Precision improvements
- **Contract step:** "Build on" section explicitly marked as required (was only shown in the example).
- **Compaction Recovery:** Added note about restoring files from git history if compaction happens during Final Completion cleanup.
- **AGENTS.md:** Added `python3 (no jq)` explanation, compaction recovery cleanup note, config.json reference already added in v1.3.1.

## [1.3.1] - 2026-03-25

### Review fixes: structural consistency and operational gaps

#### Core Loop restructuring
- **Wired the Judge into the Core Loop as step 8.** The legality check was described in a standalone section but had no step number — an agent following steps literally would never run it. Now step 8 sits between Review (7) and Document (9).
- **Renumbered all Core Loop steps** 1-15. Eliminated the "11a" hack — PR Loop is now step 13.
- **Fixed heading levels.** Batch Decomposition and Time Allocation were peers of Core Loop when they should have been children.

#### Internal consistency
- **Unified Orient and Compaction Recovery reading orders.** Added `.elves-session.json` to Orient step.
- **Clarified proof scope in Completion Contract.** "Relevant tests" → "Touched-surface tests" with note that broad regression runs at entropy checks and Readiness Gate.
- **Added legality check to Completion Contract** (now 14 items).

#### Operational gaps
- **Added `gh` API failure/retry guidance** to step 13 (PR Loop).
- **Added references** to `review-subagent.md`, `plan-template.md`, `kickoff-prompt-template.md`.

#### Cross-file sync
- AGENTS.md: renumbered steps 1-15, added step 8 (Judge), added `.elves-session.json` to Orient, added legality check to Completion Contract, added `gh` API failure guidance, added Persistent Preferences section.
- README: changed "v0" to "still early", updated file structure diagram, removed placeholder URL.
- TODO.md: marked stale PR #5 items as done.

## [1.3.0] - 2026-03-25

### PR Loop, Readiness Gate, Constitution & Legality Check

#### PR timing and review cadence
- **"Don't wait to open the PR"** — explicit instruction to open the PR after the first pushed commit, not delay until the branch is nearly done. Keep using the same PR throughout the run.
- **PR Loop (step 13):** After every push (including mid-implementation), poll PR comments, inline reviews, and check status before starting new work. Lightweight scan that defers to step 7 for full review cycles.

#### Constitution and the legality check
- **Three quality layers** made explicit: correctness (validation gates), plan compliance (review step), legality (the judge). Each asks a different question.
- **The gaming problem:** Explains why agent-authored tests have a ceiling — agents can satisfy every deterministic test while missing the point. The constitution breaks through by providing success criteria the agent didn't author.
- **The constitution:** `docs/constitution.md` or `CONSTITUTION.md` contains deal-breaker behaviors (flows with mermaid diagrams, business logic, invariants). Read during every Orient step and compaction recovery.
- **The judge:** Read-only legality check producing PASS/WARN/FAIL/UNCHANGED verdicts per intention. Runs after each batch passes validation and review. FAIL blocks the batch.
- **The flywheel:** Constitution grows via planning (propose new intentions), mistakes (regressions become safeguards), and incidents. Agent drafts, human owns.

#### Readiness gate
- **Readiness Gate:** 7-point branch-level checklist before declaring review-ready (local proof on current tip, preview proof, artifact inspection, PR comments polled, legality check clean, git status clean, execution log current). Distinct from the per-batch Completion Contract.

#### Proof scope
- **Touched-surface vs broad regression proof.** Default to touched-surface per batch; run broad regression at entropy check intervals and before readiness.
- **Re-earn proof after each push** — don't inherit proof from prior commits after review fixes.
- **Artifact inspection** — inspect actual downloaded output for export/download changes.

#### Triage and operational specificity
- **Four-category triage** unified across step 7, step 13, and judge: fix now, defer, intentional design, false positive. Replaces the previous three-category scheme.
- **Subagent capacity:** If pool is full, reuse/close idle agents or do work directly. Never skip review.
- **Process warnings:** Stop and clean up if session/process-count warnings appear.

#### Housekeeping
- Updated AGENTS.md (Codex variant) with all v1.3.0 changes.
- Updated CHANGELOG.md and README.md.

## [1.2.0] - 2026-03-25

### Harness Design: Full-Lifecycle Philosophy, Time Allocation, and Industry Convergence

#### Code Quality Philosophy across the full lifecycle
- **Philosophy now informs planning, contracts, and implementation — not just review.** Previously the 9 principles were enforced at review time. Now they're threaded through the entire lifecycle:
  - **Planning:** New architecture survey step before batch decomposition. Batch ordering is architecture-aware — shared utilities go in early batches, pattern-setting batches come before pattern-following ones.
  - **Contract (step 4):** New **Build on** section identifies specific existing patterns, utilities, and conventions the batch should extend. Gives the implementing agent a concrete target and the reviewer something specific to verify against.
  - **Implementation (step 5):** New **pre-implementation survey** — search for relevant utilities, patterns, and conventions before writing code. Logged in the execution log so the reviewer can check whether the agent used what it found.
  - **Review (step 7):** Reviewer now checks implementation against the Build on section and pre-implementation survey. Creating a duplicate of something identified in the survey is a blocking finding.

#### Time allocation
- Added **Time Allocation** guidance to the core loop. Default is equal thirds (implement, validate, review); configurable in survival guide. Agents naturally rush validation and review — this makes the expected balance explicit and trackable.

#### Entropy management
- Added **Entropy Check** step (step 12): every 3 batches, the agent performs a cross-batch quality scan to catch accumulated drift — duplicated utilities, naming inconsistencies, diverging patterns — that individual batch reviews miss. Cadence is configurable via survival guide.

#### New principle and architecture support
- Added **Principle #9: Favor boring technology.** Agents should prefer well-known, stable, composable libraries over novel ones. "Boring" technology has stable APIs and broad training-data representation, making agents more reliable. Sometimes reimplementing a small utility is cheaper than pulling in an opaque dependency.
- Added **Architectural Boundaries** section to survival guide template: optional section for defining layered architecture, dependency direction, module ownership, and enforcement mechanisms (structural tests, lint rules). Helps agents respect boundaries in larger codebases.

#### Industry convergence
- Expanded **Prior art and convergence** section in README. Elves, Anthropic, OpenAI, and Factory AI independently converged on the same core patterns for autonomous agent orchestration — plan approval before execution, persistent state across context boundaries, iterative self-correction, quality enforcement, and codebase conditioning for agent performance. Added [Factory AI Missions](https://factory.ai/news/missions) and their [Agent Readiness framework](https://factory.ai/news/agent-readiness) as a third independent convergence point alongside Anthropic and OpenAI.

#### Housekeeping
- Core loop steps renumbered: Continue or Stop is now step 13 (was 12).
- Added future ideas to TODO.md: process self-improvement across sessions, multi-model routing, secret redaction, codebase context indexing.

## [1.1.0] - 2026-03-24

### Harness Design Improvements

- Added **Verify Green** step (step 2): agents confirm the project is in a working state before starting each batch
- Added **Contract** step (step 4): agents define testable acceptance criteria before writing code (generator/evaluator pattern)
- Two-stage validation now explicit in core loop: local gates then preview deployment
- Structured session data (`.elves-session.json`) tracks `review_comments` dispositions (`fixed`, `dismissed`, `deferred`) for compaction recovery
- Strengthened review loop with commit-message-as-communication-channel guidance
- Consistent philosophy principles (1-8) across SKILL.md, AGENTS.md, and review-subagent.md
- Cross-references between AGENTS.md and reference docs (validation-guide.md, verification-patterns.md)
- Browser verification language clarified: "strongly recommended" (not blocking for non-UI projects)
- Generalized browser automation references to "Playwright, Cypress, or similar" (not Playwright MCP-specific)
- Dependency installation examples added to SKILL.md Verify Green step
- Batch sizing examples clarified as overrides of the stated default
- Configurable thresholds (5-modification, 3-cycle) noted as overridable via survival guide

## [1.0.0] - 2026-03-21

### Core Skill

- Interactive planning phase: the agent and user collaborate on scope, batches, and configuration before any code is written
- Multi-batch execution with user-defined sprint sizing (default: 4 developers x 2-week sprint)
- Core loop: Orient, Tag, Implement, Validate, Review, Document, Update, Push, Re-read, Continue
- Three-document compaction survival system (Plan, Survival Guide, Execution Log)
- Subagent delegation for long runs (Claude Code): implementer, validator, reviewer, scout
- Scout mode for bonus improvements after planned batches are done
- Time-aware pacing with session budgets
- Rollback safety with `elves/pre-batch-N` git tags
- Structured session data in `.elves-session.json`
- Persistent preferences via `config.json`
- Skill memory: execution logs improve over time

### Safety

- Forbidden commands: `git reset --hard`, `git checkout .`, `git clean -fd`, `git push --force`, `git rebase` on shared branches
- Test integrity: never modify a test to make it pass. Fix the code, not the test
- Non-interactive operation with `CI=true` and comprehensive env var hardening
- Mid-run check-in protocol: answer concisely, keep going
- PreToolUse hook example for deterministic enforcement of forbidden commands
- Survey and popup suppression guidance for Claude Code, Codex, and Cursor

### Validation

- Two-stage validation: local gates then preview deployment
- Auto-discovery for Node.js, Python, Go, Rust, and Makefile projects
- Zero accumulated debt philosophy: every batch must be production-ready
- Verification patterns: headless browser drivers, video recording, smoke testing, state assertions, custom scripts

### Review

- Built-in review subagent reads PR comments, bot reviews, and CI status (zero config)
- Adversarial review pattern: fresh-eyes subagent with no implementation context
- Custom review API support (opt-in)
- Additional checks: smoke tests, visual review, doc review, custom scripts
- Finding triage: genuine issues, intentional design choices, false positives

### Documentation

- README with origin story, Ralph Loop, Human Sandwich, and honest v0 framing
- "What to expect" section with real ROI numbers (6-9 months of work in 3-4 hours of human time)
- "Riding along" guidance: say "do not stop" in every message
- "What can go wrong" failure modes table with mitigations
- Preventing sleep/shutdown guide (caffeinate, systemd-inhibit, tmux/screen)
- Monitoring with GitKraken and Slack notifications
- Claude Code hooks: SessionStart for auto-loading context, PreToolUse for forbidden commands
- Installation guide: global and per-project for Claude Code, Codex, Claude.ai
- "Making it your own" customization guidance
- Daily briefing and Friday planning cadence

### Templates

- Survival guide template with non-negotiables, tool config, and safe rollback procedures
- Execution log template with timing breakdown and Ralph Loop framing
- Plan template with worked example (auth system refactor) and Human Sandwich framing
- Kickoff prompt template (minimal and full versions) with daily briefing guidance
- Tool configuration examples for Node, Python, Go, Rust, monorepos, and custom APIs

### Scripts

- `preflight.sh`: comprehensive pre-run checklist (git, auth, project detection, sleep prevention, gate dry-runs, notification checks, non-interactive env guidance, branch staleness)
- `notify.sh`: Slack webhook, custom command, or PR comment notification helper. Returns proper exit codes in --test mode for preflight validation

### Platform Support

- Claude Code (SKILL.md): full feature set with subagents and hooks
- Codex (AGENTS.md): direct execution, concise format
- Claude.ai: zip upload
- Any Agent Skills compatible platform (open standard)
- Passes `agentskills validate`
