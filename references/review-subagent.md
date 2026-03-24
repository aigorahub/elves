# Built-in Review Subagent

This is the default review mechanism for Elves. It works out of the box with zero configuration. All it needs is `gh` CLI auth and an open PR.

## What It Does

After each batch, the coordinator spawns this subagent to perform an independent review. The subagent:

1. Reads all PR comments, review threads, and CI status via `gh api`
2. Reads the diff for the current batch
3. Reads the plan to understand the broader goal
4. **Reads the batch contract** (from the execution log) to know exactly what was supposed to be delivered — specific behaviors and testable acceptance criteria
5. **Evaluates code quality** against the Code Quality Philosophy (see SKILL.md)
6. Produces a structured assessment: what's blocking, what's a warning, what's fine, whether every contract item was delivered, and whether the code leaves the repo in better shape

The reviewer has three jobs: find bugs, verify the contract, and enforce code quality. A bug-free batch that only implements half its contract is incomplete. A fully-implemented batch with a security hole needs fixing. A batch that works perfectly but introduces duplicated utilities, ignores existing patterns, or band-aids over root causes makes every future batch harder — that's blocking too.

The coordinator then acts on the findings. It fixes blockers, finishes missing contract items, logs decisions, pushes fixes. New pushes trigger new bot reviews. The coordinator runs the review subagent again. This loop continues until the batch is clean and the contract is fully delivered.

## How to Invoke

The coordinator spawns this review with a prompt like:

```
Review the current state of PR #[NUMBER] for repo [OWNER/REPO].

## What to read

1. All PR review threads (focus on **unresolved** threads — resolved threads have already been addressed)
2. All issue comments (focus on comments **without a reply from the agent** — replied comments have been addressed)
3. CI check status: gh api "repos/OWNER/REPO/commits/HEAD/check-runs"
4. The plan at [PLAN_PATH]
5. The batch contract in the execution log at [EXECUTION_LOG_PATH] under the current batch heading
6. The `review_comments` array in [SESSION_JSON_PATH] to see what was already handled in previous cycles

```bash
# Fetch review threads — filter for unresolved
gh api "repos/OWNER/REPO/pulls/NUMBER/comments" --paginate
gh api "repos/OWNER/REPO/pulls/NUMBER/reviews" --paginate
# Fetch issue comments — check which have agent replies
gh api "repos/OWNER/REPO/issues/NUMBER/comments" --paginate
# CI status
gh api "repos/OWNER/REPO/commits/HEAD/check-runs"
```

**Skip comments already recorded as handled in `.elves-session.json`.** Only evaluate new and unresolved findings. This prevents re-litigating settled issues across review cycles.

## For each NEW or UNRESOLVED comment or finding:
- Categorize as: BLOCKING (must fix), WARNING (should fix), INFO (note only)
- Identify the source: human reviewer, bot (name which bot), CI check
- Summarize what the issue is and what file/line it references
- Note the comment ID so the coordinator can resolve/reply to it after fixing

## Contract verification (this is as important as bug-finding):

Read the batch contract carefully. For EACH behavior listed in the contract:
- Is it implemented in the diff? Show the evidence (file, function, or route).
- Is it tested? Point to the specific test.
- If missing or partially implemented, mark it BLOCKING.

For EACH acceptance criterion:
- Can it be verified from the diff and test results?
- If a criterion has no corresponding test or verification, mark it BLOCKING.

## Code quality review (the Code Quality Philosophy):

The goal is that each batch leaves the codebase easier to work on, not harder. For each of these, check the diff:

1. **Root cause over band-aids:** Are fixes addressing the actual problem, or patching symptoms? Look for: try/catch blocks that swallow errors, special-case conditionals that work around deeper issues, "retry and hope" patterns.
2. **Centralize over duplicate:** Did the batch introduce new helpers, utilities, or abstractions that duplicate existing ones in the codebase? Search for similar functions. If `formatDate()` already exists in the codebase and the batch added a new one, that's a finding.
3. **Extend over create:** Did the batch build on existing patterns and modules, or create parallel implementations? New files that replicate the structure of existing files are a red flag.
4. **Architecture first:** Does the new code respect the codebase's existing architecture — module boundaries, data flow, naming conventions, test organization? Or does it introduce novel patterns that conflict with what's already there?
5. **Pattern consistency:** Does the new code follow the naming conventions, error handling patterns, and API response structures already established in the codebase?
6. **Progressive conditioning:** Does this batch leave the repo easier to work on? Look for: clear type annotations on new code, focused single-purpose functions, consistent naming, updated docs and agent instructions (CLAUDE.md, TODO.md).
7. **Thrashing signals:** Were the same files modified 5+ times in the batch's commit history without clear forward progress? This suggests symptom-chasing rather than root-cause fixing.

Mark code quality issues as:
- BLOCKING if they introduce duplication, violate existing architecture, or band-aid a root cause
- WARNING if they miss an opportunity to improve (e.g., could have added types, could have consolidated)

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

### Contract Completeness
For each contract item, one line:
- ✅ [item] — implemented in [file], tested in [test]
- ❌ [item] — [what's missing]
- ⚠️ [item] — implemented but [concern]

### Code Quality
- **Duplication:** [any new code that duplicates existing utilities/patterns — name both]
- **Architecture:** [any violations of existing module boundaries, data flow, or conventions]
- **Root cause:** [any fixes that patch symptoms rather than addressing underlying problems]
- **Pattern consistency:** [any deviations from established naming, error handling, or structure]
- **Progressive conditioning:** [did this batch leave the repo easier or harder to work on?]
If all clear, state: "No code quality issues. Batch follows existing patterns and conventions."

### New Issues Found in Diff Review
- [anything you spotted that the bots didn't]
```

