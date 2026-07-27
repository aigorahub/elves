# Model routing, cache reality, and compaction stewardship — deep-dive review

- **Date:** 2026-07-27
- **Base:** v2.17.1 (`9731fc3`)
- **Author:** John, drafted in a Claude Code session (Claude Fable 5 driver) on a shared
  machine; the commit identity reflects that machine's git config. Section 8 carries the
  resume notes for continuing this work from another machine.

## 1. Scope and method

Three questions motivated this review:

1. Is the driver→worker handoff worth the trouble, given that most operators want to start
   with a frontier planner (Fable 5, GPT-5.6 at ultra, Opus 5 at ultracode) and hand off to
   a cheaper worker (a lower effort tier of the same model, or a cross-family model such as
   Grok 4.5)?
2. Does prompt caching reward staying within one model family on the handoff, as intuition
   suggests?
3. Can Elves manage context compaction through the host interface, so long runs keep a
   cleaner window?

Every claim below carries one of three evidence tags:

- **[observed]** — verified directly in this repository or session, with the source named.
- **[docs]** — from Claude Code / Claude API documentation research performed this session.
  Version-dependent items are flagged; re-verify against the installed CLI before making any
  of them normative.
- **[analysis]** — reasoning from the tagged evidence.

## 2. Findings in brief

1. **Handoffs are worth it for the overnight use case, but token savings are the secondary
   reason.** The primary value is context isolation (the driver survives a multi-batch run
   with a lean window) and fresh-context verification, which measurably outperforms
   self-critique. [analysis over observed evidence]
2. **Caching does not meaningfully reward family-local handoffs in Elves' architecture.**
   Prompt caches are exact-prefix and model-scoped, and Elves handoffs are file-mediated,
   so there is almost no shared prefix to reuse. Family-local delegation is still the right
   default — for capability, tokenizer, qualification, and calibration reasons. The
   existing routing contract already refuses cross-session cache claims. [observed + docs]
3. **Compaction is programmatically triggerable for sessions Elves supervises, but the
   stronger doctrine is "recycle beats summarize."** Fresh per-batch sessions restoring
   from run docs are a lossless form of compaction; steering the host's compactor is the
   backstop. Four small, deterministic upgrades are proposed in section 7. [docs + analysis]

## 3. Are driver→worker handoffs worth the trouble?

The intuition "smart planner hands off to a cheaper worker" is already the shipped default:
the routing table in `references/adaptive-worker-routing.md` maps GPT-5.6 at
`xhigh`/`ultra` → the same model at `medium`, Claude Fable 5 at `max`/`ultra` →
`claude-fable-5` at `low`, Claude Opus 5 at `max`/`ultracode` → `claude-opus-5` at `high`,
and the sole cross-family route is the explicitly opted-in `grok-4.5` at `high`.
[observed: routing table]

What the handoff actually buys, ranked:

1. **Context isolation.** A single session doing plan → implement → review across N
   batches compacts repeatedly, and each compaction is a lossy summary landing exactly when
   late-run quality matters most. With handoffs, each worker opens a fresh window sized to
   one batch, and the driver's window carries only orchestration and review. The handoff is
   Elves' context-management primitive, not just its cost lever. [analysis]
2. **Fresh-context verification.** Anthropic's model guidance states that separate
   fresh-context verifiers tend to outperform self-critique. [docs] Two run episodes in
   this repository's history bear it out: a worker reported `high` confidence with an empty
   `unsure_about` list while its diff contained three real defects (a NaN comparison
   defeating a gate, an unhandled overflow, and recursion-depth exhaustion), all caught by
   a fresh adversarial review lens; and a shared-OAuth defect was found by a fresh review
   following the worker's own uncertainty flag. [observed: run history for v2.10.x and
   v2.11.0 development]
3. **Effort economics.** Output tokens carry roughly five times the input price, and lower
   effort yields fewer, more consolidated tool calls and terser output. Current-generation
   models at `low` effort remain capable implementation workers — the documented rationale
   for the family-local defaults above. On subscription transports this appears as quota
   headroom rather than dollars; the math is the same. [docs + observed]

Costs are real but modest: packet authoring, workers re-reading context (which doubles as
verification), orchestration latency (now parallelizable via Parallelves), and capability
mismatch on hard batches (mitigated by `route-worker` classification, the worker confidence
signal, and re-drives). Handoffs are *not* worth it for short interactive tasks, single
trivial batches, or debugging where the accumulated context is itself the asset. Prewalk
`auto` already skips atomic low-reasoning work; a width-test-style "delegation gate" would
complete that symmetry but is not urgent. [analysis]

