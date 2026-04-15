# Kickoff Prompt Template

> Elves works best as a two-call handoff:
>
> 1. **Stage the run**
> 2. **Launch the run**
>
> Most "the elves stopped" failures come from combining a giant plan and the launch instructions
> into one overloaded message. The plan already lives on disk. The launch prompt should stay short.
>
> Think of staging as winding the spring: clean the docs, line up the branch and PR, run
> preflight, and stop only when the runway is clear. Then use a fresh launch call to start the
> unattended run with momentum.
>
> **The Daily Briefing.** Block time at the end of your workday (even 30 minutes) to brief your
> agents. Friday afternoons deserve more deliberate treatment: the weekend is roughly 60 hours of
> potential agent runtime. A two-hour planning session on Friday can produce a week's worth of
> output before Monday morning.

---

## Step 1: Stage Template

> Use this first. The goal is to get everything lined up and then stop. Do not let the agent start
> implementation in the same call that is still cleaning up the plan or initializing the run.

```
Stage this Elves run. Do not start implementing the batches in this call.

**Plan:** [path/to/plan.md]
**Branch:** [feat/branch-name]
**Survival guide:** [path/to/survival-guide.md]  (or: "generate from template")
**Learnings:** [path/to/learnings.md]            (or: "generate from template")
**Execution log:** [path/to/execution-log.md]    (or: "generate from template")

**Your job in this call:**
- Tighten the plan if needed so it can survive compaction without the conversation
- Generate or refresh the survival guide, learnings file, and execution log
- Set `## Run Control` explicitly, including run mode, checkpoint semantics, may-continue-after-checkpoint, actual stop conditions, and `Active Compute` if relevant
- Create or switch to the branch, open or update the PR, and record the PR number
- Run preflight and log any warnings or blockers
- Record any durable-doc paths the run should use (`.ai-docs/*`) if the repo keeps them
- Prepare a short launch prompt for the next call

**Non-negotiables:**
- [Hard rule 1]
- [Hard rule 2]
- [Hard rule 3]

**Stop condition for this call:**
- Stop only after the run is launch-ready and you have handed me the launch prompt for the next call
```

**Example:**

```
Stage this Elves run. Do not start implementing the batches in this call.

**Plan:** docs/plans/auth-refactor.md
**Branch:** feat/jwt-auth
**Survival guide:** docs/elves/survival-guide.md  (generate from template if missing)
**Learnings:** docs/elves/learnings.md            (generate from template if missing)
**Execution log:** docs/elves/execution-log.md    (generate from template if missing)

**Your job in this call:**
- Tighten the plan if needed so it can survive compaction without the conversation
- Generate or refresh the survival guide, learnings file, and execution log
- Set `## Run Control` explicitly, including run mode, checkpoint semantics, may-continue-after-checkpoint, actual stop conditions, and `Active Compute` if relevant
- Create or switch to the branch, open or update the PR, and record the PR number
- Run preflight and log any warnings or blockers
- Record any durable-doc paths the run should use (`.ai-docs/*`) if the repo keeps them
- Prepare a short launch prompt for the next call

