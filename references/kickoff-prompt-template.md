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
**Execution log:** [path/to/execution-log.md]    (or: "generate from template")

**Your job in this call:**
- Tighten the plan if needed so it can survive compaction without the conversation
- Generate or refresh the survival guide and execution log
- Create or switch to the branch, open or update the PR, and record the PR number
- Run preflight and log any warnings or blockers
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
**Execution log:** docs/elves/execution-log.md    (generate from template if missing)

**Your job in this call:**
- Tighten the plan if needed so it can survive compaction without the conversation
- Generate or refresh the survival guide and execution log
- Create or switch to the branch, open or update the PR, and record the PR number
- Run preflight and log any warnings or blockers
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
Read [path/to/survival-guide.md] first, then `.elves-session.json` if it exists, then [path/to/plan.md], then [path/to/execution-log.md].
I am going offline until [WHEN].
Do not stop unless you hit a genuine blocker with no reasonable workaround.
Use your judgment. Work in small batches and commit frequently.
Make the commit subjects read like progress reports.
Run every relevant validation gate, including E2E or browser checks wherever they make sense.
After every push, read PR comments and checks, fix blockers, and re-check for regressions against earlier verified work.
Keep going until the plan is done, I stop you, or you hit a true blocker.
```

**Example:**

```
The run is staged. Start now.
Read docs/elves/survival-guide.md first, then `.elves-session.json` if it exists, then docs/plans/auth-refactor.md, then docs/elves/execution-log.md.
I am going offline until 7:30am ET.
Do not stop unless you hit a genuine blocker with no reasonable workaround.
Use your judgment. Work in small batches and commit frequently.
Make the commit subjects read like progress reports.
Run every relevant validation gate, including E2E or browser checks wherever they make sense.
After every push, read PR comments and checks, fix blockers, and re-check for regressions against earlier verified work.
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
