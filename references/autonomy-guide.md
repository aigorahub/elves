# Autonomy Guide: Staying Unattended

## The Core Problem

The user isn't there. They are asleep, or at dinner, or spending time with their family. The whole point of Elves is that the 12 to 14 hours each day when the user isn't working become productive hours. But that only works if the loop keeps running.

Any pause, prompt, or confirmation dialog that expects human input will stall the entire run with no one to respond. **This is the single most common failure mode for overnight sessions.** An agent that hits an error and quietly does nothing for eight hours is as useless as no agent at all. The rules below exist to prevent it.

---

## Never Stop to Ask

### Rule 1: No Questions After Session Start

Never ask the user a question after the session has started. All questions happen during preflight, before the user goes offline. Once the run begins, you make decisions and document them.

If something is ambiguous, apply your best judgment, note it under **Decisions made** in the execution log, and keep moving. The user will review your choices when they return. A batch with a documented judgment call is more valuable than a stalled session with a polite question nobody is awake to answer.

### Rule 2: Never Use Interactive Commands

Every CLI command must run non-interactively. Use flags that suppress prompts:

- `--yes`, `--force`, `--no-input`, `--non-interactive`, `--assume-yes`
- `git push` (verify auth in preflight so no credential prompt appears at runtime)
- `npm install --yes`, `npx --yes`, `pip install --quiet`
- `gh pr create --fill` (not interactive mode)
- Pipe `yes |` or use `echo y |` as a last resort for tools that insist on confirmation

If a tool has a `--no-interaction` or `--batch` flag, use it.

### Rule 3: Suppress All Confirmation Dialogs, Surveys, and Update Prompts

Some tools (including AI coding tools) may pop up surveys, update notices, or permission requests. These will break the flow. Mitigations:

- Set `CI=true` (many tools detect this and skip interactive prompts entirely)
- Set `DEBIAN_FRONTEND=noninteractive` on Linux
- Set `HOMEBREW_NO_AUTO_UPDATE=1` on macOS
- Disable telemetry and surveys: `NEXT_TELEMETRY_DISABLED=1`, `NUXT_TELEMETRY_DISABLED=1`, `DOTNET_CLI_TELEMETRY_OPTOUT=1`

