# Parallelves: Cobbler-coordinated parallel implementation lanes (v1 contracts + width-test tooling)

Base: upstream v2.10.4 (`639b0cb`). Design provenance: the Parallelves design conversation
following the v2.10.1 review (issue #86), refined into: serial-by-default parallelism as an
*earned routing outcome*, the trunk -> lanes -> integration topology, the pairwise
surface-disjointness invariant, the width test, integration entropy review, and the Cobbler
framing (parallel lanes are Cobbler routing writer agents the way it already routes read-only
lenses — same coordination pattern, explicitly NOT the same authority model).

## Why

When a plan genuinely contains independent lines of work, the driver can stage several worker
lanes on separate worktrees and let execution proceed concurrently, reviewing lane results as
they arrive. Elves already contains nearly all the machinery (per-session full-run supervision,
worktree isolation, owned/forbidden packet surfaces, per-batch confidence signals for lane
triage, Cobbler's parallel dispatch pattern). What is missing is the contract layer and the
deterministic planner-side tooling that makes parallelism honest: a width test that declines
parallelism with a recorded concrete reason whenever it would not clearly help.

## Scope guard (v1 is contracts + deterministic tooling, no runtime orchestrator)

This run ships: the normative Parallelves contract, glossary vocabulary, plan-template lane
grammar, a deterministic lane validator + width test with honest decline reasons, a safe
`worker.parallel` preference (`off` default, `auto` conservative), session/doc surface updates,
and host-parity documentation. It does NOT ship a multi-lane runtime supervisor: Phase-1
operation composes existing per-session `implement full-run-*` commands, one per lane, exactly as
documented today. No sentence may claim runtime lane orchestration, automatic lane scheduling, or
any change to authority (lanes never gain merge/PR/protected-ref authority; prewalk lanes remain
feature-gated exactly as today — per-lane prewalk needs no new machinery and activates for no
host until operator-authorized canaries exist).

## Constraints and non-negotiables

- Serial remains the default everywhere; `worker.parallel=auto` may only *recommend* lanes when
  every width-test gate passes, and every decline records a concrete
  `parallel_declined:<reason>` provenance. Nothing auto-launches.
- Deterministic, model-free tooling only (same character as `route-worker` and
  `acceptance_contract`): plan parsing, DAG checks, path-partition checks, recorded-timing
  arithmetic. No model calls.
- Every edited normative sentence updates its `consistency_policy.py` pins in the same batch;
  additive pins only; no label sets or forbidden guards touched (extend the persona/wording
  guards only if a new normative phrase requires a pin).
- Public API snapshot: additions only.
- Local interpreter is Python 3.9.6 (repo floor 3.10): full suite must end 0 failures / 0 errors
  with the expected floor-gated skips; CI matrix unchanged.
- Codex/Claude parity: every operator command appears in both host grammars where they differ,
  and the contract text is host-neutral (parity is a stated acceptance criterion, reviewed by a
  dedicated parity lens).
- Commit subjects follow the v2.10.x schema including the Confidence trailer contract on Close
  commits.

## Batches

### Batch 1: Normative contract and vocabulary

Scope:

1. New `references/parallelves.md` — the normative contract, containing exactly these sections:
   - **Promise**: what Parallelves is (Cobbler-coordinated parallel implementation lanes within
     one run) and is not (a second orchestration layer; a default; a runtime scheduler; any
     authority change). One coordination hierarchy is preserved: Cobbler routes lanes the way it
     routes lenses; lanes are writer agents under the existing worktree/lease/branch authority
     model, and the read-only-vs-writer distinction is stated explicitly.
   - **Topology**: trunk -> lanes -> integration. Trunk batches build shared foundations
     serially; lanes run on pairwise-disjoint owned surfaces in dedicated worktrees on their own
     feature branches; integration merges lanes into an integration branch with regular merge
     commits (never rebase), driver-owned order, and one PR.
   - **The width test** (serial by default, parallel only when it clearly helps): four gates —
     structural width (>= 2 lanes, pairwise-disjoint owned surfaces, acyclic `depends_on` with
     no cross-lane edge between concurrent lanes), worker-dominance (recorded per-batch timings
     show worker execution dominating driver serial obligations; absent history declines
     honestly), lane budget (2-3 lanes max in v1; concurrent-worker cost acknowledged), risk
     posture (high blast-radius / shared-surface-heavy plans stay serial). Every failed gate
     yields a concrete `parallel_declined:<gate>:<detail>` reason; `worker.parallel` grammar is
     `off` (default) | `auto` (recommend-only, conservative).
   - **Integration review**: the cross-lane entropy review is mandatory before the integration
     PR is review-ready — duplicated helpers, convention divergence, and conflicting approaches
     to shared concerns are findings per-lane review structurally cannot see; Cobbler's
     preserve-dissent stage names this. Per-lane confidence signals order the driver's review
     queue (low confidence and flagged unsure areas first).
   - **Reclassification and demotion**: a lane discovery that invalidates the partition pauses
     lanes, runs a trunk batch, and re-forks or collapses to serial; going parallel is a
     reversible bet.
   - **Competitive lanes** (optional mode): two lanes may deliberately attack the same problem
     with different approaches and integration judges — dissent preserved literally; owned
     surfaces still disjoint via per-lane scratch namespaces; at most one lane's result lands.
   - **Prewalk lanes**: per-lane prewalk is the existing per-session lifecycle unchanged;
     qualification, `retained_safe`-only activation, and every current gate apply per lane; no
     host is behaviorally qualified and nothing here changes that.
   - **Phase roadmap**: Phase 1 (this contract + N parked full-runs composed by the driver),
     Phase 2 (session-schema lane state and staging validation), Phase 3 (prewalk lanes when
     hosts qualify). Runtime lane supervision is explicitly future work.
2. `references/glossary.md`: add entries — Parallelves, Lane, Trunk batch, Integration review,
   Width test, Competitive lanes, `parallel_declined` provenance. Keep one definition per term,
   consistent with `references/parallelves.md`.
3. `references/plan-template.md`: add an optional `## Lanes` section documenting the machine
   grammar (fenced yaml block: `lanes:` list with `id`, `name`, `depends_on`, `owned_surfaces`,
   `batches`; `trunk:` batch list) with one example and the sentence that omitting the section
   means serial (the default).
4. Consistency pins for every new normative sentence, in this batch.

Acceptance criteria:

- [x] B1-A1: `references/parallelves.md` exists with all eight sections above; no sentence
  claims runtime orchestration, automatic launching, authority changes, or prewalk availability;
  serial-default and recommend-only wording is pinned in `consistency_policy.py`.
- [x] B1-A2: All seven glossary terms resolve with definitions consistent with the contract;
  `python3 scripts/check_repo_consistency.py` passes.
- [x] B1-A3: `references/plan-template.md` documents the optional `## Lanes` yaml grammar with a
  valid example, and states that omission means serial.

Blast radius: docs + `consistency_policy.py` only. Risk: low.

### Batch 2: Deterministic lane validator and width test

Scope:

1. New `scripts/cobbler_runtime/parallel_lanes.py` (stdlib-only; imports at most `schema`,
   `acceptance`, `preferences`-adjacent helpers without cycles):
   - Parse the plan's optional `## Lanes` fenced yaml block WITHOUT any yaml dependency: the
     grammar is intentionally line-based (keys above); write a small bounded parser with
     fail-closed `ValidationIssue` codes (`parallel_lanes_grammar_invalid`,
     `parallel_lanes_missing`) — reuse the repo's existing bounded-read idiom.
   - Validators: `validate_lane_partition(lanes)` — pairwise-disjoint `owned_surfaces` (path
     prefix semantics: a lane owning `scripts/foo/` conflicts with another owning
     `scripts/foo/bar.py`), non-empty surfaces, ids unique/stable (`L1`-style), cycle-free
     `depends_on`, no dependency between lanes marked concurrent; concrete codes
     (`parallel_lanes_surface_overlap`, `parallel_lanes_dependency_cycle`, ...).
   - `width_test(lanes, *, timings, max_lanes, risk)` — pure function applying the four gates
     and returning a decision record: `{parallel: bool, lanes: [...], declined: ["parallel_declined:<gate>:<detail>", ...]}`;
     timings come from an optional bounded JSON history file argument (absent history ->
     `parallel_declined:worker_dominance:no_recorded_timings`); never a model call.
2. `scripts/cobbler_runtime/preferences.py`: `worker.parallel` accepted values `off`/`auto`
   (default `off`) following exactly the `worker.prewalk` pattern (safe unknown-field survival,
   no authority).
3. CLI: `python3 scripts/cobbler_agents.py lanes validate --plan <path> --json` and
   `python3 scripts/cobbler_agents.py lanes plan --plan <path> [--timings <json>]
   [--risk <low|standard|high>] --json` wiring the two functions; read-only, no state writes;
   errors as the standard issues envelope.
4. Tests (new `tests/test_parallel_lanes.py`): grammar accept/reject, overlap detection incl.
   prefix nesting, cycle detection, each width gate passing and declining with its exact code,
   preference default/round-trip, CLI subprocess both subcommands both directions.

Acceptance criteria:

- [x] B2-A1: The parser accepts the template's documented example and rejects malformed blocks
  with stable codes; no yaml import appears anywhere in the module.
- [x] B2-A2: Partition validation catches exact-duplicate and nested-prefix overlaps and
  dependency cycles with concrete codes, proven by tests.
- [x] B2-A3: The width test returns `parallel: false` with concrete `parallel_declined:` reasons
  for: missing lanes section, single lane, overlapping surfaces (via validation), absent timing
  history, driver-dominant timings, lane count over budget, and high risk; and `parallel: true`
  only when every gate passes — each case proven by a test.
- [x] B2-A4: `worker.parallel` defaults `off`, accepts `auto`, rejects other values, and grants
  nothing (mirrors the `worker.prewalk` preference tests); CLI subcommands proven by subprocess
  tests; public API snapshot additions only; full 3.9 suite 0 failures / 0 errors.

Blast radius: new module + one CLI subcommand + preferences addition + tests. Risk: medium.

### Batch 3: Session, parity, and review-surface integration

Scope:

1. `references/schema-and-acceptance.md`: document the optional session `lanes` key (advisory in
   v1, exactly like the pre-handoff-v1 posture): each lane row mirrors the plan grammar plus
   `branch`, `worktree`, `session_id`, `status`; a session without `lanes` is serial. State
   explicitly that v1 records lane state for recovery and does not validate it beyond JSON shape.
2. `references/host-parity.md`: Parallelves parity section — identical contract on both hosts;
   the `lanes` CLI shown once (host-neutral python invocation); per-lane full-run commands are
   the existing documented per-host grammars; note that lane workers follow the same
   subscription-native default and optional-provider rules as any worker.
3. `references/review-subagent.md`: integration entropy review protocol (inputs: cumulative
   integration diff, every lane's per-lane review record and confidence signals; questions:
   duplicated helpers across lanes, convention divergence, shared-concern conflicts; output
   classes; confidence-ordered queue guidance).
4. `SKILL.md`: one compact Parallelves subsection in the appropriate workflow area: serial
   default, width test, recommend-only `auto`, trunk/lanes/integration in three sentences, and a
   pointer to `references/parallelves.md`. `AGENTS.md`: one thin pointer line (it is a thin
   adapter; follow its existing pointer idiom). `README.md`: one reference-index row plus one
   sentence under the operations/worker area.
5. Consistency pins for every new normative sentence, same batch.

Acceptance criteria:

- [x] B3-A1: Session `lanes` key documented as advisory with the exact field list; no validation
  claim beyond shape; schema doc's canonical-map style followed.
- [x] B3-A2: Parity section states identical semantics for Claude Code and Codex with any
  host-specific invocation differences shown in both grammars; a dedicated parity review lens
  confirms no Claude-only or Codex-only assumption anywhere in the new text (recorded in the
  execution log).
- [x] B3-A3: SKILL/AGENTS/README additions land with pins; `check_repo_consistency.py` passes;
  review-subagent protocol includes the confidence-ordered queue and the three cross-lane
  question classes.

Blast radius: docs + pins. Risk: low-medium (pin synchronization volume).

### Batch 4: Guide, changelog, durable docs, coherence sweep

Scope:

1. `guide/index.html`: a short "Parallel lanes (Parallelves)" subsection in the task-first guide
   voice (match surrounding style; PRODUCT.md's guide voice rules apply — no em dashes in guide
   prose): what it is, serial default, when `auto` recommends lanes, pointer to the reference.
2. `CHANGELOG.md` `[Unreleased]`: one section describing the v1 contract + tooling honestly
   (recommend-only, no runtime orchestration, serial default).
3. `.ai-docs/architecture.md`: one paragraph (contract layer + validator location + preference);
   `.ai-docs/conventions.md` or `gotchas.md` only if a genuinely new repeatable rule emerged.
4. `TODO.md` Live: two tracked follow-ups — Phase-2 session-lane staging validation, Phase-3
   runtime lane supervision (each one line with rationale).
5. Coherence sweep: `parallelves.md` cross-references resolve; glossary/template/contract say
   the same things; no stray availability claims anywhere (grep sweep recorded in the log).

Acceptance criteria:

- [x] B4-A1: Guide subsection present in guide voice; changelog section accurate to what
  shipped; consistency + release checklists pass (`release_checklist.py` in its
  unreleased-tolerant mode).
- [x] B4-A2: `.ai-docs` updated; TODO.md Live carries both phase follow-ups; the grep sweep for
  orchestration/availability overclaims is clean and recorded.
- [x] B4-A3: Full 3.9 suite 0 failures / 0 errors on the final tip; consistency gate green;
  public API snapshot additions only.

Blast radius: docs + pins. Risk: low.

## Master Acceptance

- [x] M-A1: Full suite green on the final tip (local 3.9 green-with-skips; total strictly
  increased; nothing deleted or weakened) and every batch's gates green at its close.
- [x] M-A2: Honesty invariants hold everywhere: serial default, recommend-only `auto`, no
  runtime-orchestration or availability claims, no authority changes, prewalk gating untouched —
  verified by a dedicated final review pass across the cumulative diff.
- [x] M-A3: Codex/Claude parity explicitly reviewed and recorded; upstream PR submitted from the
  fork branch against `aigorahub/elves` `main` with an accurate body.

## Batch sizing

- Workers run at fable/low: batches are deliberately smaller and more mechanical than the audit
  run's, with contracts that spell out exact sections, codes, and gates. Split further if a
  fable/low worker churns.

## Out of scope

- Runtime multi-lane supervisor, lane scheduling, session-lane validation beyond advisory
  documentation, any prewalk activation, any authority change, release promotion.
