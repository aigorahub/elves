# Adaptive, Planner-Directed Review for Elves

## Status

Follow-up design proposal. This work should land after the v1.20.1 Cobbler runtime-hardening run,
using evidence from that run to calibrate review cost and escalation rules. It should not expand the
scope of the corrective PR while that PR is validating the external-worker procedure.

## Objective

Add a risk-aware review system to Elves that gives planners explicit control over how each
implementation batch should be reviewed.

Elves currently tends toward applying similar review ceremony at every batch boundary. That is safe,
but it can waste time, tokens, subscription allowance, and paid provider calls, especially for
low-risk work such as documentation, examples, aliases, and version metadata.

The new system must preserve rigorous review where mistakes would compound across later batches while
making routine batches faster and cheaper. Review depth should be planned deliberately, adjusted when
implementation reality differs from the plan, and followed by a mandatory cumulative release review.

This is an orchestration-policy enhancement, not a new Council system. Elves remains the execution
framework, Cobbler remains the coordinator, and optional providers remain role routes.

## Governing cost principle

Between-batch review is a **foundation-safety gate**, not release certification. Its question is:
“Is this batch safe enough for the next batch to build upon?” The final cumulative review asks the
larger question: “Is the complete change ready to ship?”

The adaptive default therefore uses:

- one fast native reviewer between batches;
- deterministic host validation in parallel with that reviewer;
- a narrow review scope covering the current batch and directly affected interfaces;
- explicit time boxes;
- no Claude/Fable, Sakana/Fugu, Grok, OpenRouter, or other external review council between batches;
- no repeated live provider qualification unless relevant behavior changed and the next batch
  depends on it;
- full multi-lens and optional external-provider review at final readiness.

Planners may require stronger between-batch evidence when a batch has an exceptional, concrete risk
that cannot be addressed by native review and deterministic tests. “More model diversity might be
useful” is not sufficient. The contract must name the invariant, why native evidence is inadequate,
and the minimum additional check. External review remains opt-in between batches and is never the
default consequence of labeling a batch high risk.

## Core operating model

Review is determined in two stages.

### 1. Planning-time review contract

During planning, independent planning lenses evaluate each proposed batch and recommend an initial
review contract. The contract records:

- expected risk level;
- required review level;
- reasons for the classification;
- affected invariants;
- required reviewer lenses;
- required validation gates;
- required live provider/tool checks;
- whether review includes earlier foundational commits;
- escalation triggers;
- reusable evidence and invalidation rules;
- estimated review cost.

The main planning agent synthesizes the recommendations into one authoritative decision. Material
disagreement remains visible.

Example:

```yaml
review:
  risk: high
  level: full
  reasons:
    - changes credential delegation
    - changes subprocess lifecycle
    - later provider sessions depend on this contract
  affected_invariants:
    - secret values never enter artifacts or logs
    - requested models require authoritative actual-model evidence
    - timeout kills and reaps every descendant
  required_lenses:
    - architecture
    - security
    - test-integrity
  validation:
    deterministic: full
    live:
      - bounded process-group cleanup
      - one real provider metadata smoke
  scope:
    current_batch: true
    cumulative_from:
      - batch-1
  escalation_triggers:
    - implementation touches Git or persistent-session code
    - more than 10 shared consumers are affected
    - tests expose an undocumented behavior change
  evidence_reuse:
    allowed: true
    invalidated_by:
      - adapter implementation changes
      - CLI version changes
      - provider output decoder changes
```

### 2. Batch-close reassessment

The planning contract is the minimum expected review requirement, not an immutable prediction.
At batch close, Cobbler compares the planned work with the actual diff and execution history.

Reassessment considers:

- files actually changed and their consumer counts;
- architectural centrality and blast radius;
- implementation size, churn, and repeated rewrites;
- deviations from the contract;
- new dependencies or abstractions;
- credentials, environment, authentication, or authorization;
- Git, PR, branch, worktree, lease, patch, or writer behavior;
- persistence, sessions, subprocesses, cancellation, and concurrency;
- migrations and destructive operations;
- test failures, flakiness, and timing sensitivity;
- worker uncertainty or reported limitations;
- prior reviewer dissent;
- removed, renamed, disabled, or weakened tests;
- validity of previously reviewed evidence.

