# Elves

**Run overnight. Wake up to a PR.**

Elves is an open-source Agent Skill for autonomous, multi-batch development. It gives AI coding agents (Claude Code, Codex, or any agent that supports the Agent Skills standard) the ability to execute large development plans unattended — with testing, review, and documentation — while surviving context compaction across long runs.

You write the plan and do the final merge. The agent does everything in between.

---

## Why "Elves"?

In the old fairy tale, a tired shoemaker goes to bed with work undone and wakes to find it finished. That story is the premise of this skill.

Throughout economic history, wealth creation has followed a consistent pattern: a resource sits idle until someone builds a tool that makes it useful. Coal sat in the ground until the steam engine. Cars sat in driveways until Uber. Spare bedrooms sat empty until Airbnb. The resource already existed — what was missing was the mechanism.

Every knowledge worker has 12 to 14 hours each day when they are not working — evenings, nights, weekends. For most of history, that time was genuinely unproductive. AI agents change that. A well-configured agent can execute code, run tests, conduct reviews, and document decisions while its owner is asleep. The sleeping hours are now a resource. They weren't before.

The question is no longer "what can I have my AI do today?" It's "what will my AI be doing at 2am on Saturday?"

Elves is the mechanism. It converts idle hours into shipped code.

*Based on [The Shoemaker's Elves](https://x.com/johnennis/status/1893694505032986896) by John Ennis.*

---

## How It Works

```
Plan → Batch → Implement → Validate → Review → Document → Continue
```

Elves runs a tight loop. For each batch of planned work, the agent implements the changes, runs validation gates, reads PR review comments, fixes any blocking findings, updates the documentation, and pushes a checkpoint — then immediately starts the next batch. No waiting, no prompting, no drift.

### The Three-Document System

AI agents are stateless. Context compaction erases working memory. Elves solves this with three persistent documents that serve as the agent's memory across compactions, restarts, and long multi-hour runs:

| Document | Purpose |
|---|---|
| **Plan** | What needs to be built — the authoritative scope |
| **Survival Guide** | Standing brief: mission, rules, tool config, current phase, next batch |
| **Execution Log** | Running record of every batch completed, every decision made, every commit pushed |

After any compaction or restart, the agent reads these three files in order and resumes without losing its place. The survival guide is marked `# READ THIS FILE FIRST AFTER ANY COMPACTION OR RESTART` so the agent cannot miss it.

### Who does what

- **Human:** writes the plan, runs preflight, walks away, reviews the PR, and merges.
- **Agent:** executes every batch, runs tests, reads review comments, fixes blockers, documents decisions, and sends a completion notification when done.

The agent never merges. That gate stays with you.

---

## Quick Start

**1. Install the skill**

- **Claude Code:** copy `SKILL.md` into `.claude/skills/elves.md` in your repo
- **Codex:** copy `AGENTS.md` into `.agents/skills/elves.md`
- **Claude.ai:** zip the `elves/` directory and upload as a skill

**2. Write a plan**

Use [`references/plan-template.md`](references/plan-template.md) as your starting point. The plan describes what needs to be built, broken into logical batches. Commit it to your repo (e.g., `docs/plans/my-feature.md`).

**3. Start the session**

Use [`references/kickoff-prompt-template.md`](references/kickoff-prompt-template.md) to start the agent. It tells the agent where your plan, survival guide, and execution log live, and what branch to work on. If the survival guide and execution log don't exist yet, the agent generates them from the templates.

**4. Walk away**

Elves runs preflight checks first — git access, test gates, sleep prevention, notifications. Once preflight passes, the agent starts executing batches and won't stop until the plan is complete or time runs out.

---

## Features

- **Multi-batch execution** with configurable batch sizing (default: 4 developers × 2-week sprint)
- **Context compaction survival** via the three-document system — reads survival guide, plan, and execution log after every compaction
- **Auto-discovered validation gates** for Node.js, Python, Go, Rust, and Makefile projects — no configuration required
- **Pluggable review** — GitHub PR comments by default (zero config), custom review API opt-in, additional custom checks
- **Subagent delegation** for long runs (Claude Code) — coordinator manages the loop, subagents do the deep work
- **Rollback safety** — `git tag elves/pre-batch-N` before every batch, so any batch can be cleanly unwound
- **Scout mode** — after all planned work is done, the agent looks for adjacent improvements, test gaps, and documentation holes
- **Time-aware pacing** — tracks how long each batch takes and uses that to decide whether to start another batch or wrap up cleanly
- **Slack notifications** (or any custom command) — know when your run finishes without watching the terminal
- **Structured session data** in `.elves-session.json` for tooling, dashboards, and analytics
- **Comprehensive preflight checks** — git remote, push access, GitHub CLI auth, test gates, sleep prevention, Slack webhook, stale branch detection

---

## Preventing Sleep / Shutdown

This is the most common failure mode for overnight runs. If your machine sleeps, the session stops. Handle this before you walk away.

### macOS

```bash
# Prevent display, idle, and system sleep for the duration of your terminal session
caffeinate -dims &
```

Or wrap your agent command: `caffeinate -dims <your-agent-command>`

Elves preflight will warn you if `caffeinate` is not running and if you are on battery power.

### Linux

```bash
systemd-inhibit --what=idle <your-agent-command>
```

### Windows (WSL)

Open Power Options → Change plan settings → set "Put the computer to sleep" to **Never** for the duration of the run. Restore it afterward.

### Cloud / Remote (recommended for reliability)

Running on a cloud VM, GitHub Codespaces, or a remote server eliminates the sleep problem entirely. The session runs independently of your local machine. This is the most reliable option for very long runs.

### Pre-run checklist

- [ ] Machine is plugged in (not on battery)
- [ ] Sleep / display sleep is disabled
- [ ] Terminal will not close (tmux or screen recommended for SSH sessions)
- [ ] Notifications are configured so you know when the run finishes
- [ ] Preflight passed — Elves will verify the above automatically

---

## Monitoring Your Run

You do not need to watch the terminal. Here is how to check in from elsewhere.

**GitKraken** is the recommended way to monitor visually. Open it on the working branch and watch:
- **Commit graph** — steady commit cadence means the agent is making progress. A long gap may mean a slow test suite, a stuck review cycle, or an unexpected blocker.
- **Branch activity** — new commits appear as the agent completes each batch and pushes a checkpoint.
- **PR status** — review comments arriving on the PR means the review step is working.

**Slack notifications** deliver a completion message when the session ends (or when a batch completes, if you configure that). You can check your phone without opening a terminal.

**The execution log** is the most detailed view. Each batch entry records what changed, what commands ran, what the test results were, how long each phase took, and what decisions were made autonomously. Read it when you return to understand exactly what happened.

---

## Setting Up Notifications

### Slack (Recommended)

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app (from scratch).
2. Under **Features**, select **Incoming Webhooks** and enable it.
3. Click **Add New Webhook to Workspace** and select the channel where you want notifications.
4. Copy the webhook URL (it looks like `https://hooks.slack.com/services/T.../B.../...`).
5. Set the environment variable before starting your session:

```bash
export ELVES_SLACK_WEBHOOK="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

Elves preflight will send a test message to confirm the webhook works before you walk away.

### Custom Notifications

Set `ELVES_NOTIFY_CMD` to any shell command you want run at session completion:

```bash
# Example: send a push notification via ntfy
export ELVES_NOTIFY_CMD='curl -d "Elves done" ntfy.sh/your-topic'

# Example: send an email via sendmail
export ELVES_NOTIFY_CMD='echo "Elves session complete" | sendmail you@example.com'
```

If neither `ELVES_SLACK_WEBHOOK` nor `ELVES_NOTIFY_CMD` is set, Elves falls back to leaving a comment on the PR.

---

## Configuration

### Tool Configuration

Tool-specific configuration lives in the survival guide under `## Tool Configuration`. This keeps the agent's instructions with the session rather than scattered across environment variables.

See [`references/tool-config-examples.md`](references/tool-config-examples.md) for full examples covering Node.js, Python, Go, Rust, monorepos, and custom review APIs.

**Minimal Node.js example** (add to survival guide):

```markdown
## Tool Configuration

### Validation Gates
- lint: `npm run lint`
- typecheck: `npm run typecheck`
- build: `npm run build`
- test: `npm test`

### Review
- method: github-pr-comments
```

If you do not configure validation gates, Elves auto-discovers them from your project files (`package.json`, `Makefile`, `pyproject.toml`, `Cargo.toml`, `go.mod`).

### Batch Sizing

The default batch size is what a team of 4 developers would accomplish in a 2-week sprint — roughly 40 person-days of effort. This limits blast radius and makes compaction recovery tractable.

Override in your plan or survival guide:

```markdown
## Batch Sizing
- team-size: 2
- sprint-length: 1 week
```

Each batch must be independently shippable: code, tests, docs, and passing review before moving on.

### Review Methods

| Tier | Method | Configuration |
|---|---|---|
| **Tier 1** | GitHub PR comments | Default — zero config. Agent reads all comments, categorizes by severity, fixes blockers. |
| **Tier 2** | Custom review API | Set `method: custom-api` and `review-api-url` in survival guide. |
| **Tier 3** | Additional checks | Smoke tests, screenshot diffs, doc checks, or any custom script returning 0/non-zero. |

The agent uses the highest tier you have configured. Non-blocking findings are logged; persistent false positives (3+ cycles) are assessed and dismissed with a written explanation in the execution log.

---

## File Structure

```
elves/
├── SKILL.md                              # Claude Code skill
├── AGENTS.md                             # Codex variant
├── references/
│   ├── survival-guide-template.md
│   ├── execution-log-template.md
│   ├── plan-template.md
│   ├── kickoff-prompt-template.md
│   └── tool-config-examples.md
├── scripts/
│   ├── preflight.sh
│   └── notify.sh
├── README.md
└── LICENSE
```

---

## Platform Support

| Platform | File | Subagents | Notes |
|---|---|---|---|
| Claude Code | SKILL.md | Yes | Full feature set |
| Codex | AGENTS.md | No | All work done directly |
| Claude.ai | SKILL.md (zip upload) | No | Upload as skill |
| Any Agent Skills compatible | SKILL.md | Varies | Open standard |

---

## Philosophy

- **Human does planning and final review.** The agent does everything in between. Good managers think constantly about whether the people and resources they're responsible for are being deployed well. That instinct now applies to your agents.
- **The 14-hour resource.** Every knowledge worker has 12-14 hours per day when they're not working. Elves converts those hours into shipped code. A two-hour planning session on Friday can produce a week's worth of output before you touch your keyboard on Monday.
- **Three documents are the agent's memory.** Without them, long runs drift and repeat work. With them, a restarted agent picks up exactly where it left off.
- **Never merge.** The PR is for review, not for merging. That gate stays with the human.
- **Document every decision.** Anything the agent decides without user input goes in the execution log under *Decisions made*. The human reviews these choices when they return.
- **Fail safely, not silently.** If the agent is genuinely blocked, it stops and says so. If a test gate fails, it fixes the issue before continuing. It does not skip gates or paper over failures.
- **Rollback before every batch.** `elves/pre-batch-N` tags mean any batch can be cleanly unwound without touching other work.
- **Agent infrastructure is real engineering.** Tight code review systems, organized work trees, failure handling — developers who treat agent infrastructure as a real engineering concern end up with something that functions like a tireless junior team working every hour they're away from their desk.

---

## The Daily Briefing

Block time at the end of your workday — even 30 minutes — to brief your agents. Load them with enough well-defined work to keep them running through the night. Before you go offline, everything needs to be provisioned and pointed in the right direction.

Friday afternoons deserve more deliberate treatment. The weekend is roughly 60 hours of potential agent runtime. A two-hour planning session on Friday, setting up plans, configuring the survival guide, and queuing batch work, can produce a week's worth of output before Monday morning.

The people who start treating their idle hours as the asset they've suddenly become will have a real advantage.

---

## Contributing

Issues and pull requests are welcome. If you find a bug, have a feature idea, or want to add support for a new platform or tool, open an issue to discuss it first.

When submitting a PR:
- Keep changes focused — one concern per PR.
- Update the relevant template or reference file if your change affects agent behavior.
- Test your change with at least one real overnight run if possible.

---

## License

MIT — see [LICENSE](LICENSE).

Copyright (c) 2026 Aigora.
