# Built-in Review Subagent

This is the default review mechanism for Elves. It works out of the box with zero configuration. All it needs is `gh` CLI auth and an open PR.

## What It Does

For host-native and legacy bounded execution, the coordinator spawns this subagent after each
batch. For a healthy trusted full-run, the coordinator stays parked while the worker runs its
internal batches and invokes this reviewer once, cumulatively, at terminal/safety wake (v2.3
convergent review: consolidate blockers, revise, then **delta re-review** only — see
`proof-and-review.md`). The subagent:

1. Reads all PR comments, review threads, and CI status via `gh api`
2. Reads the current batch diff (host-native/legacy) or the cumulative full-run diff (trusted
   full-run wake)
3. Reads the plan to understand the broader goal
4. **Reads the batch contract** (from the execution log) to know exactly what was supposed to be delivered — specific behaviors and testable acceptance criteria
5. **Evaluates code quality** against the Code Quality Philosophy (see SKILL.md)
6. Produces a structured assessment: what's blocking, what's a warning, what's fine, whether every contract item was delivered, and whether the code leaves the repo in better shape

The reviewer has **four jobs**, in this priority order:

1. **Completeness vs plan and contract** — not only “do the changes look correct,” but “is the batch done relative to the plan?”
2. **No regressions** — correct local changes can still break other behavior. Shared surfaces, callers, flows that were not edited can still break.
3. **Constitution / legality** — if `docs/constitution.md` or `CONSTITUTION.md` exists, deal-breaker behaviors must still hold even when those areas were not the focus of the batch.
4. **Bugs and code quality** — security holes, wrong logic, duplication, band-aids, architecture drift.

A bug-free batch that only implements half its contract is incomplete. A fully-implemented batch with a security hole isn’t done. A batch whose diff is “correct” but breaks an untouched flow or a constitution invariant is a **regression FAIL**. A batch that works perfectly but introduces duplicated utilities or band-aids makes every future batch harder — that's blocking too.

**Correct changes can still break things.** Prefer finding indirect breakage over congratulating a clean-looking patch.

The coordinator then acts on the findings. On host-native/legacy routes it fixes blockers, pushes,
and repeats until the batch is clean. On trusted full-run it does this cumulative fix/review loop
only after terminal/safety wake; it does not wake after healthy worker batches or pushes.

## How to Invoke

The coordinator spawns this review with a prompt like:

```
Review the current state of PR #[NUMBER] for repo [OWNER/REPO].

**Today's date is [DATE].** Your training data has a cutoff. The codebase may use libraries, APIs, model versions, or conventions that are newer than what you know. **The current codebase is the source of truth, not your training data.** If the code uses a library version, model name, API endpoint, or SDK that you don't recognize, assume the coding agent has verified it is correct and current. Do NOT flag something as wrong just because it doesn't match what you expect from your training data. If you genuinely believe something is outdated or incorrect, state your concern but note that you may be working from stale knowledge.

## What to read

1. **The commit history for this batch.** Run `git log` for the batch's commits and read the messages carefully — both subject lines and bodies. The coding agent communicates through commit messages: design decisions, justifications for non-obvious choices, reasons for hardcoded values, explanations for pattern deviations. Before flagging something, check whether the commit message already justifies it. A choice that is explained and reasoned in the commit is an intentional design decision, not a finding (unless the reasoning is actually wrong).
2. All PR review threads (focus on **unresolved** threads — resolved threads have already been addressed)
3. All issue comments (focus on comments **without a reply from the agent** — replied comments have been addressed)
4. CI check status: gh api "repos/OWNER/REPO/commits/HEAD/check-runs"
5. The plan at [PLAN_PATH] — full batch list and Acceptance, not only the current batch narrative
6. The batch contract in the execution log at [EXECUTION_LOG_PATH] under the current batch heading,
   or every delegated batch contract for a cumulative trusted full-run review
7. The **constitution** at `docs/constitution.md` or `CONSTITUTION.md` if it exists — deal-breaker
   flows/invariants that must still work even when not directly edited
8. Any full-run `model-routing` preferences in the survival guide, execution-log contract, or
   `.elves-session.json`: requested route, actual route, and fallback reason. If an external
   reviewer (e.g. Gemini/Antigravity) also helped plan, **prefer** resuming its **exact
   session_id** when available (most robust; never latest/continue). **If no session id**, fall
   back to **repo documents** the agent can see (plan, contract, execution log, Survival Guide,
   constitution, PR). Missing chat memory is not an excuse to skip completeness review; missing
   documents when a session id exists is not an excuse to skip re-reading the plan/constitution.
9. Any `## Cobbler Session State` block or `.elves-session.json` `cobbler.default_for_session`
   state that explains how the run is being coordinated