Cobbler may automatically escalate. It must not silently downgrade a planner-selected level.

A downgrade is allowed only when:

- the planning contract explicitly defines a safe downgrade condition; or
- the user explicitly approves it.

## Review levels

### Lightweight

Use for narrow, low-risk, well-understood changes such as wording-only docs, examples, aliases,
non-behavioral metadata, and version references.

Required:

- targeted deterministic tests;
- one fast independent reviewer or native review lens;
- diff and whitespace checks;
- confirmation that no unexpected runtime surface changed;
- no live provider calls by default;
- no full council quorum.

### Standard

Use for ordinary product behavior with bounded blast radius, such as a contained CLI command,
backward-compatible config support, a localized setup workflow, or a helper built on an established
pattern.

Required:

- targeted tests;
- full deterministic project gates;
- one strong independent reviewer;
- contract-versus-diff comparison;
- test-integrity check;
- live smoke only when deterministic proof is insufficient;
- remediation before close for blocking findings.

### Full batch gate

Use for foundational, security-sensitive, persistent, externally mutating, or highly coupled work,
including credentials, model identity, subprocess lifecycle, sessions, Git/writer boundaries,
migrations, authentication, public APIs, and release behavior.

Required:

- full deterministic gates;
- one strong native reviewer with a focused specialist lens;
- a 15-minute default review time box;
- adversarial tests;
- relevant live qualification only when the changed behavior cannot be proven deterministically and
  the next batch depends on that qualification;
- cumulative review of affected foundational commits;
- remediation of blocking findings;
- host verification of straightforward fixes, with re-review only when the fix materially changes
  the reviewed design;
- concrete acceptance evidence before close.

An external reviewer or second independent reviewer is added only when the planner records a specific
exceptional reason. Fable and Fugu Ultra are not routine between-batch reviewers.

### Final cumulative review

Final readiness is always a separate full review level. It may use multiple independent native and
external lenses, the required live connector matrix, complete PR feedback, CI, host parity, release
checks, and cumulative architecture review. Expensive model diversity belongs primarily here.

## Policy presets

### Minimal

- low risk defaults to lightweight;
- medium risk defaults to standard;
- high risk remains full;
- live calls occur only when indispensable;
- final cumulative review remains mandatory.

### Adaptive

Recommended default:

- planners assign the initial level;
- Cobbler reassesses after implementation;
- one native review runs in parallel with validation where safe;
- valid evidence is reused;
- hard-risk signals automatically escalate;
- external between-batch review remains off unless explicitly justified;
- final cumulative review remains full.

### Standard

- at least standard review for runtime batches;
- documentation-only work may remain lightweight;
- high-risk work is full.

### Paranoid

- most product batches receive a full native batch gate;
- additional independent lenses and live qualification may be enabled explicitly;
- less evidence reuse;
- strongest cumulative review.

### Custom

The project or user defines levels, reviewer counts, required lenses, budgets, and escalation rules.

## Configuration

The feature must work without configuration. Native host review remains the zero-config default.
Optional preferences may live in ignored `.elves/models.toml`; run-specific decisions are persisted
in the Survival Guide and structured session state.

```toml
[review_policy]
mode = "adaptive"
default_risk = "medium"
final_review = "full"
allow_automatic_escalation = true
allow_automatic_downgrade = false
reuse_unchanged_evidence = true
parallelize_with_validation = true
external_review_between_batches = false
max_parallel_batch_reviewers = 1
batch_review_timebox_minutes = 10
high_risk_review_timebox_minutes = 15
max_parallel_final_reviewers = 3

[review_policy.lightweight]
minimum_reviewers = 1
full_test_suite = false
live_checks = false

[review_policy.standard]
minimum_reviewers = 1
full_test_suite = true
live_checks = "when_behavior_requires"

[review_policy.full]
minimum_reviewers = 1
full_test_suite = true
adversarial_tests = true
live_checks = "only_when_required_by_changed_behavior"

[review_policy.roles.fast]
preference = ["native:fast", "fallback:native"]

[review_policy.roles.architecture]
preference = ["native:strong", "claude-code:opus", "fallback:native"]

[review_policy.roles.security]
preference = ["sakana:fugu-ultra", "native:strong", "fallback:native"]

[review_policy.final]
minimum_reviewers = 2
allow_external_reviewers = true
required_level = "full"
```