See the [Preflight Non-Interactive Environment](#preflight-non-interactive-environment) section for the full export block.

### Rule 4: Never Wait for CI in a Blocking Loop

Never wait for CI to finish before continuing local work. Push and move on. Read CI results on the next review cycle. Don't poll a CI pipeline in a blocking loop; it wastes time budget and can stall indefinitely if the pipeline is slow.

### Rule 5: Handle Unexpected Prompts Without Pausing

If you encounter an unexpected prompt or interactive input request, don't attempt to answer it interactively. Instead:

1. Kill the command (if possible)
2. Log the issue in the execution log with the exact command and prompt text
3. Find a non-interactive alternative
4. If no alternative exists, skip that step, log it, and continue

The run must not stall because one tool asked a question.

### Rule 6: Ambiguous Requirements Are Not a Reason to Stop

Make your best judgment call, document it under **Decisions made** in the execution log, and keep moving. The user will review your choices when they return. If you got it wrong, they'll correct you.

---

## When the User Checks In Mid-Run

Sometimes the user will come back while you are still working. They might check in at 2am, glance at progress, and want to give you additional context, ask a question, or adjust priorities. This is normal and expected.

**The critical rule: answer or acknowledge, then keep going. Don't stop.**

The user checking in isn't an invitation to pause and have a conversation. It's a drive-by. They are probably half-asleep. Give them what they need and get back to work.

The pattern is always the same: **handle the input, document it, resume the loop.**

Users should prefix mid-run messages with **`ra:`**, **`ride-along:`**, or **`[ride-along]`** — these mean "handle this and keep going." See **The ride-along prefix** section below for details and examples.

---

### Scenario 1: They Ask a Question

*Examples: "how's it going?", "what batch are you on?", "did the auth tests pass?"*

Answer concisely with current status, then immediately resume where you left off. Don't wait for a follow-up. Treat it like a colleague tapping you on the shoulder while you work. You answer without putting down your tools.

### Scenario 2: They Provide New Information

*Examples: "by the way, the payment API changed, use v3 not v2", "ignore the failing test in auth.spec.ts, it's a known flake"*

Acknowledge, incorporate the information into your current understanding, note it in the execution log under **Decisions made**, update the survival guide if it affects future batches, and if the information is durable beyond the current batch also update `learnings.md` or the relevant `.ai-docs/*` file. Then keep going.

### Scenario 3: They Change Priorities

*Examples: "skip batch 4 and do batch 5 first", "add this to the plan"*

Acknowledge, update the survival guide's "Next Exact Batch" section to reflect the new priority, note the change in the execution log, and continue with the updated plan.

If the message also changes stop behavior or checkpoint meaning — for example, "have something by
8am but keep going" or "do not stop unless blocked" — rewrite the survival guide's `## Run Control`
block immediately and log the change in the execution log.

### Scenario 4: They Say "Stop"

Stop. This is the one exception to all of the above. An explicit stop command from the user overrides everything.

Complete whatever atomic operation you're in the middle of. Don't leave a half-written file or a broken commit. Then:

1. Update the execution log with where you stopped and why
2. Update the survival guide to reflect the current stopping point
3. Commit and push
4. Halt

### Scenario 5: Their Message Is Ambiguous

Use your best judgment about what they want, do it, document your interpretation in the execution log, and keep going. Don't ask clarifying questions. If you got it wrong, they'll correct you.

### Scenario 6: They Check In On Cost Or Active Compute

*Examples: "are the pods still running?", "use them or shut them down", "pause anything idle"*

Answer directly, then immediately reconcile the actual compute picture:

1. State what paid or long-running resources are active.
2. For each, state what it is doing.
3. If any resource is idle, stale, or ambiguous, pause or stop it now.
4. Rewrite the survival guide's Active Compute section before resuming work.

Do not answer the question and then drift away without reconciling the compute state.

---

### The ride-along prefix (for users)

The simplest way to interact during a run is to prefix your message with **`ra:`**. `ride-along:` and `[ride-along]` work too. These tell the agent: "Handle this and keep going. Do not stop." The agent responds in 1-3 sentences and resumes immediately — no follow-up questions, no pause, no lengthy summaries.

Equivalent prefixes: `ra:`, `ride-along:`, and `[ride-along]`. Prefer `ra:` for speed or `[ride-along]` for maximum clarity.

**Good:**
- `[ride-along] The payment tests are expected to fail. Ignore them.`
- `[ride-along] Skip the email templates batch. Do the API migration next.`
- `[ride-along] Quick question: did you update the migration file?`
- `[ride-along] Looks good so far, keep it up.`
- `ra: skip the email templates batch and do the API migration next.`

**Avoid (no tag — agent may pause):**
- "What do you think we should do about the database schema?" (open-ended, invites a pause)
- "Can you walk me through what you've done so far?" (long answer, breaks flow)
- "Looks good so far." (no instruction to continue)

---

## Preflight Non-Interactive Environment

Set these environment variables at session start to suppress interactive prompts across common tools. They prevent tools from pausing for update prompts, telemetry opt-ins, surveys, or version check notices during the run.

```bash
export CI=true
export DEBIAN_FRONTEND=noninteractive
export HOMEBREW_NO_AUTO_UPDATE=1
export NEXT_TELEMETRY_DISABLED=1
export NUXT_TELEMETRY_DISABLED=1
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export PYTHONDONTWRITEBYTECODE=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export NPM_CONFIG_YES=true
echo "✓ Non-interactive environment variables set"
```

The agent should set these at the start of every session if they are not already present. The user's environment should also be configured during preflight to minimize interactive prompts. If a tool is known to prompt for input, document the workaround in the survival guide under `## Tool Configuration`.

---

## Memory Pressure And Strategic Forgetting

Long-running agent apps can slow down when active chats, terminal logs, worktrees, or local state
grow without boundaries. Elves should prevent that in two layers:

1. **In-run hygiene** keeps the current autonomous run fast and resumable.
2. **Local app maintenance** cleans Codex/Claude application state only when explicitly requested
   and only after inspection and backups.

### In-run hygiene

Do this during entropy checks, after unusually large batches, before a checkpoint handoff, and
before Final Completion:

- Keep the survival guide live sections concise. Rewrite current state in place.
- Archive old execution-log entries under `## Completed Archive` when the log gets large.
- Promote durable lessons to `learnings.md` or `.ai-docs/*`; condense superseded lessons.
- Rotate or archive oversized project-created command logs when safe.
- Stop or pause idle dev servers, terminals, paid jobs, and remote resources.
- If the agent app is becoming sluggish or memory pressure is visible, write a concise handoff and
  resume from a fresh launch context when the platform allows it.

The goal is a clean memory workspace when the user returns: the branch is ready to review, the PR
feedback queue is handled, and the next agent can restart from small durable docs instead of a
giant chat.

### Local app maintenance

Do not perform this as a hidden side effect of a coding run. Only do it when the user asks for
cleanup or weekly maintenance.

Safe maintenance follows this order:

1. **Inspect first.** Report what is taking space: sessions, archived sessions, worktrees,
   archived worktrees, logs, config, state databases, skills, plugins, and automations.
2. **Back up important state.** Back up config, global state, session indexes, state databases,
   memories, skills, plugins, and automations before changing anything.
3. **Check whether the app is open.** If Codex or Claude Code is running, only inspect. Apply
   cleanup after closing it so local databases are not touched by two processes.
4. **Create handoffs before archiving active chats.** For any active thread that might matter,
   write a concise reactivation handoff with branch, PR, status, remaining work, validation state,
   risks, and the prompt to resume.
5. **Archive, don't delete.** Move old non-pinned chats, stale worktrees, and oversized old logs to
   archive locations. Do not erase them as part of routine maintenance.
6. **Prune dead references.** Remove config project paths that no longer exist or point at
   temporary folders. Normalize platform-specific path variants when needed.
7. **Review processes, don't auto-kill.** List heavy background processes such as Node/dev servers
   and close only the ones the user confirms are no longer needed.
8. **Verify.** Confirm config still parses, state databases open, active session size dropped,
   archived sessions increased, and no bad paths remain.
9. **Make it boring.** Weekly maintenance should be repeatable, backup-first, archive-first, and
   report-driven.

The key distinction: chats are for execution, handoff docs are for memory, archives are for
history, and fresh threads are for speed.