10. For mathematical runs, the relevant `docs/math/*` ledgers: claim, source, model-call,
   open-question, failed-approach, and human-verification ledgers
11. The `review_comments` array in [SESSION_JSON_PATH] to see what was already handled in previous cycles

```bash
# Route start is bN for host-native/legacy batch review, b0 for trusted full-run cumulative review
ROUTE_START_REF=refs/elves/rollback/<run>/<session>/<bN-or-b0>-<digest>
git log --format='%H %s' "$ROUTE_START_REF"..HEAD
# Read full commit messages (subject + body) for context
git log "$ROUTE_START_REF"..HEAD
# Fetch review threads — filter for unresolved
gh api "repos/OWNER/REPO/pulls/NUMBER/comments" --paginate
gh api "repos/OWNER/REPO/pulls/NUMBER/reviews" --paginate
# Fetch issue comments — check which have agent replies
gh api "repos/OWNER/REPO/issues/NUMBER/comments" --paginate
# CI status
gh api "repos/OWNER/REPO/commits/HEAD/check-runs"
```

**Skip comments already recorded as handled in `.elves-session.json`.** Only evaluate new and unresolved findings. This prevents re-litigating settled issues across review cycles.

## Phase Route Context

If the run uses full-run model routing, treat it as advisory routing metadata unless the survival
guide explicitly marks the phase `required: true`. Verify that the reviewer received the requested
route, actual route, and material fallback reason. Missing optional provider access is not a
blocker for a native-first run; it is a warning only when the fallback changes risk or confidence.
It is blocking only when the survival guide explicitly made that phase route required and the
coordinator could not satisfy it. Do not infer route authority from model prestige.

## Math Domain Workflow Context

If the PR touches a mathematical run or math workflow docs, verify that Cobbler remains the
coordinator, math ledgers are treated as domain evidence artifacts, and provider routes are optional
unless the survival guide explicitly marks them required. Model agreement is not proof; retained
claims need source status, proof status, model-review status, and human-verification status.

## Worker confidence triage (read before the diff):

Read the worker's confidence signal first — the `Confidence:` commit trailers and the
`confidence`/`unsure_about` fields on `batch_complete` events, report `batches[]` rows, or the
legacy done report — and allocate review attention accordingly: prioritize a deeper pass on every
flagged `unsure_about` area. An empty `unsure_about` list is a valid, complete answer, not a lazy
default. The signal is triage only, never authority: it does not skip gates, waive review, or
change completion requirements in either direction. Uniform `high` confidence with empty lists
across many batches is a calibration observation to note in the report, not a violation.

For a trusted full-run, the successful terminal `full-run-monitor --json` or
`full-run-await --json` response carries `review_context.review_prompt_block`. The coordinator **must attach that
block verbatim** to the primary Final Readiness prompt. It is bounded, validated, conflict-aware,
and safe-projected for shared OAuth. For a native Claude Code or Codex worker, the coordinator
constructs the same table from every `Confidence:` trailer in the cumulative commit history. If
signals are missing or partial, say so and perform the ordinary full baseline review. Never infer
an asserted-clean answer from absence. Claude Code and Codex follow the same rule and prompt shape.

## Integration entropy review (Parallelves)

When a run used Parallelves lanes (`references/parallelves.md`), this cross-lane pass is mandatory
before the integration PR is review-ready. Its inputs are: the cumulative integration diff, every
lane's per-lane review record, and every lane's confidence signals. The reviewer asks three
cross-lane question classes that per-lane review structurally cannot see:

