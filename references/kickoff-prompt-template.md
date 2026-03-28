# Kickoff Prompt Template

> This is the message you paste into Claude Code, Codex, or your AI coding agent to start an
> Elves run. Copy one of the templates below, fill in the brackets, and send it before you go
> offline.
>
> The agent will read your plan, generate the survival guide and execution log if they don't
> exist, run preflight checks, and start executing immediately.
>
> **The Daily Briefing.** Block time at the end of your workday (even 30 minutes) to brief
> your agents. Load them with enough well-defined work to keep them running through the night.
> Friday afternoons deserve more deliberate treatment: the weekend is roughly 60 hours of
> potential agent runtime. A two-hour planning session on Friday can produce a week's worth of
> output before Monday morning.

---

## Minimal Template

> Use this when your plan is self-contained and you don't have special instructions.
> 3–5 lines is enough.

```
I'm going offline for [N hours / until ~HH:MM timezone].
Run the plan at [path/to/plan.md] on branch [branch-name].
Non-negotiables: [your top 1–2 rules, or "see the plan"].
```

**Example:**

```
I'm going offline until 8am ET tomorrow.
Run the plan at docs/plans/auth-refactor.md on branch feat/jwt-auth.
Non-negotiables: don't touch the OAuth routes, don't modify public API response shapes.
```

---

## Full Template

> Use this when you want to be explicit about paths, rules, and any edge cases the agent
> should know before you walk away.

```
I'm going offline [until WHEN / for HOW LONG]. Please run the plan autonomously.

**Plan:** [path/to/plan.md]
**Branch:** [feat/branch-name]
**Survival guide:** [path/to/survival-guide.md]  (or: "generate from template")
**Execution log:** [path/to/execution-log.md]    (or: "generate from template")

**Non-negotiables:**
- [Hard rule 1]
- [Hard rule 2]
- [Hard rule 3]

**Special instructions:**
- [Anything the agent should know that isn't in the plan. Environment quirks, known issues,
  things to watch for, preferred approaches]
- [E.g., "Redis might be slow to start. Give it 10 seconds before running integration tests."]
- [E.g., "The PR already exists at #42. Don't create a new one."]
- [E.g., "If Batch 3 turns out to be too risky, stop after Batch 2 and note it in the log"]

**When I return I expect to see:**
- [What a successful run looks like to you. E.g., "All batches complete, tests passing, ready for my review."]
```

**Example (filled in):**

```
I'm going offline until 7:30am ET. Please run the plan autonomously.

**Plan:** docs/plans/auth-refactor.md
**Branch:** feat/jwt-auth
**Survival guide:** docs/elves/survival-guide.md  (generate from template if missing)
**Execution log:** docs/elves/execution-log.md    (generate from template if missing)

**Non-negotiables:**
- Never modify public /api/* response shapes
- All commits must pass lint and typecheck before push
- Do not touch the OAuth routes or password reset flow
- You never merge. The PR is for me to review.

**Special instructions:**
- Redis can be slow to spin up in the test environment. If integration tests fail on
  first run, wait 10 seconds and retry once before marking as failed
- The PR already exists at #84. Don't create a new one.
- If you finish all 3 batches with time to spare, do a scout pass on the files you touched
  and look for missing test coverage

**When I return I expect to see:**
- PR #84 updated with all 3 batches committed
- All 142 auth tests passing
- Execution log showing timing for each batch and any decisions made
```

---

## Tips for Writing a Good Kickoff

**Be specific about "when you return"**
The agent uses this to pace work. "Tomorrow morning" is less useful than "8am ET Wednesday".
If you don't specify, the agent assumes an 8-hour window.

**Non-negotiables belong in the plan AND the prompt**
The plan is the source of truth, but repeating the most critical rules in the prompt ensures
the agent captures them before it starts reading files.

**Mention the existing PR if there is one**
If a PR already exists on the branch, tell the agent so it doesn't create a duplicate.

**Tell the agent what to do if it finishes early**
Without guidance, it enters scout mode by default (looking for adjacent improvements).
If you want it to stop after the plan is done, say so.

**Tell the agent what to do if it gets stuck**
The default behavior is to stop with a detailed blocker description in the execution log.
If you want it to skip a batch and try the next one, say so.

**Check in with `ra:`**
You don't have to leave. If you want to check in, give context, or adjust priorities during
the run, prefix your message with `ra:`. `ride-along:` and `[ride-along]` also work. The
agent will respond in 1-3 sentences and keep going without stopping. Think of it as a
walkie-talkie: press the button, say your piece, release. Examples: `ra: the auth tests
are flaky, ignore them.` or `ra: skip batch 4, do batch 6 next.`

**Don't over-specify**
The agent will read your plan. You don't need to repeat the whole plan in the prompt.
The prompt is for framing, rules, and anything the plan doesn't cover.

**Friday kickoffs are special**
The weekend is ~60 hours of potential runtime. If you have a big feature plan, Friday afternoon
is the time to queue it. Spend 1-2 hours writing a thorough plan, configuring the survival
guide, and running preflight. Then walk away and let the agent work through Saturday and Sunday.
You may return Monday to a week's worth of output waiting for review.
