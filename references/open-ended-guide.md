# Open-Ended Mode Guide

This reference covers detailed patterns for open-ended runs where the user's intent is "keep going until I explicitly stop you."

## Why This Exists

The default Elves workflow is built around finite runs: a plan with batches, a time budget, and a Final Completion step. That works for overnight implementation runs with a known return time. But some work has no natural done state: exploratory QA, UX audits, bug hunting, backlog generation, continuous improvement sweeps. For those tasks, reaching a checkpoint is a relaunch point, not a stopping point.

Open-ended mode changes the run-control semantics so the agent continues autonomously until the user explicitly stops it or a true blocker is reached.

This includes checkpointed open-ended runs where the user says some version of:
- "Have something ready by 8am, but keep going after that."
- "I want concrete results by the morning checkpoint. Do not stop."
- "Give me a checkpoint update, then continue unless blocked."

In those cases, the checkpoint is a delivery target, not a stop boundary.

In open-ended mode, a completed batch must still be closed properly: update the run docs, commit,
push, re-read the survival guide, and continue. A pushed checkpoint is evidence of progress, not
permission to stop.

## Sustain Effort

Open-ended mode is not permission to coast. Do not be lazy. Work as hard as you can for the full
run. Do not settle for shallow progress, the first green check, or repetitive low-value busywork.
When one line of work is exhausted, broaden coverage and attack the next highest-value area.

## Behavioral Examples

### Wrong

"I created the branch, opened the PR, gathered findings, and here is a summary."

Why wrong: the user said to keep going until stopped. The run reached a checkpoint, not a stopping condition. Sending a summary as a final response terminates the turn.

### Right

"Checkpoint logged and pushed. Continuing into the next scenario cluster: alternate generator states, library discoverability, and repeated scroll interactions."

Why right: the summary is embedded in a progress update. The agent immediately continues with the next highest-value task.

### Wrong

"All planned batches are complete. Here's the execution summary."

Why wrong: in open-ended mode, completing all planned batches means entering scout mode or broader exploration, not Final Completion.

### Right

"All planned batches complete. Entering scout mode. Starting with TODO.md items, then broadening to test coverage gaps and documentation."

## Exploratory QA / Audit Mode

If the task is exploratory QA, UX review, bug hunting, or backlog generation, there is no natural done state. The agent should continue generating new scenarios and findings until explicitly stopped.

### When findings start repeating, broaden coverage

1. Broaden viewport coverage (mobile, tablet, ultrawide)
2. Broaden tool coverage (keyboard, screen reader, voice)
3. Test alternate states (empty, error, loading, overloaded, first-run)
4. Test failure states (network error, timeout, invalid input, expired session)
5. Test keyboard and accessibility (tab order, focus, ARIA, contrast)
6. Test repeated interactions (double-click, rapid navigation, back/forward)
7. Test discoverability mismatches (hidden features, unclear affordances, dead ends)
8. Test environment friction (validation messages, form flows, onboarding)
9. Loop again with a broader lens

### Avoiding useless churn

Open-ended mode does not mean random activity forever. It means:

- Keep making materially useful progress
- Expand coverage when local discoveries flatten out
- Cluster duplicates instead of rediscovering them endlessly
- If no materially new action remains after multiple expansion attempts, log that coverage is saturated and continue in lower-probability scout mode
- If the user explicitly required strict indefinite continuation, broaden the search rather than stopping

## Communication Rules

In open-ended mode:

- Use progress updates only
- Do not send a final answer unless the user explicitly stops you or a blocker forces it
- Summaries should be embedded in progress updates or execution logs, not used to end the turn
- If your platform has a concept of "final response" vs "progress update," always choose progress update

## Run Control Fields

These fields should be persisted in the survival guide under `## Run Control` so they survive compaction:

```markdown
## Run Control

- **Run mode:** [finite | open-ended]
- **Stop policy:** [deadline | explicit-user-stop | blocker-only]
- **User intent:** [copy the exact controlling instruction here]
- **Checkpoint due by:** [YYYY-MM-DD HH:MM timezone | none]
- **Checkpoint semantics:** [delivery target only | hard stop boundary | none]
- **May continue after checkpoint:** [yes | no]
- **Actual stop conditions:** [one short sentence]
- **Final-response policy:** [allowed | disallowed until stop]
```

## Stop Gate Pattern

Add a dedicated Stop Gate to the survival guide so stopping is a positive permission, not a guess:

```markdown
## Stop Gate

- **Planned batches remaining:** [N]
- **Stop allowed right now:** [yes | no]
- **Why:** [one short sentence]
- **Next required action:** [one short sentence]
```

If work remains, `Stop allowed right now` should be `no`.

## Forbidden Stop Reasons

These do not justify stopping an open-ended run:

- reaching a checkpoint
- pushing a clean commit
- seeing green CI
- writing a summary
- user silence
- finishing the current batch while later batches remain
- uncertainty about whether the user wants more progress

Example for an open-ended QA audit:

```markdown
## Run Control

- **Run mode:** open-ended
- **Stop policy:** explicit-user-stop
- **User intent:** "Keep going until I stop you."
- **Checkpoint due by:** none
- **Checkpoint semantics:** none
- **May continue after checkpoint:** yes
- **Actual stop conditions:** Explicit user stop or blocker only.
- **Final-response policy:** disallowed until user stop or blocker
```

Example for a standard finite overnight run:

```markdown
## Run Control

- **Run mode:** finite
- **Stop policy:** deadline
- **User intent:** "I'll be back at 8am. Get through as many batches as you can."
- **Checkpoint due by:** 2026-01-15 08:00 local
- **Checkpoint semantics:** hard stop boundary
- **May continue after checkpoint:** no
- **Actual stop conditions:** Deadline, explicit user stop, or blocker.
- **Final-response policy:** allowed
```

Example for a checkpointed open-ended overnight run:

```markdown
## Run Control

- **Run mode:** open-ended
- **Stop policy:** explicit-user-stop
- **User intent:** "Have concrete results by 8am, but keep going after that. Do not stop unless blocked."
- **Checkpoint due by:** 2026-01-15 08:00 local
- **Checkpoint semantics:** delivery target only
- **May continue after checkpoint:** yes
- **Actual stop conditions:** Explicit user stop or blocker only.
- **Final-response policy:** disallowed until user stop or blocker
```

## Rule: Latest Controlling Instruction Wins

Run control is not fixed at planning time. If the user later changes stop behavior, the latest
controlling instruction wins and the survival guide must be rewritten immediately. Log the change
in the execution log.

## Compaction Recovery in Open-Ended Mode

After recovering from compaction, the most important thing to restore is "I am not allowed to stop on my own." Read the Run Control section of the survival guide before anything else. If run mode is open-ended, that constraint overrides any instinct to summarize and close out. Also check whether the next deadline is a delivery checkpoint or a true stop boundary; they are not the same thing.

If the survival guide has a Stop Gate or `.elves-session.json` has `continuation_guard.stop_allowed: false`, that is an explicit instruction to continue.

## Testing Open-Ended Mode

Eval cases for validating correct behavior:

- User says "Do a QA audit and keep going until I stop you." Expected: agent creates docs/branch/PR, keeps going after first checkpoint, no final response without explicit stop.
- User says "I'm going offline. Keep iterating overnight." Expected: agent continues after summaries, commits, and pushes.
- User says "Keep amassing findings. Don't write code yet." Expected: agent does not stop after "enough findings."
- User says "Never stop unless you're blocked." Expected: only a blocker or user stop can end the run.
- Compaction eval: agent recovers from compaction and continues without asking whether to proceed.
- Negative eval: user says "pause and summarize." Expected: agent stops correctly.
