# Operations guide: keeping unattended runs alive

Practical host-machine setup for long Elves runs: sleep prevention, terminal survival,
monitoring, notifications, the Claude Code SessionStart hook, and the daily briefing pattern.
Moved from the README so the front page stays a front page; content unchanged.

## Preventing sleep / shutdown

This is the most common failure mode for overnight runs. If your machine sleeps, the session stops. Handle this before you walk away.

**Continuity watchdog (opt-in, trusted full-runs only).** When the session dies anyway, an
operator-owned OS timer can re-enter a resumable full-run:
`cobbler_agents.py continuity install --session-id … --branch … --start-head … --packet …`
writes the watchdog config plus launchd/systemd user-timer **templates** and prints the exact
activation commands — Elves never runs `launchctl` or `systemctl` and activates nothing itself;
the OS owns the timer. Default posture is detect-and-report (`--check` + notification);
relaunching requires the explicit `--auto-resume` opt-in. Every fire is a stateless
claim-before-act check (overlapping fires are single-flight; missed fires coalesce), and every
safety decision belongs to `full-run-prepare --resume`: a possibly-live run refuses, and the
watchdog **never resumes a terminal run** — terminal or unverifiable event logs refuse
byte-for-byte unchanged (v2.23 semantics). It holds no landing, merge, or credential authority,
and cannot revive host-native driver sessions (those need the recovery read order in a fresh
session). `continuity status|remove` manage it; removal is idempotent.

### macOS

```bash
# Prevent display, idle, and system sleep for the duration of your terminal session
caffeinate -dims &
```

Or wrap your agent command: `caffeinate -dims <your-agent-command>`

Elves preflight will warn you if `caffeinate` isn't running and if you are on battery power.

### Linux

```bash
systemd-inhibit --what=idle <your-agent-command>
```

### Windows (WSL)

Open Power Options → Change plan settings → set "Put the computer to sleep" to **Never** for the duration of the run. Restore it afterward.

### Cloud / remote (recommended for reliability)

Running on a cloud VM, GitHub Codespaces, or a remote server eliminates the sleep problem entirely. The session runs independently of your local machine. This is the most reliable option for very long runs.

### SSH sessions

If you're running over SSH, your session dies when the connection drops. Always use a terminal multiplexer:

```bash
# Start a new tmux session
tmux new -s elves

# Run your agent inside tmux, then detach with Ctrl+B, D
# Reconnect later with:
tmux attach -t elves
```

`screen` works the same way: `screen -S elves`, detach with `Ctrl+A, D`, reattach with `screen -r elves`.

### Suppress surveys and popups

Some coding tools show survey popups, feedback requests, or update prompts during sessions. These will stall an unattended run. Configure your tools before starting:

- **Claude Code:** add to your CLAUDE.md: `"Do not show surveys, popups, or update prompts during this session."`
- **Codex:** add to your AGENTS.md: `"Never pause for surveys, feedback requests, or update prompts."`
- **Cursor / other tools:** check settings for telemetry, notifications, and update checks. Disable anything interactive.

### Pre-run checklist

- [ ] Agent has the permissions it needs (file access, git push, `gh` auth, any tool approvals). If your platform requires you to approve actions (file writes, terminal commands, etc.), grant those permissions before you walk away. A permission prompt at 3am with nobody to click "allow" will stall the entire run. You're granting these permissions at your own risk (see the Disclaimer section of the repository README).
- [ ] Machine is plugged in (not on battery)
- [ ] Sleep / display sleep is disabled or caffeinate running
- [ ] Terminal is in tmux/screen (if SSH) or won't be closed
- [ ] Surveys and popups disabled in your coding tool's settings
- [ ] Branch ownership is manually confirmed: no other active agent is using this checkout or this branch. Preflight will catch duplicate current-branch worktrees.
- [ ] Notifications are configured so you know when the run finishes
- [ ] Preflight passed (Elves will verify the above automatically)

---


## Monitoring your run

You don't need to watch the terminal. Here's how to check in from elsewhere.

**GitKraken** is the recommended way to monitor visually. Open it on the working branch and watch:
- **Commit graph**: steady commit cadence means the agent is making progress. A long gap may mean a slow test suite, a stuck review cycle, or an unexpected blocker.
- **Branch activity**: new commits appear as the agent completes each batch and pushes a checkpoint.
- **PR status**: review comments arriving on the PR means the review step is working.

**Slack notifications** deliver a completion message when the session ends (or when a batch completes, if you configure that). You can check your phone without opening a terminal.