1. **Duplicated helpers across lanes** — did two lanes each introduce a utility, abstraction, or
   fixture that should be one shared implementation?
2. **Convention divergence** — did lanes drift apart on naming, error handling, module structure,
   or test organization while each staying internally consistent?
3. **Conflicting approaches to shared concerns** — did lanes make incompatible assumptions about a
   shared surface, data shape, or contract that only the merged result exposes?

Findings use the same output classes as every other review in this file: BLOCKING, WARNING, INFO,
or PENDING-DOCS. Per-lane confidence signals order the review queue: low-confidence lanes and
flagged `unsure_about` areas are reviewed first. Uniform `high` confidence with empty lists across
many lanes is a calibration observation to note in the report, not a violation; the signal remains
triage only, never authority.

## For each NEW or UNRESOLVED comment or finding:
- Categorize as: BLOCKING (must fix), WARNING (should fix), INFO (note only), or PENDING-DOCS (implementation is acceptable but supporting docs are stale)
- Identify the source: human reviewer, bot (name which bot), CI check
- Summarize what the issue is and what file/line it references
- Note the comment ID so the coordinator can resolve/reply to it after fixing

## Completeness verification (plan + contract — as important as bug-finding):

Read the **plan** and the **batch contract**. Do not only grade the diff’s local correctness.

For EACH behavior listed in the contract:
- Is it implemented in the diff? Show the evidence (file, function, or route).
- Is it tested? Point to the specific test.
- If missing or partially implemented, mark it BLOCKING.

For EACH acceptance criterion:
- Can it be verified from the diff and test results?
- If a criterion has no corresponding test or verification, mark it BLOCKING.

Also check **plan-level completeness** for this batch’s scope:
- Does the batch leave plan Acceptance criteria for this scope open without a hard-stop note?
- Did “correct” implementation skip a promised behavior that only appears in the plan narrative?

## Constitution / legality (if a constitution file exists):

Read the constitution. For each intention that *could* be affected — including **indirectly**
(shared utilities, data model, auth, payments, API contracts):

- **PASS** — still holds
- **WARN** — ambiguous / fragile
- **FAIL** — broken (BLOCKING)
- **UNCHANGED** — batch cannot affect it

Mark FAIL if a deal-breaker flow/invariant is broken even when that code was not the edit focus.
The ideal of the constitution is: some things must still work even if they were not directly worked on.

## Regression verification (correct changes can still break things):

Ask only: “What existing behavior could this break?” Trace shared surfaces and non-obvious callers.
A patch that is locally correct but breaks an unedited path is a regression finding, not a pass.

## Coordinator-to-implementer handoff obligations:

When the batch used an external or less-capable worker, treat an incomplete handoff as a
**blocking coordinator defect** before blaming the worker. The packet must carry:

1. intent / why
2. non-obvious rationale
3. Build On targets
4. owned surfaces
5. forbidden surfaces
6. acceptance evidence (not “make tests green”)
7. failure modes / pitfalls
8. HEAD / run-doc paths / route-session identity / output format

Also verify **Git history as operator UI**:

- Host pushed meaningful mid-batch slices with
  `[branch · Batch N/total · Contract|Implement|Validate|Review|Close] concrete outcome`
  (or the documented legacy host-only form).
- Subjects are not vague (`Updates`, `progress`, `WIP`, bare `fixes`).
- Authority matched the selected lane: trusted `branch_progress` full-run workers touched only the
  assigned feature branch and never owned protected refs, PR actions, run memory, final review, or
  merge; untrusted lease workers created only audited detached handoff commits and never owned
  refs, remotes, push, PRs, or run memory.
- `Close` appears only with acceptance evidence.
- Protected refs, PR operations, and merge did not dispatch model inference. Trusted
  assigned-feature-branch commit/push is the explicit full-run exception.

## Code quality review (the Code Quality Philosophy):

The goal is that each batch leaves the codebase easier to work on, not harder. For each of these, check the diff:

