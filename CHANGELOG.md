# Changelog

All notable changes to the Elves skill are documented here.

## [1.0.0] - 2026-03-21

### Core Skill

- Multi-batch autonomous execution with configurable batch sizing (default: 4 developers x 2-week sprint)
- Three-document compaction survival system (Plan, Survival Guide, Execution Log)
- Core loop: Orient → Tag → Implement → Validate → Review → Document → Update → Push → Re-read → Continue
- Subagent delegation strategy for long runs (Claude Code)
- Scout mode for bonus improvements after planned work is done
- Time-aware pacing with session budgets
- Rollback safety with `elves/pre-batch-N` git tags
- Structured session data in `.elves-session.json`

### Safety

- Forbidden Commands: `git reset --hard`, `git checkout .`, `git clean -fd`, `git push --force`, `git rebase` on shared branches
- Test Integrity: never modify a test to make it pass. Fix the code, not the test.
- Never Stop to Ask: non-interactive operation with `CI=true` and comprehensive env var hardening
- Mid-run check-in protocol: answer concisely, keep going

### Validation

- Two-stage validation: local gates then preview deployment
- Auto-discovery for Node.js, Python, Go, Rust, and Makefile projects
- Zero accumulated debt philosophy. Every batch must be production-ready.
- Headless app testing guidance

### Review

- GitHub PR comments as default review method (zero config)
- Custom review API support (opt-in)
- Additional checks: smoke tests, visual review, doc review, custom scripts
- Finding triage: genuine issues, intentional design choices, false positives

### Documentation

- README with origin story (The Shoemaker's Elves), Ralph Loop, Human Sandwich
- Installation guide: global and per-project for Claude Code, Codex, Claude.ai
- "Making It Your Own" customization guidance
- "What Can Go Wrong" failure modes table
- Preventing Sleep / Shutdown guide with caffeinate, systemd-inhibit, tmux/screen
- Monitoring with GitKraken and Slack notifications
- Claude Code SessionStart hook for automatic context loading
- Daily briefing and Friday planning cadence

### Templates

- Survival guide template with non-negotiables, tool config, and compaction recovery
- Execution log template with timing breakdown
- Plan template with worked example (auth system refactor)
- Kickoff prompt template (minimal and full versions)
- Tool configuration examples for Node, Python, Go, Rust, monorepos

### Scripts

- `preflight.sh`: 10-section preflight checklist (git, auth, project detection, sleep prevention, gates, notifications, env vars, branch staleness)
- `notify.sh`: Slack webhook, custom command, or PR comment notification helper

### Platform Support

- Claude Code (SKILL.md): full feature set with subagents
- Codex (AGENTS.md): all work done directly, concise format
- Claude.ai: zip upload
- Any Agent Skills compatible platform