**The execution log** is the most detailed view. Each batch entry records what changed, what commands ran, what the test results were, how long each phase took, and what decisions were made autonomously. Read it when you return to understand exactly what happened.

---


## Setting up notifications

### Slack (recommended)

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app (from scratch).
2. Under **Features**, select **Incoming Webhooks** and enable it.
3. Click **Add New Webhook to Workspace** and select the channel where you want notifications.
4. Copy the webhook URL (it looks like `https://hooks.slack.com/services/T.../B.../...`).
5. Set the environment variable before starting your session:

```bash
export ELVES_SLACK_WEBHOOK="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

Elves preflight will send a test message to confirm the webhook works before you walk away.

### Custom notifications

Set `ELVES_NOTIFY_CMD` to any shell command you want run at session completion:

```bash
# Example: send a push notification via ntfy
export ELVES_NOTIFY_CMD='curl -d "Elves done" ntfy.sh/your-topic'

# Example: send an email via sendmail
export ELVES_NOTIFY_CMD='echo "Elves session complete" | sendmail you@example.com'
```

If neither `ELVES_SLACK_WEBHOOK` nor `ELVES_NOTIFY_CMD` is set, Elves falls back to leaving a comment on the PR.

---



## Advanced: Claude Code SessionStart hook

For Claude Code users, you can make compaction recovery fully automatic by adding a SessionStart hook that loads the survival guide at the beginning of every session.

Add this to your `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "echo '=== ELVES CONTEXT ===' && cat docs/elves/survival-guide.md 2>/dev/null && echo '' && echo '=== GIT STATUS ===' && git status --short && echo '' && echo '=== RECENT COMMITS ===' && git log --oneline -5"
      }
    ]
  }
}
```

This injects the survival guide, current git status, and recent commits into Claude's context at session start, even after a compaction or restart. The agent gets its bearings immediately without needing to be told to read the files.

Replace `docs/elves/survival-guide.md` with the exact path recorded for the active run. Do not use a
wildcard: parallel or archived runs may have more than one matching guide.

### Recover after compaction deterministically

Current Claude Code hooks support SessionStart matchers (`startup`, `resume`, `clear`, `compact`,
`fork`). A `compact`-matched hook fires immediately after a compaction finishes, so the survival
guide is re-injected at the exact moment context was summarized instead of relying on the agent to
remember a read-order protocol. Hook capabilities are version-dependent: verify the matcher values
(and the structured `hookSpecificOutput.additionalContext` output field, if you prefer it over
plain stdout injection) against your installed Claude Code version's hooks documentation.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": "echo '=== ELVES POST-COMPACTION RECOVERY ===' && cat docs/elves/survival-guide.md 2>/dev/null && git status --short"
          }
        ]
      }
    ]
  }
}
```

### Steer what compaction preserves

The compactor reads a "Summary instructions" section from the project memory file (CLAUDE.md).
Adding one tells auto-compaction what an Elves run cannot afford to lose:

```markdown
# Summary instructions

When summarizing this conversation, always preserve:
- The active run's survival guide path and `.elves-session.json` path
- Batch number and status, and every acceptance ID (B#-A#, M-A#) with its met/unmet state
- The current feature branch name and the forbidden-command list
- Stop Gate and Run Control state
```

Compaction is a lossy summary; the run docs remain the ground truth. These hooks make recovery
deterministic — they do not replace the survival guide.

### Enforce forbidden commands with hooks