1. **Root cause over band-aids:** Are fixes addressing the actual problem, or patching symptoms? Look for: try/catch blocks that swallow errors, special-case conditionals that work around deeper issues, "retry and hope" patterns.
2. **Centralize over duplicate:** Did the batch introduce new helpers, utilities, or abstractions that duplicate existing ones in the codebase? Search for similar functions. If `formatDate()` already exists in the codebase and the batch added a new one, that's a finding.
3. **Extend over create:** Did the batch build on existing patterns and modules, or create parallel implementations? New files that replicate the structure of existing files are a red flag.
4. **Architecture first:** Does the new code respect the codebase's existing architecture — module boundaries, data flow, naming conventions, test organization? Or does it introduce novel patterns that conflict with what's already there?
5. **Proactive pattern detection:** Does the new code follow the naming conventions, error handling patterns, and API response structures already established in the codebase? Match existing conventions exactly.
6. **Progressive repo conditioning:** Does this batch leave the repo easier to work on? Look for: clear type annotations on new code, focused single-purpose functions, consistent naming, updated docs and agent instructions (CLAUDE.md, TODO.md).
7. **No hardcoded constants without justification:** Are there magic numbers, URLs, timeouts, thresholds, or config values hardcoded inline? Check the commit message — if the coding agent justified the hardcoding (e.g., protocol-required value, mathematical constant), evaluate whether the justification holds. If there's no justification, flag it.
8. **Runaway detection:** Were the same files modified 5+ times in the batch's commit history without clear forward progress? This suggests symptom-chasing rather than root-cause fixing.
9. **Favor boring technology:** Did the batch introduce new dependencies or libraries? Are they well-known, stable, and composable, or novel and opaque? If a small utility was reimplemented instead of pulling in a dependency, that may be the right call — verify the reimplementation is correct and well-tested. If an unfamiliar dependency was introduced, flag it as WARNING unless there's a clear justification.

Mark code quality issues as:
- BLOCKING if they introduce duplication, violate existing architecture, or band-aid a root cause
- WARNING if they miss an opportunity to improve (e.g., could have added types, could have consolidated)

## Bug-fix quality check:

If this review cycle includes fixes for previously reported bugs, verify:
- Did the fix include a **category test** — a test that catches not just the specific bug but the class of bug it belongs to? (e.g., not just "null check on email field" but "null/undefined/empty across the user input interface")
- Did the category test surface and fix **related bugs**, or was only the reported instance patched?
- If a bug was fixed with no category test, or with a test that only covers the exact reported instance, mark it BLOCKING: "Bug fix for [issue] needs a category test — see bug-fix protocol."

## Shared-surface regression check:

For any file in the diff that's imported, used, or depended on by code outside this batch's scope:
1. **Identify the shared surface.** Is this file a utility, type definition, interface, config, middleware, or any code imported by multiple modules?
2. **Grep for consumers.** Search for imports/requires of the modified file. List the count and note which are inside vs. outside the batch scope.
3. **Verify backward compatibility.** Did any function signatures, exported types, interfaces, or public APIs change? Are changes purely additive (new exports, new optional parameters), or do they modify existing contracts?
4. **Check callers.** For any changed signature or interface, verify all callers were updated. If callers exist outside the batch scope and weren't updated, mark BLOCKING.
5. **Report.** For each shared surface: file path, consumer count, nature of change (additive / modified / breaking), and whether consumers were verified.

If no shared surfaces were modified, state: "No shared surfaces modified in this batch."

Mark BLOCKING if: a shared surface was modified without verifying consumers, a function signature changed without updating all callers, or a type/interface was modified in a way that could break downstream code.

## Documentation freshness check:

Before calling the batch clean, verify that the relevant docs moved with the code:
- run-state drift -> survival guide or execution log
- reusable lesson -> `learnings.md`
- stable repo truth -> `.ai-docs/architecture.md`, `.ai-docs/conventions.md`, or `.ai-docs/gotchas.md`
- human-facing behavior -> README / CHANGELOG / config docs

