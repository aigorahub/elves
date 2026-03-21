# Built-in Review Subagent

This is the default review mechanism for Elves. It works out of the box with zero configuration. All it needs is `gh` CLI auth and an open PR.

## What It Does

After each batch, the coordinator spawns this subagent to perform an independent review. The subagent:

1. Reads all PR comments, review threads, and CI status via `gh api`
2. Reads the diff for the current batch
3. Reads the plan to understand what the batch was supposed to accomplish
4. Produces a structured assessment: what's blocking, what's a warning, what's fine

The coordinator then acts on the findings. It fixes blockers, logs decisions, pushes fixes. New pushes trigger new bot reviews. The coordinator runs the review subagent again. This loop continues until the batch is clean.

## How to Invoke

The coordinator spawns this review with a prompt like:

```
Review the current state of PR #[NUMBER] for repo [OWNER/REPO].

Read:
1. All PR comments: gh api "repos/OWNER/REPO/pulls/NUMBER/comments" --paginate
2. All review threads: gh api "repos/OWNER/REPO/pulls/NUMBER/reviews" --paginate
3. All issue comments: gh api "repos/OWNER/REPO/issues/NUMBER/comments" --paginate
4. CI check status: gh api "repos/OWNER/REPO/commits/HEAD/check-runs"

For each comment or finding:
- Categorize as: BLOCKING (must fix), WARNING (should fix), INFO (note only)
- Identify the source: human reviewer, bot (name which bot), CI check
- Summarize what the issue is and what file/line it references
- If it's a duplicate of a previous finding, note that

Also review the diff yourself against the plan at [PLAN_PATH]:
- Is the batch scope fully implemented?
- Are there obvious bugs, security issues, or missing error handling?
- Are there any changes outside the batch scope that shouldn't be there?

Return a structured report:
## Blocking (must fix before moving on)
- [finding]

## Warnings (fix if easy, defer if complex)
- [finding]

## Info (no action needed)
- [finding]

## Completeness vs Plan
- [assessment of whether the batch is fully implemented]

## New Issues Found in Diff Review
- [anything you spotted that the bots didn't]
```

## What the Coordinator Does With the Report

1. **Blocking items**: Fix each one. This is non-negotiable.
2. **Warnings**: Fix easy ones inline. Defer complex ones to TODO.md tagged `[elves-scout]`.
3. **Info**: Log in execution log, no action.
4. **Completeness gaps**: Go back to the Implement step and finish what's missing.
5. **New issues**: Treat as blocking if they're bugs or security; treat as warnings otherwise.

After fixing, the coordinator pushes and runs the review subagent again. The loop repeats until the report comes back with zero blocking items and the completeness check passes.

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

Read the diff for PR #[NUMBER] and the plan at [PLAN_PATH].

Your job is to find problems. Be skeptical. Assume nothing works until proven otherwise.

For each finding, state:
- What's wrong
- Why it matters
- What the fix should be

Do not be polite. Do not pad with compliments. If the code is correct, say so in one line and stop.
```

The coordinator fixes any blocking findings from the adversarial review, then runs it again. The loop continues until the adversarial reviewer has nothing left to find.

This pattern is most valuable for security-sensitive code, data integrity logic, and anything where a subtle bug would be expensive. It adds time to each batch, so use it selectively.

## Why This Matters

Without review, the agent is grading its own homework. The validate step (tests, lint, build) catches mechanical failures, but it doesn't catch logical errors, missing requirements, security issues, or code that compiles correctly but does the wrong thing.

The review step is the independent check. It's what makes the difference between an agent that produces output and an agent that produces *good* output. Every round through the review loop makes the batch tighter. By the time the human reviews the PR, the work has already been through multiple cycles of independent scrutiny.

This is the Ralph Loop in action: try, check, feed back, repeat. The review is the "check" that the loop depends on.