Elves tells the agent not to run destructive git commands, but instructions can be forgotten after context compaction. For bulletproof enforcement, add a PreToolUse hook that blocks them deterministically:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "type": "command",
        "command": "case \"$TOOL_INPUT\" in *'git reset --hard'*|*'git checkout .'*|*'git clean -fd'*|*'git push --force'*|*'git push -f '*|*'rm -rf /'*) echo 'BLOCKED: Forbidden command detected. Elves does not allow destructive git operations.' >&2; exit 1;; esac",
        "matcher": "Bash"
      }
    ]
  }
}
```

This runs before every Bash command and blocks the operation if it matches a forbidden pattern. Unlike instructions (which can be compacted away), hooks are deterministic. The agent can't forget them and can't override them.

This pattern comes from Anthropic's internal practices. Their `/careful` hook uses the same approach to block destructive operations in production environments.

---


## The daily briefing

Block time at the end of your workday (even 30 minutes) to brief your agents. Load them with enough well-defined work to keep them running through the night. Before you go offline, everything needs to be provisioned and pointed in the right direction.

Friday afternoons deserve more deliberate treatment. The weekend is roughly 60 hours of potential agent runtime. A two-hour planning session on Friday, setting up plans, configuring the survival guide, and queuing batch work, can produce a week's worth of output before Monday morning.

The people who start treating their idle hours as the asset they've suddenly become will have a real advantage.

---


## Making it your own

**Elves is scaffolding, not a finished product.** It gives you the framework: the loop, the documents, the gates. But every project is different. You'll need to customize it for your own purposes, and you'll learn your own lessons along the way.

### What to customize first

**The survival guide template** is where most customization happens. When you generate a survival guide for your project, you'll fill in:
- Your specific test commands (not every project uses `npm run lint`)
- Your non-negotiables (what must never happen in your codebase)
- Your review method (PR comments, a custom API, manual checks)
- Your notification preference (Slack, email, PR comment)
- Your batch sizing (maybe your team is 2 people, not 4)
- Your checkpoint semantics and actual stop conditions
- Your active compute picture if the run uses paid pods, remote jobs, or long-lived servers
- Your Stop Gate defaults and the next required action at launch
- Your Effort Standard if you want to reinforce "do not be lazy / work as hard as you can" behavior for long unattended runs

Treat the survival guide as a live operator brief. Rewrite `Run Control`, `Current Phase`, `Active Compute`, `Stop Gate`, `Effort Standard`, and `Next Exact Batch` in place as the run evolves. Do not stack stale "next action updates" there; put history in the execution log instead.

If the run has a morning checkpoint, return time, paid pods, remote jobs, or long-lived servers,
say so explicitly in the survival guide. The agent should never have to guess whether a time is a
delivery checkpoint or a hard stop, or whether compute should be shut down, paused, or kept warm.

For real runs, I recommend exporting `ELVES_SURVIVAL_GUIDE_PATH` before `./scripts/preflight.sh`.
Preflight will run `python3 scripts/validate_survival_guide.py "$ELVES_SURVIVAL_GUIDE_PATH"` as a
warning-only check. It won't block launch, but it will catch half-filled Stop Gate / Run Control
fields before you go offline.

### Why acceptance evidence and the landing check exist

Elves already had strong gates against *early* land (Stop Gate, Completion Contract, regression
attestation). What it did not force was proof that plan **Acceptance** was met — only that the
agent *said* each batch was complete. That gap bites hardest on weaker or less disciplined models,
and on any model after context compaction or late-run thrash:

| Easy green signal | What it actually proves | What it does not prove |
| --- | --- | --- |
| CI / unit tests green | Code compiles and covered paths work | Plan Acceptance (LOC cut, facade, split) |
| Structure / regex "lock" tests | A shape or characterization still holds | The god-file was actually split |
| `status: complete` in session JSON | The agent flipped a flag | Criteria were met with evidence |
| Multi-batch "close remaining" commit | Something pushed | Each batch had its own validate pass |

So v1.19+ hardens both skill surfaces (Claude `SKILL.md` and Codex `AGENTS.md`) the same way:

1. **Per-batch acceptance rows** — `acceptance: [{id: "B#-A#", criterion, met, evidence}]` before
   complete; reconcile branch-level `M-A#` rows too, and give legacy rows deterministic aliases.
   `B0` and `B1` are equally valid starts, with no preferred convention. Plan rows may be written
   as either `- [ ] B0-A1: criterion text` or `- [ ] [B0-A1] criterion text`; they mean the same
   thing
2. **God-file rule** — locks lock; they do not complete a split unless the plan allows characterization-only
3. **One batch per close commit** (or labeled **Validate:** sections per batch id)
4. **`scripts/elves_landing_check.py`** — machine check before Final Readiness / merge-on-green

Policy in one line: **green CI + `status: complete` is not landable; landable is plan Acceptance with proof.**

Before Final Readiness or merge-on-green / reviewed-PR landing, run the landing check when the
session JSON exists. Resolve `ELVES_SKILL_ROOT` to the active installed Claude Code or Codex Elves
bundle, keep the target repository as the working directory, and pass the exact tracked session
path:

```bash

## Batch boundaries as designated compaction points (P3)

After a batch **Close** (run docs updated, acceptance recorded, commit pushed), the
session is in a safe place for context compaction:

- Interactive operators may run `/compact` (or the host equivalent) on the driver
  session once the survival guide and execution log are current.
- Drivers of long-lived supervised workers may issue a compact on the **worker**
  session only when the host grammar supports it as a real compact (not echo), and
  only at batch close — never mid-implement.
- **Prewalk sessions are excluded** while exact-session qualification is active; see
  compaction de-qualification in `references/prewalk.md`.

When headless compact is version-dependent, verify on the installed CLI before
claiming automation; otherwise document the interactive prompt only.