If the implementation is sound but the required docs are stale, mark the finding `PENDING-DOCS`.

## Also review the diff for:
- Obvious bugs, security issues, or missing error handling
- Changes outside the batch scope that shouldn't be there
- Logic that is internally consistent but doesn't match the contract

## Return a structured report:

### Blocking (must fix before moving on)
- [finding]

### Warnings (fix if easy, defer if complex)
- [finding]

### Info (no action needed)
- [finding]

### Pending Docs (must clear before calling the batch clean)
- [finding]

### Contract Completeness
For each contract item, one line:
- ✅ [item] — implemented in [file], tested in [test]
- ❌ [item] — [what's missing]
- ⚠️ [item] — implemented but [concern]

### Code Quality
- **Root cause:** [any fixes that patch symptoms rather than addressing underlying problems]
- **Duplication:** [any new code that duplicates existing utilities/patterns — name both]
- **Extend over create:** [any parallel implementations that should have extended existing code]
- **Architecture:** [any violations of existing module boundaries, data flow, or conventions]
- **Pattern detection:** [any deviations from established naming, error handling, or structure]
- **Progressive conditioning:** [did this batch leave the repo easier or harder to work on?]
- **Hardcoded constants:** [any unjustified magic numbers/URLs/thresholds — note whether commit message provides justification]
- **Thrashing:** [any files modified 5+ times without clear forward progress]
If all clear, state: "No code quality issues. Batch follows existing patterns and conventions."

### New Issues Found in Diff Review
- [anything you spotted that the bots didn't]
```

## What the Coordinator Does With the Report

1. **Blocking items (bugs)**: Fix each one using the **bug-fix protocol**. For every bug: (a) diagnose the *category* of bug — is this a missing null check? unvalidated input? off-by-one? (b) write a test that catches the category, not just the instance — if one endpoint has a missing null check, test null/undefined/empty across all similar endpoints. (c) Run the test before fixing to surface related bugs. (d) Fix all failures — the reported bug and every sibling. (e) Confirm green. This prevents the same category of bug from surfacing again in the next batch.
2. **Contract items marked ❌**: Go back to Implement (step 5) and finish what's missing. These are blocking — an incomplete contract means an incomplete batch.
3. **Contract items marked ⚠️**: Evaluate the concern. Fix if it's a real gap; log if it's a judgment call.
4. **Code quality findings**: Duplication and architecture violations are blocking — fix them now, not later. Remove the duplicate and use the existing utility. Refactor to follow the established pattern. Root-cause band-aids are blocking if they hide a bug, warning if they're just suboptimal. Pattern consistency issues are warnings.
5. **Warnings**: Fix easy ones inline. Defer complex ones to TODO.md tagged `[elves-scout]`.
6. **Info**: Log in execution log, no action.
7. **PENDING-DOCS**: Update the docs in the same batch when possible. If the doc debt must slip, carry it into the immediate next batch and record that explicitly in the execution log and `.elves-session.json`.
8. **New issues**: Treat as blocking if they're bugs or security; treat as warnings otherwise.

**Critical: fixes must follow the same Code Quality Philosophy.** When the reviewer flags duplication and you go back to fix it, don't create a *third* copy to "consolidate" the first two — actually find the existing utility and use it. When the reviewer flags a band-aid, don't add a bigger band-aid — fix the root cause. The review-fix cycle is where agents are most tempted to take shortcuts because the pressure to "just make it pass" is highest. The reviewer will check the fix too.

### Resolving Comments After Fixes

After fixing issues, the coordinator must close the loop on every comment:

**Review threads** (from bot reviewers and humans): Resolve the thread on GitHub via the API. This marks it as handled so subsequent review cycles only see new, unresolved threads.

```bash
# Resolve a review thread by its thread ID
gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "THREAD_NODE_ID"}) { thread { isResolved } } }'
```

To get thread IDs, fetch review threads with the `node_id` field included. The node ID is the GraphQL ID needed for resolution.

**Issue comments** (bot summaries, general feedback): Reply with a short disposition so the comment is visibly addressed:

```bash
gh api "repos/${REPO}/issues/${PR_NUMBER}/comments" -f body="Fixed in $(git rev-parse --short HEAD). [Validation: added input validation to email field per CodeRabbit finding.]"
```

Or for dismissals: "Dismissed: false positive. Function is a straightforward switch statement; splitting would reduce readability. See execution log batch 1, cycle 2."

**Record every disposition** in `.elves-session.json` under `review_comments` with: comment ID, type (`review_comment`, `review_thread`, or `issue_comment`), source (which bot or reviewer), batch number, review cycle, one-line summary, disposition (`fixed`, `dismissed`, `deferred`, `pending_docs`), and fix commit or reason.

### The Work Queue

For host-native/legacy routes, after resolution the work queue for the next per-batch review cycle
is simply:
- Unresolved review threads (GitHub is the source of truth)
- Issue comments with no reply from the agent
- Any `PENDING-DOCS` items not yet cleared
- New comments triggered by the latest push

If the queue is empty, `PENDING-DOCS` is clear, and the contract is fully ✅, the batch is clean.

After fixing, the coordinator pushes and runs the review subagent again. The loop repeats until the
report has zero blockers, every contract item is ✅, and the queue is empty. For trusted full-run,
apply this same queue cumulatively after terminal/safety wake; never turn a healthy internal batch
into a host review/re-drive cycle.

## Final Readiness Review

Run this once after the final summary and strategic-forgetting pass, before operational-artifact
cleanup, and before the agent declares the branch review-ready. **This is the mandatory final step
of every finite run — never skip it.** It is a cumulative performance and merge-readiness guard: it
catches anything that slipped between host per-batch reviews or worker-internal batches and makes
sure the user returns to a clean PR and a clean memory workspace, confident the branch is green to
merge.

Spawn a fresh review subagent if the platform supports subagents. If not, do the same analysis
directly.

Prompt shape:

```
Review the final state of PR #[NUMBER] for repo [OWNER/REPO].

