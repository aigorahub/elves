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

---

### Scenario 1: They Ask a Question

*Examples: "how's it going?", "what batch are you on?", "did the auth tests pass?"*

Answer concisely with current status, then immediately resume where you left off. Don't wait for a follow-up. Treat it like a colleague tapping you on the shoulder while you work. You answer without putting down your tools.

### Scenario 2: They Provide New Information

*Examples: "by the way, the payment API changed, use v3 not v2", "ignore the failing test in auth.spec.ts, it's a known flake"*

Acknowledge, incorporate the information into your current understanding, note it in the execution log under **Decisions made**, update the survival guide if it affects future batches, and keep going.

### Scenario 3: They Change Priorities

*Examples: "skip batch 4 and do batch 5 first", "add this to the plan"*

Acknowledge, update the survival guide's "Next Exact Batch" section to reflect the new priority, note the change in the execution log, and continue with the updated plan.

### Scenario 4: They Say "Stop"

Stop. This is the one exception to all of the above. An explicit stop command from the user overrides everything.

Complete whatever atomic operation you're in the middle of. Don't leave a half-written file or a broken commit. Then:

1. Update the execution log with where you stopped and why
2. Update the survival guide to reflect the current stopping point
3. Commit and push
4. Halt

### Scenario 5: Their Message Is Ambiguous

Use your best judgment about what they want, do it, document your interpretation in the execution log, and keep going. Don't ask clarifying questions. If you got it wrong, they'll correct you.

---

### Good and Bad Check-In Messages (for users)

When you check in on a running Elves session, frame your messages as instructions rather than open-ended questions. End with something like "keep going" or "don't stop" to reinforce that you're not expecting a back-and-forth conversation.

**Good:**
- "Batch 3 looks good. The payment tests are expected to fail, so ignore them. Keep going."
- "Change of plans: skip the email templates batch. Move straight to the API migration. Don't stop."
- "Quick question: did you update the migration file? Either way, keep going."

**Avoid:**
- "What do you think we should do about the database schema?" (open-ended, invites a pause)
- "Can you walk me through what you've done so far?" (long answer, breaks flow)

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