## 4. What caching does and does not buy

Mechanics [docs]: prompt caches are exact-prefix matches, scoped per model (and per
organization); writes cost 1.25–2× input price, reads 0.1×. Any byte difference anywhere in
the prefix invalidates everything after it. A cache entry on one model is never readable
from another model.

Two consequences for Elves:

- **File-mediated handoffs share almost no cacheable prefix.** The worker receives a packet
  on disk and a fresh session, not the driver's conversation. The only prefix driver and
  worker sessions share is the host's static prelude (system prompt, tool schemas, project
  memory files). Staying family-local therefore saves roughly one prelude cache write per
  additional model per TTL window — a rounding error against a multi-batch run.
  [docs + analysis]
- **The intuition is true for conversation-inheriting forks, which Elves does not do.** If
  a handoff spliced the driver's transcript into the worker, same-model would be mandatory:
  cross-model gets zero cache reuse by construction, and some models' thinking blocks are
  dropped when replayed to a different model. Elves chose the file-mediated shape, which is
  why routing is free to ignore caching. [docs + analysis]

The existing contract already encodes this honestly: `references/adaptive-worker-routing.md`
§"Cache and authority limits" states that neither host exposes a supported cache object the
driver can export into another process or model, that a session ID is not such an object,
and that cache hits are opportunistic telemetry, never launch or acceptance gates. No change
is needed there. [observed]

What actually justifies family-local delegation [analysis over observed + docs]:

- **Behavioral predictability.** Packets are prompts, and prompt behavior tunes per model
  family; a packet idiom proven on one family transfers within it.
- **Tokenizer consistency.** Current same-family pairs share tokenizers, so token budgets,
  output headroom, and plan sizing transfer; cross-family handoffs change the budget math.
- **Qualification cost.** Native transports are pre-qualified; external providers require
  prewalk-style behavioral evidence before any elevated trust, which is deliberate
  friction.
- **Reviewer calibration.** Knowing how a specific (model, effort) pair under- or
  over-reports uncertainty is per-route knowledge; the confidence-signal episode in
  section 3 is exactly such a calibration datum.

## 5. Compaction control surfaces (Claude Code)

Findings from documentation research this session. All rows are **[docs]** unless marked;
re-verify version-dependent rows against the installed CLI before relying on them.

| Surface | Finding |
|---|---|
| `/compact` in headless mode | Works as prompt input (`claude -p --resume <session-id> "/compact"`); reported as supported from roughly v2.1.205. Version-dependent — verify on the target CLI. |
| `/compact` via Agent SDK | `query(prompt="/compact")` triggers compaction on the session. |
| Model self-compaction | Not possible; no tool exposes compaction to the model mid-session. |
| Auto-compaction | Always on near the context limit; threshold not publicly configurable. |
| PreCompact hook | Fires with `manual`/`auto` matchers; can **block** compaction (exit 2 or `{"decision": "block"}`) but **cannot inject** instructions into the compaction prompt. |
| SessionStart hook | Supports a `compact` matcher (also `startup`, `resume`, `clear`, `fork`); returning `hookSpecificOutput.additionalContext` injects text into context immediately after compaction. |
| Compactor steering | A "Summary instructions" section in project memory (CLAUDE.md) is read by the compactor and shapes what the summary preserves. |
| Context introspection | No live tokens-used/remaining API; the SDK emits a `compact_boundary` system message after the fact. Orchestrators must estimate or track manually. |
| Subagents | Auto-compact like main sessions; results roll up as a single tool result in the parent. |
| This machine | No `claude`, `codex`, or `grok` CLI installed; workers here run through host agent tools where compaction is automatic and not skill-triggerable. **[observed]** |

## 6. Doctrine: recycle beats summarize

A compaction summary is a lossy paraphrase written under context pressure. A fresh session
restoring from the survival guide, session JSON, and execution log is a lossless
"compaction," because the state lives in files rather than in the summary's fidelity. Elves
already made this architectural bet — the survival-guide apparatus exists because compaction
loses things. The default for workers should remain per-batch fresh sessions; host
compaction is the backstop for the driver's own long session and for deliberately long-lived
supervised workers. [analysis]

**Prewalk caveat.** The exact-session prewalk is the one place where session continuity is
the point: qualification depends on guide-phase facts being retained into the execution
phase. A compaction inside such a session can summarize away exactly those retained facts,
silently invalidating the premise behind `retained_safe`. Until proven otherwise, a
compaction event inside a qualified prewalk session should be treated as de-qualifying for
that session's retained-fact guarantees. Section 7 proposes making this normative.
[analysis]