Today's date is [DATE]. The current codebase is the source of truth.

Read:
1. The cumulative branch diff: git diff [DEFAULT_BRANCH]...HEAD
2. The full commit history for the branch
3. The plan at [PLAN_PATH]
4. The execution log at [EXECUTION_LOG_PATH]
5. The survival guide at [SURVIVAL_GUIDE_PATH]
6. .elves-session.json, especially cobbler, review_comments, and continuation_guard
7. Math ledgers under docs/math when the run is mathematical
8. Every PR review comment — resolved and unresolved, from humans, bots, and CI — plus issue comments and current check runs
9. TODO.md and relevant docs touched by the run

Worker confidence review context (required before reading the diff):
[PASTE review_context.review_prompt_block VERBATIM for a trusted full-run. For a native worker,
paste the equivalent table extracted from every Confidence: trailer. If none were reported, write
"No worker confidence signal was reported; full baseline review required."]

Use the coordinator's exact-tip evidence map. Request only tests whose inputs changed or whose
consumers are reasonably affected. At terminal readiness, require the project's one broad gate;
request E2E or browser proof only when the changed surface can affect it. Reuse unchanged evidence.

Assess:
- Is the branch green and ready to merge — for the human to merge, for an opt-in merge-on-green commit, or for the reviewed-PR landing command if the user invoked it?
- Are there any unresolved PR comments, failing checks, missing docs, or unhandled TODOs?
- Does the cumulative diff include unrelated or surprising files?
- Did any shared surface change without consumer proof?
- Is the memory workspace clean enough to resume from concise docs instead of this chat?

Return:
### Confidence-Guided Review
- [each low-confidence, unsure_about, hidden-reservation, conflicting, partial, or missing area;
  what received a deeper/focused pass; and the resulting evidence]

### Blocking
- [must fix before readiness]

### Warnings
- [safe to defer only with a clear TODO or handoff note]

### PR Feedback Queue
- [unresolved threads/comments/checks and required disposition]

### Cumulative Diff Risk
- [shared surfaces, surprising files, missing proof]

### Memory Workspace
- [survival guide/log/learnings/handoff cleanup needed before handoff]

