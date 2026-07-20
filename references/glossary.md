# Glossary

One line per coined term. Docs link here on first use instead of re-explaining. If a term is not
in this file, it is not project vocabulary — plain English wins.

- **Elves** — the execution system: plans, branches, PRs, validation, review, run memory, landing.
- **Driver** — the live capable session (Claude Code or Codex) that stages, reviews, and lands.
- **Worker** — the separate session that implements batches; never merges, never owns protected refs.
- **Cobbler** — the default coordination model: classify a task, route it, preserve dissent, fit
  one answer. *Quick Cobbler* = read-only one-off answer; *Cobbler Mode* = current-thread chat
  state; *Cobbler session state* = durable run state in the survival guide and session file.
- **Council** — deprecated alias of Cobbler, kept for invocation compatibility only.
- **Chat-to-work** — end-to-end run that stops at a landable PR; the user merges.
- **Chat-to-land** — the same run with an explicit in-session user authorization to merge.
- **Full-run** — trusted delegation shape: one packet, worker owns internal batches on the feature
  branch while the driver parks.
- **Parked driver / parked monitor** — the driver between launch and wake: no model inference, no
  timed chat, wakes on material events only.
- **Follow mode** — the sanitized non-model stream a parked driver (or the user) can watch.
- **Worker packet** — the standalone coordinator→implementer handoff written at staging
  (`worker_packet_path` in the session); the plan's per-batch handoff blocks are not a substitute.
- **Progress ledger** — the worker's untracked orientation note under `.elves/runtime/`,
  refreshed at each milestone so a cold re-drive starts oriented.
- **Survival guide** — the run's live operator brief and compaction-recovery anchor.
- **Execution log** — chronological proof of what happened, with decisions.
- **Learnings** — durable reusable lessons that outlive a run.
- **Stop Gate** — the explicit "may I stop now?" answer in the survival guide; silence never
  grants stopping.
- **Run Control** — the survival-guide section recording run mode, stop policy, merge policy,
  workspace ownership, and delegation shape.
- **Batch** — one independently shippable slice (`B#`), with stable acceptance ids (`B#-A#`).
- **Master Acceptance** — branch-level outcomes (`M-A#`) proving the whole run is landable.
- **Close** — the single acceptance-backed commit that completes a batch; driver reconciles use
  the `Review` label instead.
- **Collision tripwire / START_TIP** — the recorded branch tip at staging; any unexplained move is
  a collision and a Hard Stop.
- **Rollback ref** — host-owned `refs/elves/rollback/...` pointer for recovery.
- **Landing / land-pr** — the reviewed merge path (regular merge commit, never squash) after
  readiness at the exact final HEAD.
- **Readiness** — plan Acceptance with proof at the exact HEAD; independent of merge authority.
- **Thin safety kernel** — the invariants that never weaken (identity, credentials, no worker
  merge authority, test integrity, exact-HEAD readiness).
- **Legality check / constitution** — human-owned intentions the run must not violate; judged
  PASS/WARN/FAIL per intention.
- **Scout mode** — post-plan spare-time work: adjacent bugs, tests, docs.
- **Ride-along** — a user message prefixed `ra:`/`ride-along:` answered in 1–3 sentences without
  breaking the run.
- **Worktree gc** — the reclaim helper (`preflight.sh --gc-worktrees`) that removes only clean,
  fully merged, fully pushed worktrees; separate from the create helper.
- **Elves report** — the static HTML end-of-run report under `/tmp`.
- **Domain workflow** — a specialized Cobbler-managed pack (math is the first).
- **Codex Goals** — optional Codex continuation plumbing; distinct from Grok Build goal mode.
- **Prewalk** — a trajectory property: one worker session receives the packet once on a guide
  route, makes the first meaningful edit, and is resumed exactly on the execution route with only
  `Continue.`; a cold packet handoff is never prewalk (`references/prewalk.md`).
- **Guide route** — the explicitly pinned model/effort a prewalk worker uses to orient, build the
  bounded TODO, and make the first meaningful edit.
- **Execution route** — the explicitly pinned model/effort the supervisor resumes that same
  session on after the transition checkpoint.
- **Instruction fidelity** — the honest behavioral result of a qualification: `retained_safe`
  (exact trajectory proven, cooperative guide instruction safe to retain — the only state that
  activates the current transport), `pruned` (instruction proven absent after transition),
  `turn_scoped` (instruction proven guide-process-only), or `unsupported` (no usable evidence).
- **Behavioral qualification artifact** — bounded, operator-recorded JSON binding a live canary to
  the exact host, transport, installed version/build, session, routes, continuity facts, and an
  instruction-fidelity result; validated fail-closed by tooling, never fabricated by it.
- **Canary** — an operator-authorized live probe run that exists only to record behavioral
  evidence (e.g. goal terminal canary, prewalk qualification canary); never implicit, never paid
  for silently.
- **Lane A** — the trusted external-implementer lane: worker owns feature-branch progress in a
  host-created worktree under explicit credential grants; host keeps protected refs, review, PR,
  and merge.
- **Mode A1** — Lane A's `branch_progress` Git mode: the worker commits and pushes progress
  slices on its assigned feature branch only.
- **Main driver** — the live host session (Claude Code or Codex) that stages, coordinates,
  reviews, and lands; synonymous with Driver when contrasted with a work driver.
- **Work driver** — the adapter that performs implementation work for a run: `host-native`,
  `grok-build`, `devin-cli`, `opencode-cli`, or `untrusted-writer`
  (`references/schema-and-acceptance.md` owns the spelling map).
- **Implementation lane** — the survival-guide selector for external implementers
  (`implementation_lane: fast | untrusted`); omitted entirely for host-native runs.
- **State capsule** — the bounded explicit handoff v1 declaration (leading Markdown
  `elves-handoff-v1` comment or JSON `elves_handoff`) binding fresh/resume state, ownership, and
  acceptance to branch/HEAD; cold-handoff evidence, never prewalk continuity.
- **Parallelves** — Cobbler-coordinated parallel implementation lanes within one run: serial by
  default, recommend-only `auto`, no runtime orchestrator, no authority change
  (`references/parallelves.md`).
- **Lane** — one Cobbler-routed writer agent in a Parallelves run: a dedicated worktree and
  feature branch on pairwise-disjoint owned surfaces, under the existing worker authority model.
- **Trunk batch** — a serial batch that builds shared foundations before lanes fork (or after a
  reclassification pause); anything two lanes would both need lives in a trunk batch.
- **Integration review** — the mandatory cross-lane entropy review before the integration PR is
  review-ready: duplicated helpers, convention divergence, and shared-concern conflicts that
  per-lane review structurally cannot see.
- **Width test** — the deterministic four-gate check (structural width, worker dominance, lane
  budget, risk posture) that must pass before `auto` may recommend lanes; any failed gate
  declines with a concrete recorded reason.
- **Competitive lanes** — optional Parallelves mode: two lanes attack the same problem with
  different approaches, surfaces kept disjoint via per-lane scratch namespaces, integration
  judges, and at most one lane's result lands.
- **`parallel_declined` provenance** — the concrete `parallel_declined:<gate>:<detail>` reason
  the width test records for every declined gate; parallelism is never silently withheld.
