# Architecture

## Repo shape

This repo is a portable skill package, not an application. Its primary surfaces are documentation,
templates, and small support scripts:

- `SKILL.md`: compact canonical workflow for every supported host
- `AGENTS.md`: thin Codex invocation adapter that points back to `SKILL.md`
- `references/*`: reusable templates and supporting guidance
- `README.md`, `CHANGELOG.md`, `TODO.md`: human-facing project docs
- `guide/index.html`: task-first public user guide, published by GitHub Pages
- `.github/workflows/pages.yml`: dependency-free guide deployment from the same repository
- `scripts/*`: supporting operator utilities, such as preflight
- `docs/plans/*` and `docs/elves/*`: run-specific working memory during an active Elves session

## Coordination hierarchy

Elves has one coordination hierarchy:

1. Elves executes plans through branches, PRs, validation, review, memory, and landing.
2. Cobbler coordinates intent, routing, context, evidence, dissent, medium, and fitted answer.
3. Domain workflows specialize Cobbler for a work type.
4. Providers are optional role routes, not orchestration layers.

Math is the first domain workflow. Its ledgers under `docs/math/*` are domain evidence artifacts
managed inside the Elves run, not a separate Council or Cobbler memory system.

## External-agent runtime (stdlib)

`scripts/cobbler_runtime/` is the standard-library external-agent foundation:

- `schema.py` / `config.py` / `capabilities.py` / `behavior_policy.py`: provider-neutral
  contracts, route resolution, and explicit behavior-policy classification
- `context.py`: redacted context packets and minimal child environments
- `adapters.py`: read-only argv command builders, structured role-report parsing, exact session
  create/resume builders (no bare `--resume` / `--continue` / `--last`)
- `dispatch.py` plus `dispatch_models.py`, `dispatch_results.py`, `dispatch_attempt.py`,
  `dispatch_lane_attempt.py`, `dispatch_external.py`, and `dispatch_host_native.py`: decomposed
  parallel council dispatch, model/result contracts, attempt lifecycle, external lanes, native
  fallback, quorum policy, and lightweight-review utility
- `sessions.py`: exact session registry, lifecycle transitions, context digests, usage ledger,
  Grok parent→child lineage helpers
- `implement.py` / `full_run.py`: legacy bounded implement lifecycle plus the persistent trusted
  full-run supervisor, bounded events/report validation, process fingerprinting, and parked-monitor
  wake classification
- `delegated_git.py` / `isolation.py`: trusted feature-branch reconciliation and shared
  environment/process/path isolation rules
- `leases.py`: exclusive one-writer lease, worker preflight, host-issued write packets, and
  refresh-after-import
- `audit.py`: descriptor-bound Git config/ref/index/object audit, sealed binary format-patch export,
  descriptor-verified retained-byte import, disposable final-tree proof, and clean-host
  `git apply --check --index`
- `evidence_review.py` / `public_api_snapshot.py`: independent evidence assessment and versioned
  public-contract regression snapshots
- `onboard.py` / `setup.py` / `executables.py`: model onboarding, effective setup, and executable
  capability probing
- `preflight_cache.py` / `storage.py`: live-proof cache policy and private atomic runtime storage
- `preferences.py` / `worker_routing.py` / `prewalk.py` / `native_worker.py`: shared safe XDG
  preferences, deterministic plan-to-worker and phase-route decisions, provider-neutral prewalk
  artifacts/transition policy, exact separate-session Codex/Claude launch specs, and the private
  version-2/single-phase plus version-3/prewalk supervised follow/status lifecycle

Parallelves (parallel implementation lanes) is a contract layer plus deterministic tooling, not a
second orchestrator: the normative contract lives in `references/parallelves.md`, the bounded
fail-closed lane parser / partition validator / four-gate width test live in
`scripts/cobbler_runtime/parallel_lanes.py` (surfaced as the `lanes validate|plan` CLI), and the
`worker.parallel` preference (`off` default | recommend-only `auto`) lives in `preferences.py`.
The one-coordination-hierarchy rule is preserved: Cobbler routes lanes the way it routes lenses,
lanes are ordinary writer agents under the existing lease/worktree/branch authority model, and no
runtime lane orchestration exists in v1.

The thin CLI is `scripts/cobbler_agents.py` (`validate-config`, `doctor`, `council`,
`lightweight-review`, `session …`, trusted
`implement full-run-prepare|full-run-launch|full-run-monitor|full-run-await|full-run-reconcile|full-run-logs|full-run-stop`,
and untrusted `worker prepare|packet|audit|export|import|refresh`). Private runtime state belongs under ignored
`.elves/runtime/` (`council/`, `sessions/`, `leases/`, `implement/full-run/`). A trusted Grok
full-run may create and push feature-branch progress while the host retains protected refs, PR,
run-memory, cumulative review, and merge. Its host creates one `b0` rollback ref before handoff,
then parks until a terminal/safety wake; worker commit SHAs are internal rollback points.
Real Grok launch always uses a private per-run `GROK_HOME` and exactly one explicit auth route:
named `XAI_API_KEY`, or the validated canonical owner-private OAuth file through Grok's native
`GROK_AUTH_PATH`. Keeping one canonical file lets Grok's own lock and atomic refresh preserve
rotating tokens. The OAuth route is trusted-Lane-A-only; the worker and host share an OS user, so
this is credential minimization and artifact hardening, not malicious-worker privilege separation.
The launcher resolves and probes one exact native Mach-O/ELF Grok artifact plus its full safe
ancestor chain in a credential-free environment, carries those identities into the child pre-spawn
check, and validates the canonical file through a bound
full-ancestor descriptor walk including supported-platform ACLs.
Grok sessions use caller-generated UUIDs, exact resume, and only models returned by the
authenticated live catalog. Behaviorally proven headless `/goal` enhances the provider; otherwise
the same qualified worker receives one compatible packet. The default follow path exposes bounded,
sanitized progress and terminal facts without passing raw provider output through the driver.
Detached worker commits belong to the separate untrusted lease path: the host creates branch
commits and pushes only after binary patch audit/import.

