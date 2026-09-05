# Agent teams for Elves

## Mission

Let one driver use helpers on one task. Keep callback delivery optional, preserve exact identities, and require independent review. Use the Lantern v1 checkpoint protocol. Existing standalone runs retain their current behavior.

## Batch 1: Reports and read only teams

Build on the Cobbler CLI, preferences, dispatch, and session acceptance records. The driver owns canonical state. Helpers cannot change permissions, routes, or merge authority. Callback failure preserves the message ID for reconciliation. Read only proposals precede critique. No implementation helper can qualify as the independent reviewer.

**Acceptance criteria:**

- [x] B1-A1: Optional callbacks persist message IDs, use bounded subprocess calls, negotiate protocol, and consume only at named checkpoints.
- [x] B1-A2: Saved team roles resolve through existing preferences and public team commands run independent proposals before critique with existing dispatch.
- [x] B1-A3: Driver owned contributor identities block contributor review in route selection and final readiness while accepting a fresh same family reviewer.

## Batch 2: Persistent writer supervision

Build on parallel lane validation. Bind worktrees, branches, sessions, dependencies, and owned paths. Only the driver integrates exact completed results. Pending lanes must keep the run active.

**Acceptance criteria:**

- [x] B2-A1: Lane state survives restart and pending lanes are not terminal.
- [x] B2-A2: Overlap, unmet dependencies, branch drift, and repeated integration block unsafe writer integration.

## Batch 3: Validation and release preparation

Update canonical skill, host adapter, guide, references, changelog, and version to 2.37.0. Run focused and required checks. Obtain independent cumulative review and fix findings. Stop at a landable PR. Merge and installation are not authorized for this run.

**Acceptance criteria:**

- [x] B3-A1: Tests cover callback failures, identity checks, reviewer exclusion, standalone compatibility, and persistent lane recovery.
- [x] B3-A2: Documentation and version surfaces describe supported behavior and limits consistently.

## Master Acceptance

- [x] M-A1: One driver coordinates helpers through public runtime commands without weakening existing execution or landing gates.
- [x] M-A2: Independent review and required checks pass at the final PR commit.

Initial M-A2 proof: PR #275 passed all 13 checks at f74a9cb. Independent review
passed at f97c0d1, with unchanged source and tests through f74a9cb. Any later
source change requires a new review and checks before landing.