External routes are optional unless the user explicitly marks one required. Role preferences do not
activate external review between batches when `external_review_between_batches=false`; they apply to
final review or an explicitly approved exceptional batch contract.

## Planner responsibilities

Planners justify review depth against concrete risk dimensions:

- architectural centrality and consumer count;
- data-loss potential;
- security and privacy exposure;
- credential access;
- external side effects;
- concurrency and persistence;
- Git and release effects;
- reversibility and migration burden;
- testability and observability;
- provider/model uncertainty;
- downstream batch dependence;
- cost of discovering a defect later.

Planner dissent is recorded:

```yaml
planner_recommendations:
  architecture:
    level: full
    reason: introduces the attempt graph used by every provider
  implementation:
    level: standard
    reason: deterministic fixtures cover the behavior
  security:
    level: full
    reason: named credential delegation is included

synthesis:
  level: full
  deciding_reason: credential handling and downstream dependency outweigh deterministic testability
```

## Plan format

Every batch gains a Review Contract.

```markdown
**Review Contract:**
- Planned risk: high
- Planned level: full
- Required lenses: architecture, lifecycle, adversarial
- Minimum independent reviewers: 1 native
- Time box: 15 minutes
- External between-batch reviewers: none
- Cumulative scope: Batch 1 through Batch 2
- Required live evidence: create/resume the same real session twice because the next writer batch
  depends on proven resume identity
- Reusable evidence: Batch 1 adapter argv fixtures
- Invalidation triggers: adapter, decoder, registry, or session CLI changes
- Escalation triggers: cross-worktree storage, new credential flow, unplanned Git mutation
- Downgrade allowed: no
- Rationale: incorrect session identity would invalidate later writer qualification
```

## Survival Guide and session state

The Survival Guide records the policy and live decision:

```markdown
## Review Policy

- Mode: adaptive
- Automatic escalation: allowed
- Automatic downgrade: forbidden
- Evidence reuse: allowed with digest/invalidation checks
- Final cumulative review: full
- External review between batches: disabled
- Maximum parallel batch reviewers: 1
- Batch review time box: 10 minutes; 15 minutes for high-risk foundations
- Maximum parallel final reviewers: 3

## Current Batch Review Contract

- Planned level: standard
- Actual level: full
- Escalated: yes
- Reason: implementation unexpectedly changed credential delegation
- Required lens: native security
- Required reviewer quorum: 1
- External reviewers: none
- Validation may run in parallel: yes
```

`.elves-session.json` stores both planned and actual review execution:

```json
{
  "review_policy": {
    "mode": "adaptive",
    "automatic_escalation": true,
    "automatic_downgrade": false,
    "reuse_unchanged_evidence": true,
    "final_review": "full"
  },
  "current_batch": {
    "review": {
      "planned_risk": "medium",
      "planned_level": "standard",
      "actual_risk": "high",
      "actual_level": "full",
      "escalated": true,
      "escalation_reasons": ["implementation introduced named secret delegation"],
      "required_lenses": ["architecture", "security"],
      "minimum_reviewers": 1,
      "completed_reviewers": 0,
      "external_reviewers_allowed": false,
      "timebox_minutes": 15,
      "status": "pending"
    }
  }
}
```

## Deterministic risk rules

Model judgment may refine classification, but hard signals enforce minimums.

Mandatory high-risk signals:

