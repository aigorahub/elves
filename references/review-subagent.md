# Built-in Review Subagent

This is the default review mechanism for Elves. It works out of the box with zero configuration. All it needs is `gh` CLI auth and an open PR.

## What It Does

After each batch, the coordinator spawns this subagent to perform an independent review. The subagent:

1. Reads all PR comments, review threads, and CI status via `gh api`
2. Reads the diff for the current batch
3. Reads the plan to understand the broader goal
4. **Reads the batch contract** (from the execution log) to know exactly what was supposed to be delivered — specific behaviors and testable acceptance criteria
5. Produces a structured assessment: what's blocking, what's a warning, what's fine, and whether every contract item was delivered

The reviewer doesn't just look for errors. It verifies the work matches the batch that was supposed to be done. A bug-free batch that only implements half its contract is incomplete. A fully-implemented batch with a security hole needs fixing. Both checks must pass.

The coordinator then acts on the findings. It fixes blockers, finishes missing contract items, logs decisions, pushes fixes. New pushes trigger new bot reviews. The coordinator runs the review subagent again. This loop continues until the batch is clean and the contract is fully delivered.

## How to Invoke

The coordinator spawns this review with a prompt like:

```
Review the current state of PR #[NUMBER] for repo [OWNER/REPO].

## What to read

1. All PR comments: gh api "repos/OWNER/REPO/pulls/NUMBER/comments" --paginate
2. All review threads: gh api "repos/OWNER/REPO/pulls/NUMBER/reviews" --paginate
3. All issue comments: gh api "repos/OWNER/REPO/issues/NUMBER/comments" --paginate
4. CI check status: gh api "repos/OWNER/REPO/commits/HEAD/check-runs"
5. The plan at [PLAN_PATH]
6. The batch contract in the execution log at [EXECUTION_LOG_PATH] under the current batch heading

## For each PR comment or finding:
- Categorize as: BLOCKING (must fix), WARNING (should fix), INFO (note only)
- Identify the source: human reviewer, bot (name which bot), CI check
- Summarize what the issue is and what file/line it references
- If it's a duplicate of a previous finding, note that

## Contract verification (this is as important as bug-finding):

Read the batch contract carefully. For EACH behavior listed in the contract:
- Is it implemented in the diff? Show the evidence (file, function, or route).
- Is it tested? Point to the specific test.
- If missing or partially implemented, mark it BLOCKING.

For EACH acceptance criterion:
- Can it be verified from the diff and test results?
- If a criterion has no corresponding test or verification, mark it BLOCKING.

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

### New Issues Found in Diff Review
- [anything you spotted that the bots didn't]
```

## What the Coordinator Does With the Report

1. **Blocking items**: Fix each one. This is non-negotiable.
2. **Contract items marked ❌**: Go back to Implement (step 5) and finish what's missing. These are blocking — an incomplete contract means an incomplete batch.
3. **Contract items marked ⚠️**: Evaluate the concern. Fix if it's a real gap; log if it's a judgment call.
4. **Warnings**: Fix easy ones inline. Defer complex ones to TODO.md tagged `[elves-scout]`.
5. **Info**: Log in execution log, no action.
6. **New issues**: Treat as blocking if they're bugs or security; treat as warnings otherwise.

After fixing, the coordinator pushes and runs the review subagent again. The loop repeats until the report comes back with zero blocking items and every contract item is ✅.

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

Parse with python3. Categorize each finding. Fix blockers. Push. Repeat.

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

Your job is to find problems AND verify the work matches the contract. Be skeptical. Assume nothing works until proven otherwise.

For each contract item: is it actually delivered, or does the code just look like it might be? Trace from the contract through the implementation to the test. If any link in that chain is missing, it's a finding.

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
