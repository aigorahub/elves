---
name: Elves
description: Unattended-run kernel for Grok Bot non-git work. Use when the user says "use elves" for a long unattended job with no PR/merge model.
license: MIT
compatibility: Grok Bot, Grok-assistant agents. Not for coding runs — use root SKILL.md for those.
metadata:
  author: John Ennis
  version: "1.0.0"
  argument-hint: Natural language "use elves"
---

# Elves (Grok Bot)

Files are memory. Chat is not. The user owns done. You own the middle.

## Stage

Write four files under a run folder:

- **PLAN.md** — mission, scope, batches, M-A# acceptance, non-negotiables
- **SURVIVAL.md** — start with "READ THIS FIRST." Stop gate, next action, file paths
- **session.json** — `stop_allowed: false` until every M-A# has proof
- **LEDGER.md** — last item, last outcome, next action

Proof is a count, file, or record id. "The important ones are done" is not proof.

## Stop gate

Stay closed until acceptance is proven.

Not a stop: a recap, the first slice, silence, "this is a lot," a natural pause, a quiet inbox.

Hard stop only: user said stop, auth is dead, or the next write would break a rule.

Mid-run ping: answer in a few sentences and continue.

## Watchdog

Reminder every 15 minutes, waking hours. Each fire: read survival → session → plan → ledger. If the gate is closed, do the next batch. Do not recap instead of working. When all M-A# are proven, recap once and delete the reminder.

## Each wake

Read survival. Count remaining from files. Ship the next batch. Update ledger and session. If work remains, keep going.

Preflight logins before you walk away. Retry a failed worker; do not relaunch into an unchanged workspace. If the session died, report it — do not redo side effects.

No git/PR/merge. Grok Bot skill.