- credentials or secret-shaped environment variables;
- authentication or authorization;
- Git refs, worktrees, commits, patches, leases, pushes, or merges;
- persistent session registries;
- process spawning, signals, cancellation, or background jobs;
- migration, destructive behavior, or publication;
- path traversal and filesystem boundaries;
- model identity/provenance used for acceptance;
- sandbox or security-policy changes.

Standard-risk signals:

- runtime behavior changes;
- public configuration changes;
- new CLI arguments or output formats;
- shared utilities with multiple consumers;
- compatibility behavior;
- setup and reconciliation logic.

Low-risk signals:

- wording-only documentation;
- formatting;
- non-behavioral metadata;
- examples that do not change executable behavior;
- comments and fixture naming.

## Parallel execution

After implementation:

1. Freeze an immutable candidate base and tip.
2. Start deterministic validation.
3. Start one time-boxed native read-only review against the same range.
4. Run live checks only after cheap prerequisites pass.
5. Collect evidence and preserve dissent.
6. Synthesize one remediation packet.
7. Re-run invalidated gates; re-review only when remediation materially changes the reviewed design.
8. Close only when the review contract is satisfied.

When an exceptional contract authorizes multiple reviewers, they remain independent and do not see
peer conclusions before reporting.

## Evidence reuse and invalidation

Every reusable review/live record includes:

- commit range and relevant file digest;
- tool/CLI version;
- requested and actual route/model;
- config and fixture digests;
- test command;
- environment variable names used, never values;
- timestamp and result;
- invalidation rules.

Reuse is allowed only when relevant source, config semantics, CLI version, decoder contract, fixtures,
and affected invariants remain unchanged.

Invalidate evidence when:

- an adapter or parser changes;
- a provider CLI version changes;
- an exact model route changes;
- credential policy changes;
- session or persistence semantics change;
- proving tests/fixtures change;
- a reviewer finds the original evidence defective;
- evidence came from an untrusted or mutable tree.

“Previously passed” without a digest and invalidation analysis is not evidence.

## Live-check budgeting

Live calls are behavior-triggered, not ceremonial. They are normally absent from between-batch
review and concentrated in final qualification:

- docs do not rerun every provider;
- adapter changes rerun affected providers;
- generic wrappers use fixtures plus one representative smoke where needed;
- session changes rerun exact resume for the affected CLI;
- credential changes use sentinel wrappers before a minimum real smoke;
- final release qualification runs the complete required matrix.

```toml
[review_policy.live_budget]
max_calls_per_batch = 3
max_retries_per_route = 1
prefer_deterministic_fixture_first = true
require_reason_for_live_call = true
```

A budget never converts missing proof into success.

## Remediation

Review findings are synthesized into one worker packet containing:

- finding and severity;
- evidence and affected invariant;
- required outcome;
- relevant files and proving tests;
- reviewer disagreement;
- required re-review;
- invalidated cached evidence.

The implementation worker fixes findings but does not declare acceptance. The host verifies
straightforward fixes directly. Re-review is required only when a blocking fix materially changes the
reviewed architecture, security boundary, or acceptance contract.

## Final release review

Adaptive batch review never weakens final readiness. Before landing, Elves performs a full cumulative
review of the configured base range and verifies:

- every batch acceptance and review contract;
- all escalations and authorized downgrades;
- all findings and remediation;
- cumulative architecture;
- test integrity and count;
- docs/config/host parity;
- required live-provider evidence;
- PR feedback and checks;
- operational cleanup;
- merge and release readiness.

Valid evidence may be reused, but applicability to the final tree must be independently confirmed.

## Codex and Claude Code parity

Both hosts must:

- read the same review contracts;
- apply the same escalation rules;
- record requested and actual routes;
- fall back honestly;
- avoid requiring external providers;
- preserve reviewer independence;
- produce equivalent structured evidence.

Codex uses native Codex reviewers by default and host-honest `$elves`/natural invocation. Claude
Code uses native Claude reviewers by default and host-honest `/cobbler` aliases. Either may
optionally route roles to Claude, Codex, Grok, Sakana, OpenRouter, Gemini, or custom wrappers.
Under the adaptive default, each host uses its own fast native reviewer between batches. Cross-host
and external reviewers are reserved for final cumulative review unless an exceptional contract says
otherwise.

