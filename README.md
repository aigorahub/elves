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

The core pattern is the Ralph Loop: try, check, feed back, repeat. An AI doesn't return correct or incorrect answers — it returns drafts. Judging AI on its first attempt is like judging a tree by its first day of growth. The people who get extraordinary results aren't writing better prompts. They are running better loops.

Elves is the harness that lets the Ralph Loop run for hours without supervision — with a Survival Guide so the agent knows what it's doing, an Execution Log so it can recover after a restart, and test gates so it knows whether its work is actually correct before it moves on.

*Part of a series by John Ennis: [The Shoemaker's Elves](https://x.com/johnennis/status/2025904571311141215) (the 14-hour resource), [The Survival Guide](https://x.com/johnennis/status/2028960113646604794) (keeping agents on track), and [Water the Tree](https://x.com/johnennis/status/2034300044212351114) (the Ralph Loop).*

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

### The Human Sandwich

The shape of productive work is changing. The human operates on both ends — specifying problems and reviewing output — while the agent runs loops in the middle.

- **Front end (human):** Decide what's worth working on. Write the plan. Specify the problem fully. What are we trying to accomplish? What does success look like? What are the constraints?
- **Middle (agent):** Run the loop. Implement, validate, review, fix, iterate. This happens while you sleep.
- **Back end (human):** Review the output. Catch the remaining issues. Provide final judgment. Merge.

The agent never merges. That gate stays with you.

---

## Quick Start

**1. Install the skill**

See [Installation](#installation) below for full details. The short version:

- **Claude Code:** copy the `elves/` directory into `.claude/skills/elves/` in your repo
- **Codex:** copy `AGENTS.md` into `.agents/skills/elves/AGENTS.md`
- **Claude.ai:** zip the `elves/` directory and upload via Settings > Features > Skills

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

### SSH Sessions

If you're running over SSH, your session dies when the connection drops. Always use a terminal multiplexer:

```bash
# Start a new tmux session
tmux new -s elves

# Run your agent inside tmux, then detach with Ctrl+B, D
# Reconnect later with:
tmux attach -t elves
```

`screen` works the same way: `screen -S elves`, detach with `Ctrl+A, D`, reattach with `screen -r elves`.

### Pre-run checklist

- [ ] Machine is plugged in (not on battery)
- [ ] Sleep / display sleep is disabled or caffeinate running
- [ ] Terminal is in tmux/screen (if SSH) or won't be closed
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
├── SKILL.md                              # Claude Code skill (main instructions)
├── AGENTS.md                             # Codex variant
├── references/
│   ├── survival-guide-template.md        # Bootstrap template for new projects
│   ├── execution-log-template.md         # Log entry template
│   ├── plan-template.md                  # How to write a good plan
│   ├── kickoff-prompt-template.md        # Copy-paste prompts for starting a run
│   ├── tool-config-examples.md           # Configs for Node, Python, Go, Rust, etc.
│   ├── validation-guide.md               # Detailed validation gates and auto-discovery
│   └── autonomy-guide.md                 # Non-interactive operation and mid-run protocols
├── scripts/
│   ├── preflight.sh                      # Pre-run checklist
│   └── notify.sh                         # Notification helper
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

- **The Human Sandwich.** The human operates on both ends: specifying problems and reviewing output. The agent runs the loop in the middle. Your working hours become morning for reviewing last night's output, afternoon for setting up the next run.
- **The Ralph Loop.** Try, check, feed back, repeat. AI returns drafts, not answers. A dumb, stubborn loop beats over-engineered sophistication because AI is non-deterministic. Any single attempt might fail. But if you keep trying, checking, and feeding back, the process converges.
- **The 14-hour resource.** Every knowledge worker has 12-14 hours per day when they're not working. Elves converts those hours into shipped code. A two-hour planning session on Friday can produce a week's worth of output before you touch your keyboard on Monday.
- **Three documents are the agent's memory.** Without them, long runs drift and repeat work. With them, a restarted agent picks up exactly where it left off. These aren't overhead — they are the minimum viable infrastructure for the loop to run unsupervised.
- **Tests are the watch.** An agent working overnight has no one watching. The tests are the watch. Without them, you wake up to code that compiles, passes lint, and does the wrong thing.
- **Never merge.** The PR is for review, not for merging. That gate stays with the human.
- **Document every decision.** Anything the agent decides without user input goes in the execution log under *Decisions made*. The human reviews these choices when they return.
- **Fail safely, not silently.** If the agent is genuinely blocked, it stops and says so. If a test gate fails, it fixes the issue before continuing. It does not skip gates or paper over failures.
- **Rollback before every batch.** `elves/pre-batch-N` tags mean any batch can be cleanly unwound without touching other work.
- **Agent infrastructure is real engineering.** Tight code review systems, organized work trees, failure handling — developers who treat agent infrastructure as a real engineering concern end up with something that functions like a tireless junior team working every hour they're away from their desk.

---

## What Can Go Wrong

Overnight agent runs fail in predictable ways. Knowing the failure modes makes them preventable.

| Failure | What happens | Mitigation |
|---|---|---|
| **Machine sleeps** | Session stops silently. You wake up to 45 minutes of work instead of 8 hours. | `caffeinate` (macOS), `systemd-inhibit` (Linux), or run in cloud. Elves preflight warns you. |
| **Agent runs destructive git commands** | `git reset --hard` wipes hours of uncommitted work. This has happened to real users. | Elves explicitly forbids `git reset --hard`, `git checkout .`, `git push --force`, and `git clean -fd`. The survival guide template includes these as non-negotiables. |
| **Agent disables or weakens tests** | Agent comments out failing tests, weakens assertions, or shortens timeouts to make the gate pass. You wake up to code that "passes" but is broken. | Elves has a Test Integrity rule: never modify a test to make it pass. Fix the code, not the test. If the agent thinks a test is wrong, it logs the issue and moves on without changing it. |
| **Context compaction loses instructions** | Long sessions hit memory limits. The agent's conversation gets summarized, and safety instructions disappear. | Elves stores all instructions in files on disk (survival guide, plan, execution log), not in conversation memory. The agent re-reads the survival guide after every push. Compaction can't erase files. |
| **Interactive prompt stalls the session** | A tool asks for confirmation, a survey pops up, or `npm install` wants input. Nobody is there to click yes. | Elves sets `CI=true` and other non-interactive env vars in preflight. The skill explicitly requires `--yes` flags on all commands. |
| **Flaky tests block progress** | A test passes locally but fails intermittently. The agent loops trying to fix a non-bug. | The agent logs flaky tests in the execution log and moves on after 3 failed attempts on the same non-deterministic failure. |
| **Terminal closes (SSH disconnect)** | The SSH connection drops and the session dies. | Use `tmux` or `screen`. Elves mentions this in the pre-run checklist. |
| **Agent drifts from the plan** | After many batches, the agent starts making changes that weren't in the plan. | The agent re-reads the survival guide after every push and checks the plan hash to detect modifications. The three-document system anchors every decision. |

Most of these are prevented by the preflight checks. Run preflight, fix the warnings, and most overnight failures never happen.

---

## Advanced: Claude Code SessionStart Hook

For Claude Code users, you can make compaction recovery fully automatic by adding a SessionStart hook that loads the survival guide at the beginning of every session.

Add this to your `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "echo '=== ELVES CONTEXT ===' && cat docs/plans/*-survival-guide.md 2>/dev/null && echo '' && echo '=== GIT STATUS ===' && git status --short && echo '' && echo '=== RECENT COMMITS ===' && git log --oneline -5"
      }
    ]
  }
}
```

This injects the survival guide, current git status, and recent commits into Claude's context at session start — even after a compaction or restart. The agent gets its bearings immediately without needing to be told to read the files.

Adjust the `cat` path to match where your survival guide lives.

---

## The Daily Briefing

Block time at the end of your workday — even 30 minutes — to brief your agents. Load them with enough well-defined work to keep them running through the night. Before you go offline, everything needs to be provisioned and pointed in the right direction.

Friday afternoons deserve more deliberate treatment. The weekend is roughly 60 hours of potential agent runtime. A two-hour planning session on Friday, setting up plans, configuring the survival guide, and queuing batch work, can produce a week's worth of output before Monday morning.

The people who start treating their idle hours as the asset they've suddenly become will have a real advantage.

---

## Installation

Elves can be installed globally (applies to all your projects) or per-project (lives in the repo).

### Global Installation (recommended to start)

Global installation means the skill is always available, no matter which project you're in. Install it once, use it everywhere, and customize it as you learn.

**Claude Code:**
```bash
# Create the global skills directory if it doesn't exist
mkdir -p ~/.claude/skills/elves

# Clone and copy
git clone https://github.com/aigorahub/elves.git /tmp/elves
cp -r /tmp/elves/SKILL.md /tmp/elves/references /tmp/elves/scripts ~/.claude/skills/elves/
rm -rf /tmp/elves
```

**Codex:**
```bash
mkdir -p ~/.codex/skills/elves
git clone https://github.com/aigorahub/elves.git /tmp/elves
cp /tmp/elves/AGENTS.md ~/.codex/skills/elves/
cp -r /tmp/elves/references /tmp/elves/scripts ~/.codex/skills/elves/
rm -rf /tmp/elves
```

### Per-Project Installation

Per-project installation puts the skill in your repo so it's versioned with your code and visible to collaborators.

**Claude Code:**
```bash
# From your project root
mkdir -p .claude/skills
git clone https://github.com/aigorahub/elves.git .claude/skills/elves
rm -rf .claude/skills/elves/.git  # remove the nested git repo
```

**Codex:**
```bash
mkdir -p .agents/skills
git clone https://github.com/aigorahub/elves.git .agents/skills/elves
rm -rf .agents/skills/elves/.git
```

### Claude.ai (Upload)

1. Download or clone this repo
2. Zip the `elves/` directory
3. Go to Settings > Features > Skills > Upload
4. Upload the zip file

### Validating Your Installation

```bash
pip install -q skills-ref
agentskills validate ~/.claude/skills/elves/  # or wherever you installed it
```

You should see: `Valid skill: ...`

---

## Making It Your Own

**Elves is scaffolding, not a finished product.** It gives you the framework — the loop, the documents, the gates — but every project is different. You are going to need to customize it for your own purposes, and you are going to learn your own lessons along the way.

### What to customize first

**The survival guide template** is where most customization happens. When you generate a survival guide for your project, you'll fill in:
- Your specific test commands (not every project uses `npm run lint`)
- Your non-negotiables (what must never happen in your codebase)
- Your review method (PR comments, a custom API, manual checks)
- Your notification preference (Slack, email, PR comment)
- Your batch sizing (maybe your team is 2 people, not 4)

**The validation gates** will be different for every project. A Python data pipeline has different gates than a React web app. Edit the survival guide's `## Tool Configuration` section to match your stack. See [`references/tool-config-examples.md`](references/tool-config-examples.md) for examples across Node, Python, Go, Rust, and monorepos.

**The plan template** is a starting point. Some teams want more structure (acceptance criteria per batch, risk statements). Others want less (just a task list). Make the plan format work for how you think, not how the template thinks.

### What you'll learn by doing

The first time you run Elves overnight, you will discover things no template can predict:

- Which of your test suites is flaky and needs to be fixed before agents can rely on it
- Which commands in your toolchain prompt for input and need `--yes` flags
- How long your batches actually take (probably longer than you estimate)
- Where your plan was vague and the agent had to guess
- What non-negotiables you forgot to list

This is normal. After each run, read the execution log — especially the **Decisions made** sections — and update your survival guide template with what you learned. The skill gets better every time you use it because *you* get better at writing plans and configuring the harness.

### Editing your global installation

If you installed globally, your customized skill lives at:
- Claude Code: `~/.claude/skills/elves/SKILL.md`
- Codex: `~/.codex/skills/elves/AGENTS.md`

Edit these files directly. Add your own defaults, remove sections that don't apply to your work, add project-type-specific guidance. This is your copy — make it yours.

When you want to update from upstream (new features, fixes), pull the latest and merge manually:
```bash
git clone https://github.com/aigorahub/elves.git /tmp/elves-update
diff ~/.claude/skills/elves/SKILL.md /tmp/elves-update/SKILL.md
# Review the diff, merge what you want, skip what you don't
```

### Per-project overrides

If you have a global installation but one project needs different behavior, put a project-level copy in `.claude/skills/elves/` inside that repo. The project-level skill takes precedence over the global one.

This is useful when:
- One project uses Python while your default is Node
- A project has specific non-negotiables ("never touch the billing module")
- You want to experiment with a modified workflow without affecting other projects

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