Delegation routes are explicit `(model, effort)` pairs. “Inherited model” means the exact observed
model identity with only effort lowered: GPT-5.6 strong routes and GPT-4.8 Max/UltraCode use the
same family member at `medium`, while Fable 5 `max`/`ultra` uses the same Fable model at `low`.
Fable→`claude-opus-4-8` at `medium` is a named cross-model exception. Grok is also cross-family and
uses the authenticated live-catalog default at explicit `high`; neither runtime nor docs hardcode a
remembered Composer identifier.

Acceptance staging has two compatible handoff layers. The v2.8 default keeps a missing delegated
packet path advisory, while a session that declares top-level `handoff` opts into strict handoff v1:
exact fresh/resume state, pending-acceptance ownership, current branch/HEAD, and a matching bounded
leading Markdown or JSON packet capsule. Full-run prepare still owns immutable launch-time
plan/session/packet binding. The capsule is cold-handoff evidence and never proves prewalk.

Host differences live in one host-profile registry (`cobbler_runtime/host_profiles.py`): per host
it carries create/resume argv builders, effort grammar, transport name, identity event typing,
provider-secret allowlist, help-probe argv, commit mode, and `launch_ready`. Spec construction,
child-env secret projection, launch identity readiness, prewalk probes, and routing transport
naming all consume the registry instead of per-site `if/elif` chains; `native_worker_profiles()`
is a view of it. The `grok` row is feature-gated (`launch_ready` false, non-yolo
`--permission-mode auto`, `XAI_API_KEY`-only): grok prewalk routing requires the absence of the repository allow_grok=false veto, explicit
consent, and a valid operator-recorded `grok_prewalk_qualification_canary` artifact
(`retained_safe`, bound to the exact version/build from a live installed-binary probe). The
artifact can qualify behavioral evidence but cannot open the separate registry launch gate;
while `launch_ready` is false, routing records
`grok_prewalk_unqualified:launch_feature_gate_closed` with actual mode `off`, and `required` fails
before launch. Other invalid or missing evidence records its concrete
`grok_prewalk_unqualified:<reason>`. No environment is qualified for launch; nothing may claim
Grok prewalk availability.

Exact-session prewalk is a lifecycle inside one subscription-native (or separately qualified)
worker, not a cross-worker context transfer. The packet appears once on the guide turn; private model-free policy verifies a
bounded TODO, first meaningful edit, session/worktree/Git continuity, and checkpoint before the
supervisor resumes that same ID on a separately pinned execution route with `Continue.`. Static
host help is advertised capability only; version-bound behavioral evidence gates actual prewalk and
records instruction fidelity as `pruned`, `turn_scoped`, `retained_safe`, or `unsupported`. The
current persisted-instruction path activates only `retained_safe`; the other usable-sounding states
require a future, separately proven delivery mechanism. The driver retains all canonical memory,
terminal review, PR, and landing authority. Normative detail lives in `references/prewalk.md`.
Hard external subprocess lanes require a recursive boundary acquired atomically with the child.
The current Python runtime cannot prove that boundary on Linux or Darwin—even when Linux has a
bubblewrap PID namespace—so optional routes fall back host-native and required routes block before
snapshot creation or spawn. The legacy bounded `--exec` convenience has no
qualified boundary on either supported OS and fails before spawn. Its print-only argv workflow and
the separate trusted full-run route remain available; the latter operates under an explicit
same-user policy boundary and does not claim malicious-worker recursive containment.

The survival guide remains the home for live run control, checkpoint semantics, active compute, next exact batch, and operator constraints; the Cobbler session state extends that live layer.

## Memory layers

Elves now uses distinct layers instead of one giant note pile:

1. `plan`: authoritative scope and batch structure for the current run
2. `survival guide`: live run control, Cobbler session state, checkpoint semantics, active compute,
   next exact batch, and operator constraints
3. `learnings`: durable reusable lessons that should survive this run
4. `execution log`: chronological proof of what happened
5. `.ai-docs/*`: curated durable truths about this repo

The point of the layering is to keep raw chronology, reusable lessons, and stable repo knowledge in
different places so later agents do not need to infer intent from noisy notes.

## Documentation system

This repo now treats documentation as a maintained surface:

- Raw observations belong in the execution log.
- Live operator state belongs in the survival guide and should be rewritten in place.
- Reusable lessons belong in the learnings file.
- Stable architecture, conventions, and traps belong in `.ai-docs/*`.
- The shortest user path belongs in `guide/index.html`; the README links it and retains the full
  repository reference.
- Human-facing explanations and release notes belong in `README.md`, `CHANGELOG.md`, and `TODO.md`.

Because this repo *is* a skill, changes almost always cross multiple surfaces. Updating one file in
isolation is usually not sufficient.

Acceptance identity is a cross-surface staging contract. The plan is authoritative; `B0` and `B1`
are equally valid starts, and bare or bracketed stable-id checkbox rows are equivalent. Before any
worker launch, staging parses the plan and reconciles session and packet criteria by id and text so
syntax or drift failures are returned to the coordinator immediately rather than at landing.


## Trusted full-run authority note

Trusted Grok full-run uses one session, feature-branch progress, parked-monitor driver, and bounded events. Untrusted detached leases remain a distinct authority model.
