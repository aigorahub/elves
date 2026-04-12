# TODO

Project backlog and deferred tasks.

## Deferred from PR #5

- [x] ~~Update the validation guide to soften mandatory browser testing language to 'strongly recommended'~~ (already done — validation-guide.md uses "strongly recommended")
- [x] ~~Standardize Verify Green, Contract, and Entropy Check across skill files~~ (stale — these referred to code orchestration modules that don't exist in this repo; the Markdown skill files are the implementation)

## Future Ideas

### Process self-improvement across sessions
`v1.7.0` added learnings and docs-in-the-loop upkeep, so Elves now preserves lessons better than it did originally. But the process still doesn't truly auto-tune itself. Could the entropy check also evaluate whether the Elves process itself needs adjustment? For example: if review keeps flagging the same category of issue, should the contract template add a check for it? If validation times are growing, should batch sizing shrink? Factory AI calls this "Signals" — a closed-loop system that detects friction and implements fixes to its own process. Worth exploring as a lightweight version: a "process retro" step every N batches that proposes survival guide amendments based on patterns in the execution log.

## Follow-ups from v1.7.0

### Repo consistency checker
This release fixed multiple cases of documentation drift across `SKILL.md`, `AGENTS.md`,
`.elves-session.json`, and README. A tiny consistency script or lint-like checker could catch those
before PR bots do.

### Local installed skill sync
The `v1.7.0` PR intentionally updates only the canonical repo skill surfaces. It may still be worth
adding a release helper or checklist for syncing installed local copies under `.claude/` and
`.codex/` after a repo release lands.

### Multi-model routing for subagents
Different phases of the loop have different cost/quality tradeoffs. Implementation needs the strongest model; validation could run on a cheaper one; review benefits from a fresh perspective (different model = different blind spots). The subagent strategy already creates natural seams for this. Add optional model configuration per phase in the survival guide, e.g. `implement-model: opus`, `validate-model: sonnet`, `review-model: opus`. The user already controls which model runs — this would make it explicit and tunable.

### Secret redaction layer
Elves has "don't commit .env files" and "never git add -A" but no automated scanning of what gets sent to LLM prompts. A pre-prompt filter that strips API keys, tokens, and credentials from context before sending to the model would close a real security gap. This is infrastructure, not process — probably belongs as a separate tool or MCP server rather than in the skill itself. Factory AI calls theirs "Droid Shield."

### Codebase context indexing
The pre-implementation survey (step 5) relies on the agent searching the codebase in real time. For large repos, a pre-computed index of utilities, patterns, conventions, and module boundaries would make the survey faster and more reliable. Could be generated once during planning and updated incrementally per batch. Similar in spirit to Factory AI's "HyperCode" but implemented as a Markdown file the agent reads rather than proprietary tooling.

### Regression-specific review cycle for high-risk batches
For batches that touch shared surfaces or are flagged as high-risk in the contract's blast radius section, add an optional regression-focused review pass after the standard review. This is a lightweight variant of the adversarial review pattern, focused only on "what could this break?" The regression reviewer reads only the cumulative diff and the plan, then traces every changed file to its consumers. It ignores code quality, style, and improvements. It only reports things that could break existing functionality. Most valuable for batches modifying auth, billing, data models, or shared utilities.

### Public API surface snapshot
For projects with APIs (REST, GraphQL, exported library interfaces), capture the API surface at session start: route list, response shapes, exported types and functions. At the end of each batch, diff the snapshot against the current state. Any unintended change to the public API surface is a finding. This complements the test baseline (which catches removed tests) and the regression attestation (which catches shared-surface changes). It catches changes that pass all tests but alter the contract with consumers.

### Regression test as first-class acceptance criterion
For any batch that modifies existing code (not just adds new code), require at least one acceptance criterion that explicitly verifies existing behavior is preserved. For example: "All existing validation tests still pass unchanged" or "GET /api/users still returns the same response shape." This shifts regression thinking into the contract phase (step 4) where it's cheapest to enforce, instead of waiting for the review or attestation to catch it.
