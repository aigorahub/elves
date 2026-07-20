# Parallelves: Cobbler-coordinated parallel implementation lanes

## Promise

**Parallelves** is Cobbler-coordinated parallel implementation lanes within one run. It is not a
second orchestration layer, not a default, not a runtime scheduler, and not an authority change.
There is exactly one coordination hierarchy: Cobbler routes lanes the way it already routes
lenses. The distinction is explicit: Cobbler lenses are read-only responders; Parallelves lanes
are writer agents, and every writer rule already in force applies to them unchanged — the
existing worktree, lease, and branch authority model governs each lane. The coordination pattern
is shared; the authority model is not. Lanes never gain merge, PR, or protected-ref authority.

Serial remains the default everywhere. Parallelism is an earned routing outcome: the
`worker.parallel` preference is `off` by default, and `auto` may only recommend lanes when every
width-test gate passes. Nothing auto-launches. v1 ships contracts and deterministic tooling only;
no sentence in this contract claims a runtime lane orchestrator, and none exists.

## Topology

The shape is trunk -> lanes -> integration.

- **Trunk batches** build shared foundations serially, before any lane forks. Anything two lanes
  would both need lives in a trunk batch.
- **Lanes** run on pairwise-disjoint owned surfaces, each in a dedicated worktree on its own
  feature branch. Disjointness uses path-prefix semantics: a lane owning a directory conflicts
  with any lane owning a path inside it.
- **Integration** merges lanes into an integration branch with regular merge commits (never
  rebase), in a driver-owned order, and produces one PR for the whole run.

Phase-1 operation composes existing per-session worker runs (native or trusted full-run), one
per lane, per each host's documented grammar; the driver stages and reviews each lane as its own
supervised session. Host-by-host invocation parity lives in the Parallelves parity section of
[`host-parity.md`](host-parity.md).

## The width test

Serial by default; parallel only when it clearly helps. The width test is a deterministic,
model-free check with four gates. Every failed gate yields a concrete
`parallel_declined:<gate>:<detail>` reason, recorded as provenance.

1. **Structural width** — the plan declares >= 2 lanes with pairwise-disjoint owned surfaces and
   an acyclic `depends_on` graph containing no cross-lane edge between concurrent lanes.
2. **Worker dominance** — recorded per-batch timings show worker execution dominating the
   driver's serial obligations (staging, review, integration). Absent history declines honestly:
   `parallel_declined:worker_dominance:no_recorded_timings`. A positive worker duration with a
   zero driver duration is valid recorded evidence (there was no serial driver bottleneck); a
   zero worker duration is invalid evidence, including the `0/0` case.
3. **Lane budget** — 2-3 lanes maximum in v1; the concurrent-worker cost is acknowledged, and a
   plan asking for more declines.
4. **Risk posture** — high blast-radius or shared-surface-heavy plans stay serial.

The `worker.parallel` grammar is `off` (default) | `auto`. `auto` is recommend-only and
conservative: a passing width test produces a recommendation for the driver, never a launch.
After the four gates, `lanes plan` applies this preference as a separate policy veto. `off`
records `parallel_declined:preference:off`; it is not a fifth width-test gate.

## Integration review

The cross-lane entropy review is mandatory before the integration PR is review-ready. Duplicated
helpers, convention divergence, and conflicting approaches to shared concerns are findings that
per-lane review structurally cannot see, because each lane's reviewer saw only its own diff.
Cobbler's preserve-dissent stage names this review. Per-lane confidence signals order the
driver's review queue: low-confidence lanes and flagged unsure areas are reviewed first.

## Reclassification and demotion

Going parallel is a reversible bet. A lane discovery that invalidates the partition — a shared
surface neither plan section anticipated, a dependency the DAG missed — pauses the lanes: the
driver runs a trunk batch to rebuild the shared foundation, then either re-forks the lanes on a
corrected partition or collapses the run to serial. Collapsing to serial is a normal outcome,
not a failure.

## Competitive lanes

Competitive lanes are an optional mode: two lanes may deliberately attack the same problem with
different approaches, and integration judges the results — dissent is preserved literally as
competing implementations. Owned surfaces remain disjoint via per-lane scratch namespaces, and at
most one lane's result lands.

## Prewalk lanes

Per-lane prewalk is the existing per-session prewalk lifecycle unchanged. Qualification,
`retained_safe`-only activation, and every current gate in `references/prewalk.md` apply per
lane; per-lane prewalk needs no new machinery. No host is behaviorally qualified today, and
nothing in this contract changes that: prewalk lanes activate for no host until
operator-authorized canaries exist.

## Phase roadmap

- **Phase 1** (this contract): the normative contract plus N parked full-run sessions composed by
  the driver, one per lane.
- **Phase 2**: session-schema lane state and staging validation.
- **Phase 3**: prewalk lanes, when hosts qualify.

Runtime lane supervision is explicitly future work and ships in no v1 batch.