If everything is clean, say: "Final readiness review clean."
```

The coordinator consolidates all blocking findings into one revision, resolves or replies to PR
comments, updates `.elves-session.json`, and reruns validation affected by that revision. A
delta-only re-review checks the fixes and unresolved blockers; advisory suggestions do not reopen
settled work. Before cleanup, require the target project's single terminal broad gate plus
`python3 "$ELVES_SKILL_ROOT/scripts/elves_landing_check.py" --session <session-path> --repo-root .`
from a clean worktree. A repository-specific aggregate verifier is additional proof only when the
target checkout itself provides one; installed Elves never depends on a repo-only helper. After an
operational-artifact cleanup commit, reuse product proof unless cleanup touched a relevant input;
then run only the affected checks. Poll comments and required checks once on the final tip.
Then hand the user the Elves Report and tell them to review it, and either stop for the user to
merge or — only if the user set a merge-on-green preference or invoked the reviewed-PR landing
command — land a regular merge commit (never a squash).

### Reviewed PR Landing Command

If the user explicitly asks to get a subagent to review the diff from main, read all PR comments,
fix findings, test, and merge commit once green, treat that request as a one-off merge opt-in for
the current PR. The reviewer should use the Final Readiness Review shape, with extra attention to
the live PR feedback queue and whether a regular merge commit is safe now.

The shorthand aliases `\land-pr` and `/land-pr` are explicit reviewed-PR landing commands too.

The coordinator may merge only after the review is clean, the PR is not draft, required checks are
green, no unresolved requested changes remain, and comments/checks have been polled after the final
push. Use `gh pr merge --merge`; never squash or rebase for this command.

## When Subagents Aren't Available

If the platform doesn't support subagents (some Codex configurations, Claude.ai), the coordinator does this analysis directly:

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
PR_NUMBER=$(gh pr view --json number -q .number)

# Get all review data
gh api "repos/${REPO}/pulls/${PR_NUMBER}/comments" --paginate > /tmp/pr-comments.json
gh api "repos/${REPO}/pulls/${PR_NUMBER}/reviews" --paginate > /tmp/pr-reviews.json
gh api "repos/${REPO}/issues/${PR_NUMBER}/comments" --paginate > /tmp/issue-comments.json
gh api "repos/${REPO}/commits/$(git rev-parse HEAD)/check-runs" > /tmp/ci-checks.json
```

Parse with python3. Filter out comments already recorded in `.elves-session.json`. Categorize each remaining finding. Fix blockers. Resolve threads / reply to comments. Record dispositions. Push. Repeat.

## Fortifying the Review

The built-in review is the minimum viable loop. Users can strengthen it by:

- **Installing GitHub reviewer bots** (CodeRabbit, GitHub Copilot code review, SonarCloud, etc.): these produce detailed, automated reviews on every push that the subagent reads and acts on
- **Adding a custom review API** (configure in the survival guide under `## Tool Configuration`)
- **Adding smoke tests** (curl endpoints after preview deployment)
- **Adding visual review** (screenshot capture and inspection)
- **Adding verification scripts** (see `references/verification-patterns.md` for headless browser drivers, video recording, state assertions, and more)
- **Building their own review subagent** with domain-specific knowledge about their codebase

The more review infrastructure you add, the tighter each batch gets before the agent moves on. The built-in review ensures there is always *something* checking the work, even on a fresh project with no bots installed.

## Optional High-Risk Adversarial Lens

For a declared high-risk security, data-integrity, or public-contract surface, one fresh read-only
lens may supplement the cumulative review. It is not part of the normal trusted fast path.

The adversarial reviewer doesn't know what you were trying to do. It reads only the diff and the plan, then critiques from scratch. This catches a category of bugs that the primary review misses: cases where the implementation is internally consistent but doesn't match the requirements, or where the code "makes sense" only if you already know what the author intended.

To use this pattern, spawn a separate subagent after the primary review passes:

```
You are an adversarial code reviewer. You have not seen this code before.
Today's date is [DATE]. The codebase is the source of truth, not your training data. If the code uses libraries, model versions, or APIs you don't recognize, assume the coding agent has verified they are current.

Read:
1. The diff for PR #[NUMBER]
2. The commit history from the route start (`bN..HEAD` for host-native/legacy, `b0..HEAD` for a
   trusted full-run cumulative review); read full messages because the coding agent explains
   decisions there
3. The plan at [PLAN_PATH]
4. The batch contract in the execution log at [EXECUTION_LOG_PATH]

Your job is to find problems, verify the work matches the contract, and check code quality. Be skeptical. Assume nothing works until proven otherwise.

For each contract item: is it actually delivered, or does the code just look like it might be? Trace from the contract through the implementation to the test. If any link in that chain is missing, it's a finding.

For code quality: does this batch introduce duplicated utilities, ignore existing patterns, or band-aid over root causes? Does new code follow the codebase's conventions (naming, error handling, module structure)? Does this batch leave the repo easier or harder to work on?

For each finding, state:
- What's wrong
- Why it matters
- What the fix should be

Do not be polite. Do not pad with compliments. If the code is correct and the contract is fully delivered, say so in one line and stop.
```

Consolidate concrete blockers with the primary review. After revision, re-check only the changed
delta and unresolved blockers. Stop when exact-tip evidence is sufficient; the absence of further
suggestions is not a readiness condition.

This pattern is most valuable for security-sensitive code, data integrity logic, and anything where a subtle bug would be expensive. It adds time to each batch, so use it selectively.

## High-Risk Regression Review Pattern

Use this narrower pass when the batch contract's blast radius is **medium** or **high**, or when
the batch touches auth, billing, data models, shared utilities, public interfaces, or any surface
with many callers.

This is not a second full review. It is a focused regression check that asks only:

- What existing behavior could this break?
- Which callers, routes, jobs, or dependents would feel the break first?
- What proof do we have that those consumers still work?

Read only:

1. The cumulative diff for the branch or batch
2. The plan at `[PLAN_PATH]`
3. The batch contract in `[EXECUTION_LOG_PATH]`, especially **Acceptance criteria** and
   **Blast radius**
4. Any consumer evidence the implementer gathered (`rg` output, importer counts, route lists,
   interface snapshots, or targeted regression tests)
5. API surface snapshot artifacts when configured (`.elves/api-surface/baseline.json`,
   `.elves/api-surface/current.json`, and `.elves/api-surface/diff.md` by default)

Ignore:

- style or readability suggestions
- architecture cleanups unrelated to breakage
- new feature ideas
- docs freshness unless the stale doc itself would mislead an existing consumer

Return a tight report:

### Blocking
- [Confirmed regression or concrete breakage risk that is not yet proven safe]

### Warnings
- [Plausible regression risk that needs more proof, a targeted test, or an explicit safety note]

### Info
- [Changed shared surfaces that were traced and appear safe]

### Consumer Trace
- `[surface]` -> [callers/dependents checked] -> [why safe / what could break]

### Missing Proof
- [Any consumer or behavior that still needs direct verification]

If an API surface snapshot exists, treat it as shape evidence only. Public API surface snapshots
are optional regression evidence. Additive public contract changes are usually INFO, intentional
breaking changes require a plan or execution-log note, and unexpected breaking changes are
BLOCKING. A missing snapshot source is not blocking unless `required: true` was explicitly set in
the survival guide. A snapshot proves public surface shape only; it is not a substitute for tests,
E2E checks, review, or the human-owned constitution.

If nothing is risky, say so in one line and stop.

## Why This Matters

Without review, the agent is grading its own homework. The validate step (tests, lint, build) catches mechanical failures, but it doesn't catch logical errors, missing requirements, security issues, or code that compiles correctly but does the wrong thing.

The review step is the independent check. It's what makes the difference between an agent that produces output and an agent that produces *good* output. Every round through the review loop makes the batch tighter. By the time the human reviews the PR, the work has already been through multiple cycles of independent scrutiny.

This is the Ralph Loop in action: try, check, feed back, repeat. The review is the "check" that the loop depends on.
