# TODO

Project backlog and deferred tasks.

## Deferred from PR #5

- [x] ~~Update the validation guide to soften mandatory browser testing language to 'strongly recommended'~~ (already done — validation-guide.md uses "strongly recommended")
- [x] ~~Standardize Verify Green, Contract, and Entropy Check across skill files~~ (stale — these referred to code orchestration modules that don't exist in this repo; the Markdown skill files are the implementation)

## Future Ideas

- [x] Add a lightweight process-retro pass to entropy checks.
  `SKILL.md`, `AGENTS.md`, `README.md`, and `references/execution-log-template.md` now tell Elves
  to spend a few minutes on repeated friction during entropy checks and tighten the survival guide,
  templates, learnings, or tool config when a pattern clearly recurs.

## Follow-ups from v1.7.0

- [x] Add a repo consistency checker for the high-value drift classes from `v1.7.0`.
  `scripts/check_repo_consistency.py` now checks version alignment, recovery-order wording,
  `PENDING-DOCS` coverage, and the expected durable doc surfaces.

- [x] Add a local installed-skill sync helper for `.claude/` and `.codex/` copies.
  `scripts/sync_installed_skills.py` now checks and mirrors the managed bundle from this checkout
  into `~/.claude/skills/elves/` and `~/.codex/skills/elves/`.

### Multi-model routing for subagents
Different phases of the loop have different cost/quality tradeoffs. Implementation needs the strongest model; validation could run on a cheaper one; review benefits from a fresh perspective (different model = different blind spots). The subagent strategy already creates natural seams for this. Add optional model configuration per phase in the survival guide, e.g. `implement-model: opus`, `validate-model: sonnet`, `review-model: opus`. The user already controls which model runs — this would make it explicit and tunable.

### Secret redaction layer
Elves has "don't commit .env files" and "never git add -A" but no automated scanning of what gets sent to LLM prompts. A pre-prompt filter that strips API keys, tokens, and credentials from context before sending to the model would close a real security gap. This is infrastructure, not process — probably belongs as a separate tool or MCP server rather than in the skill itself. Factory AI calls theirs "Droid Shield."

### Codebase context indexing
The pre-implementation survey (step 5) relies on the agent searching the codebase in real time. For large repos, a pre-computed index of utilities, patterns, conventions, and module boundaries would make the survey faster and more reliable. Could be generated once during planning and updated incrementally per batch. Similar in spirit to Factory AI's "HyperCode" but implemented as a Markdown file the agent reads rather than proprietary tooling.

- [x] Add a regression-specific review cycle for high-risk batches.
  `SKILL.md`, `AGENTS.md`, `README.md`, and `references/review-subagent.md` now describe an
  optional regression-only pass for medium/high blast-radius batches that traces changed shared
  surfaces to their consumers and asks only what existing behavior could break.

### Public API surface snapshot
For projects with APIs (REST, GraphQL, exported library interfaces), capture the API surface at session start: route list, response shapes, exported types and functions. At the end of each batch, diff the snapshot against the current state. Any unintended change to the public API surface is a finding. This complements the test baseline (which catches removed tests) and the regression attestation (which catches shared-surface changes). It catches changes that pass all tests but alter the contract with consumers.

- [x] Make regression preservation an explicit acceptance-criteria rule.
  `SKILL.md`, `AGENTS.md`, `README.md`, and `references/plan-template.md` now require at least one
  acceptance criterion that proves old behavior still works when a batch changes existing surfaces.
