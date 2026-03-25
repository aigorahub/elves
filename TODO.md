# TODO

Project backlog and deferred tasks.

## Deferred from PR #5

- [x] ~~Update the validation guide to soften mandatory browser testing language to 'strongly recommended'~~ (already done — validation-guide.md uses "strongly recommended")
- [x] ~~Standardize Verify Green, Contract, and Entropy Check across skill files~~ (stale — these referred to code orchestration modules that don't exist in this repo; the Markdown skill files are the implementation)

## Future Ideas

### Process self-improvement across sessions
Elves improves the *repo* progressively (principle #6) but doesn't improve *itself*. The survival guide carries forward, but the process doesn't auto-tune. Could the entropy check also evaluate whether the Elves process itself needs adjustment? For example: if review keeps flagging the same category of issue, should the contract template add a check for it? If validation times are growing, should batch sizing shrink? Factory AI calls this "Signals" — a closed-loop system that detects friction and implements fixes to its own process. Worth exploring as a lightweight version: a "process retro" step every N batches that proposes survival guide amendments based on patterns in the execution log.

### Multi-model routing for subagents
Different phases of the loop have different cost/quality tradeoffs. Implementation needs the strongest model; validation could run on a cheaper one; review benefits from a fresh perspective (different model = different blind spots). The subagent strategy already creates natural seams for this. Add optional model configuration per phase in the survival guide, e.g. `implement-model: opus`, `validate-model: sonnet`, `review-model: opus`. The user already controls which model runs — this would make it explicit and tunable.

### Secret redaction layer
Elves has "don't commit .env files" and "never git add -A" but no automated scanning of what gets sent to LLM prompts. A pre-prompt filter that strips API keys, tokens, and credentials from context before sending to the model would close a real security gap. This is infrastructure, not process — probably belongs as a separate tool or MCP server rather than in the skill itself. Factory AI calls theirs "Droid Shield."

### Codebase context indexing
The pre-implementation survey (step 5) relies on the agent searching the codebase in real time. For large repos, a pre-computed index of utilities, patterns, conventions, and module boundaries would make the survey faster and more reliable. Could be generated once during planning and updated incrementally per batch. Similar in spirit to Factory AI's "HyperCode" but implemented as a Markdown file the agent reads rather than proprietary tooling.