**Non-negotiables:**
- Never modify public /api/* response shapes
- All commits must pass lint and typecheck before push
- Do not touch the OAuth routes or password reset flow
- You never merge. The PR is for me to review.

**Stop condition for this call:**
- Stop only after the run is launch-ready and you have handed me the launch prompt for the next call
```

---

## Step 2: Hard Launch Template

> Use this in a fresh call after staging is done. Keep it short. The plan already carries the
> project detail; the launch prompt should reinforce behavior and momentum.

```
The run is staged. Start now.
Read [path/to/survival-guide.md] first, then `.elves-session.json` if it exists, then [path/to/learnings.md] if it exists, then [path/to/plan.md], then the execution log at [path/to/execution-log.md], then `.ai-docs/manifest.md` if it exists.
I am going offline until [WHEN].
By [WHEN], I want [CHECKPOINT DELIVERABLE]. This is a [delivery checkpoint / hard stop].
Do not stop unless you hit a genuine blocker with no reasonable workaround.
Do not be lazy. Work as hard as you can for the entire run.
Do not coast after the first success, first green check, or first useful checkpoint. Push each batch to a thoroughly verified state, then continue immediately.
Every completed batch must end with a commit and push before you start anything else.
Immediately after every commit and push, re-read the survival guide before any other action.
If this is a delivery checkpoint, log it, push it, and continue immediately. Do not stop at the checkpoint.
Do not wait for me to acknowledge checkpoints, summaries, or clean commits. If work remains, keep going.
Do not send a final response unless the survival guide Stop Gate says stopping is allowed or a true blocker forces it.
Use your judgment. Work in small batches and commit frequently.
Make the commit subjects read like progress reports.
Run every relevant validation gate, including E2E or browser checks wherever they make sense.
After every push, read PR comments and checks, fix blockers, and re-check for regressions against earlier verified work.
If the run uses paid compute, remote jobs, or long-lived servers, keep the survival guide's `Active Compute` section current after every push and topology change.
Keep going until the plan is done, I stop you, or you hit a true blocker.
```

**Example:**

```
The run is staged. Start now.
Read docs/elves/survival-guide.md first, then `.elves-session.json` if it exists, then docs/elves/learnings.md if it exists, then docs/plans/auth-refactor.md, then the execution log at docs/elves/execution-log.md, then `.ai-docs/manifest.md` if it exists.
I am going offline until 7:30am ET.
By 7:30am ET, I want a review-ready checkpoint with green local validation. This is a delivery checkpoint, not a stop boundary.
Do not stop unless you hit a genuine blocker with no reasonable workaround.
Do not be lazy. Work as hard as you can for the entire run.
Do not coast after the first success, first green check, or first useful checkpoint. Push each batch to a thoroughly verified state, then continue immediately.
Every completed batch must end with a commit and push before you start anything else.
Immediately after every commit and push, re-read the survival guide before any other action.
This checkpoint is for delivery only. Log it, push it, and continue immediately. Do not stop at 7:30am ET.
Do not wait for me to acknowledge checkpoints, summaries, or clean commits. If work remains, keep going.
Do not send a final response unless the survival guide Stop Gate says stopping is allowed or a true blocker forces it.
Use your judgment. Work in small batches and commit frequently.
Make the commit subjects read like progress reports.
Run every relevant validation gate, including E2E or browser checks wherever they make sense.
After every push, read PR comments and checks, fix blockers, and re-check for regressions against earlier verified work.
If the run uses paid compute, remote jobs, or long-lived servers, keep the survival guide's `Active Compute` section current after every push and topology change.
Keep going until the plan is done, I stop you, or you hit a true blocker.
```

---

## Tips

**Stage and launch in separate calls**
The split is the point. Staging should absorb plan cleanup and setup churn. Launch should begin
with a short, behavior-heavy prompt.

**If you only send one message, the agent should stage first**
If you paste a large plan and also say "run now," the agent should treat that message as a staging
request, not a launch request.

**The agent should push back explicitly**
When the prompt is overloaded, the agent should say some version of: "Hang on, we need to get
this right. I'm going to stage the run and wait for your final launch command."

**Don't repeat the whole plan in the launch prompt**
Point to the plan by path. If the launch prompt starts looking like a second plan file, it is too
long.

**Point to durable memory too**
If the run uses a learnings file or `.ai-docs`, include those paths in the launch prompt so the
agent rehydrates from durable knowledge instead of rediscovering it.

**State checkpoint semantics explicitly**
Don't make the agent guess whether "8am" is a delivery checkpoint or a hard stop. Say which it is.

**Call out paid compute**
If pods, remote jobs, or long-lived servers are involved, tell the agent and require `Active
Compute` updates in the survival guide.

**Make the launch prompt behavior-heavy**
The launch prompt should remind the agent how to behave: don't stop, use judgment, work in small
batches, commit frequently, validate aggressively, review PR feedback, and watch for regressions.

**Check in with `ra:`**
You don't have to disappear completely. If you want to give context or change priorities during
the run, prefix your message with `ra:`. `ride-along:` and `[ride-along]` also work. The agent
will respond briefly and keep going without stopping.

**Friday staging is leverage**
Use Friday afternoon to build a clear plan, stage the run, and make sure preflight is green. Then
launch in a clean second call and let the agent work through the weekend.