## Setup experience

Setup may offer:

```text
Review policy:
  Adaptive (recommended)
  Minimal
  Standard
  Paranoid
  Custom
```

Optional follow-ups:

- use faster/cheaper models for lightweight review;
- use external providers during final review;
- allow exceptional external between-batch review;
- maximum parallel final reviewers;
- between-batch review time boxes;
- permit automatic escalation;
- permit automatic downgrade;
- reuse still-valid evidence.

Model recommendations remain capability-based and dated, not hardcoded prestige rankings.

## Observability

Git history and the execution log expose review decisions:

```text
[branch · Batch 2/5 · Validate] Prove exact resume and registry recovery
[branch · Batch 2/5 · Review] Address lifecycle and concurrency findings
[branch · Batch 2/5 · Close] Close persistent sessions with full review evidence
```

Record planned/actual level, escalation, routes, findings, remediation, reused/invalidated evidence,
live-call count, duration, known cost, and close decision.

## Compatibility

Legacy plans without review contracts continue to work:

- infer a conservative contract during staging;
- record it in the Survival Guide;
- do not silently rewrite the source plan;
- warn that explicit contracts improve predictability;
- retain full review for recognized high-risk surfaces;
- preserve native-only zero-config behavior.

## Testing requirements

Add deterministic tests for:

- policy and review-contract parsing;
- adaptive defaults and presets;
- risk classification and mandatory escalation;
- no silent downgrade and explicit authorized downgrade;
- gate/reviewer selection and quorum;
- optional-provider fallback and required-provider failure;
- external providers disabled by default between batches;
- one-native-reviewer batch default;
- review time-box enforcement;
- parallel validation/review scheduling;
- immutable review packets;
- evidence digests, reuse, and every invalidation class;
- live-call budgeting;
- remediation and re-review;
- refusal to close with incomplete evidence;
- mandatory final cumulative review;
- Codex/Claude parity;
- legacy plans;
- native-only zero-config and zero unsolicited mutation.

## Suggested implementation batches

### Batch 1: Review-policy schema and planning contracts

Add levels, risks, config, batch contracts, serialization, validation, legacy defaults, and templates.
Planned review: full.

### Batch 2: Planner synthesis and deterministic escalation

Add planner recommendations, synthesis, hard escalation rules, reassessment, no-silent-downgrade,
rationale, and dissent. Planned review: full.

### Batch 3: Review execution and parallel scheduling

Add execution paths, immutable context packets, one native batch reviewer in parallel with
validation, exceptional multi-reviewer routing, final-review quorum, remediation, and selective
re-review. Planned review: full native batch gate.

### Batch 4: Evidence cache and invalidation

Add evidence records/digests, reuse decisions, invalidation, live selection, budgets, and conservative
failure. Planned review: full unless implementation remains narrowly isolated.

### Batch 5: Setup, host parity, docs, and metrics

Add preferences, Codex/Claude mirrors, examples, capability-based recommendations, reporting,
migration docs, and host tests. Planned review: standard, escalating if persistence/migration expands.

## Success criteria

- Every batch has an explicit or conservative inferred review contract.
- Planners justify review depth before implementation.
- Cobbler escalates based on the actual diff.
- Review never silently downgrades.
- Low-risk batches avoid unnecessary councils and live calls.
- Foundational batches retain a strong, time-boxed native review.
- Fable, Fugu Ultra, and other external reviewers are not used routinely between batches.
- External model diversity and the complete live matrix are concentrated at final readiness.
- Validation and review run concurrently where safe.
- Evidence reuse requires digest and invalidation proof.
- Missing optional providers never block native-only use.
- Missing required evidence fails honestly.
- Final cumulative review remains rigorous.
- Codex and Claude behave consistently.
- Git/run memory explains every review decision.
- Measured review time/provider usage decreases without weakening acceptance or increasing escaped defects.