## 7. Proposals

All four are deterministic, grant no authority, and imply no runtime orchestration. Each
names its overnight-run value per the anti-accretion rule. Sizing: S = one surface + tests
or doc coupling; M = a few surfaces.

- **P1 — SessionStart(compact) recovery hook upgrade (S).** Upgrade the
  `references/operations-guide.md` SessionStart example to use the `compact` matcher and
  `hookSpecificOutput.additionalContext`, injecting the survival guide, session JSON
  pointer, and Stop Gate. Value: unattended runs recover from mid-run compaction
  deterministically instead of relying on a read-order protocol the model must remember.
- **P2 — Recommended "Summary instructions" block (S).** Ship a recommended project-memory
  block instructing the compactor to preserve acceptance IDs, run-doc paths, branch name,
  batch status, and the forbidden-command list. Value: auto-compaction stops erasing the
  exact state the operations guide already warns "can be forgotten after context
  compaction."
- **P3 — Batch boundaries as designated compaction points (M).** Document batch close
  (run docs updated, commit pushed) as the safe compaction moment: interactive operators
  are prompted to `/compact` there; drivers of long-lived supervised workers may issue
  `/compact` on the resumed worker session at batch close where the host grammar supports
  it. Explicitly excludes prewalk sessions (see P4). Value: long full-run workers stop
  hitting forced auto-compaction mid-batch at the worst possible moment. Depends on
  verifying the headless `/compact` row of section 5 on the target CLI first.
- **P4 — Prewalk compaction de-qualification sentence (S, normative).** Add to
  `references/prewalk.md`: a compaction event inside a qualified exact-session prewalk
  invalidates that session's retained-fact guarantees; continuation falls back to packet
  semantics unless re-qualified. This edits normative text, so the consistency-policy pins
  must be updated in the same change per the coupling rule. Value: prevents an unattended
  run from silently trusting guide facts that a mid-run compaction may have destroyed.

Suggested order: P1 + P2 together (docs-only, immediate), P4 next (small normative change),
P3 after live verification of the headless `/compact` grammar.

## 8. Status snapshot and resume notes

State of the world as of this review (all **[observed]** on 2026-07-27):

- Upstream `aigorahub/elves` main = v2.17.1 (`9731fc3`); no open PRs at review time.
- Fork `RBrownHOPE/elves` main = `81eb1a1`: content-identical to v2.17.1, with the fork's
  five historical reconciliation merge commits joined; pushed 2026-07-27. Full local suite
  on the merged tree: exit 0 (Python 3.9.6 host, floor-gated skips expected).
- Parallelves (PR #100) merged 2026-07-20 as v2.11.0 (merge `d910700`); its contract,
  validator, CLI, and tests are untouched through v2.17.1. Suggestions issue #86 is closed.
- Leftovers on the shared machine, safe to remove when convenient: worktrees
  `../elves-parallelves` (branch `feat/parallelves`, `9a2e9c0`) and
  `../elves-audit-follow-ups` (branch `feat/audit-follow-ups`, `483aac0`), plus local
  rollback tags `elves/audit-follow-ups/pre-batch-*` and `elves/parallelves/pre-batch-*`.

To resume from another machine:

1. Pull this branch or the merged doc; everything decision-relevant is in sections 5–7.
2. Before staging P3, verify on a machine with the CLI installed: `claude --version`
   (needs the headless slash-command support, reported ≥ v2.1.205), then confirm
   `claude -p --resume <sid> "/compact"` compacts rather than echoing, and confirm the
   SessionStart `compact` matcher + `additionalContext` fields against the current hooks
   documentation.
3. Open decisions: which of P1–P4 to stage as an Elves run and in what grouping; whether
   P4 lands normative immediately or after live verification of compaction behavior inside
   a resumed session.

## 9. Source pointers

- `references/adaptive-worker-routing.md` — routing table; §"Cache and authority limits".
- `references/operations-guide.md` — §"Advanced: Claude Code SessionStart hook"; forbidden
  command hooks; "instructions can be forgotten after context compaction."
- `SKILL.md` — §"Compaction Recovery".
- `references/prewalk.md` — exact-session contract and `retained_safe` semantics (P4
  target).
- Claude Code documentation (researched this session): hooks reference (PreCompact,
  SessionStart matchers, `hookSpecificOutput.additionalContext`), headless mode, Agent SDK
  agent-loop (auto-compaction, `compact_boundary`, summary instructions).