## What the Coordinator Does With the Report

1. **Blocking items**: Fix each one. This is non-negotiable.
2. **Contract items marked ❌**: Go back to Implement (step 5) and finish what's missing. These are blocking — an incomplete contract means an incomplete batch.
3. **Contract items marked ⚠️**: Evaluate the concern. Fix if it's a real gap; log if it's a judgment call.
4. **Code quality findings**: Duplication and architecture violations are blocking — fix them now, not later. Remove the duplicate and use the existing utility. Refactor to follow the established pattern. Root-cause band-aids are blocking if they hide a bug, warning if they're just suboptimal. Pattern consistency issues are warnings.
5. **Warnings**: Fix easy ones inline. Defer complex ones to TODO.md tagged `[elves-scout]`.
6. **Info**: Log in execution log, no action.
7. **New issues**: Treat as blocking if they're bugs or security; treat as warnings otherwise.

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

**Record every disposition** in `.elves-session.json` under `review_comments` with: comment ID, type (`review_thread` or `issue_comment`), source (which bot or reviewer), batch number, review cycle, one-line summary, disposition (`fixed`, `dismissed`, `deferred`), and fix commit or reason.

### The Work Queue

After resolution, the work queue for the next review cycle is simply:
- Unresolved review threads (GitHub is the source of truth)
- Issue comments with no reply from the agent
- New comments triggered by the latest push

If the queue is empty and the contract is fully ✅, the batch is clean.

After fixing, the coordinator pushes and runs the review subagent again. The loop repeats until the report comes back with zero blocking items, every contract item is ✅, and the work queue is empty.

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

## Adversarial Review Pattern

For higher confidence, spawn a second review subagent that has no context from the implementation. This is the "fresh eyes" pattern used internally at Anthropic.

The adversarial reviewer doesn't know what you were trying to do. It reads only the diff and the plan, then critiques from scratch. This catches a category of bugs that the primary review misses: cases where the implementation is internally consistent but doesn't match the requirements, or where the code "makes sense" only if you already know what the author intended.

To use this pattern, spawn a separate subagent after the primary review passes:

```
You are an adversarial code reviewer. You have not seen this code before.

Read:
1. The diff for PR #[NUMBER]
2. The plan at [PLAN_PATH]
3. The batch contract in the execution log at [EXECUTION_LOG_PATH]

Your job is to find problems, verify the work matches the contract, and check code quality. Be skeptical. Assume nothing works until proven otherwise.

For each contract item: is it actually delivered, or does the code just look like it might be? Trace from the contract through the implementation to the test. If any link in that chain is missing, it's a finding.

For code quality: does this batch introduce duplicated utilities, ignore existing patterns, or band-aid over root causes? Does new code follow the codebase's conventions (naming, error handling, module structure)? Does this batch leave the repo easier or harder to work on?

For each finding, state:
- What's wrong
- Why it matters
- What the fix should be

Do not be polite. Do not pad with compliments. If the code is correct and the contract is fully delivered, say so in one line and stop.
```

The coordinator fixes any blocking findings from the adversarial review, then runs it again. The loop continues until the adversarial reviewer has nothing left to find.

This pattern is most valuable for security-sensitive code, data integrity logic, and anything where a subtle bug would be expensive. It adds time to each batch, so use it selectively.

## Why This Matters

Without review, the agent is grading its own homework. The validate step (tests, lint, build) catches mechanical failures, but it doesn't catch logical errors, missing requirements, security issues, or code that compiles correctly but does the wrong thing.

The review step is the independent check. It's what makes the difference between an agent that produces output and an agent that produces *good* output. Every round through the review loop makes the batch tighter. By the time the human reviews the PR, the work has already been through multiple cycles of independent scrutiny.

This is the Ralph Loop in action: try, check, feed back, repeat. The review is the "check" that the loop depends on.
