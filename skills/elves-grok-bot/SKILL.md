---
name: elves-grok-bot
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

Do not use `/goal` — that string is reserved for a possible future feature.

This is not Grok Build and not a coding host. No git, PR, or merge.

## Stage

Create one run. Give it a unique run id. Write four files under one folder named for that id. Put the folder path, run id, and reminder id in SURVIVAL and session.json. Every wake uses that exact path. Do not invent a second folder.

- **PLAN.md** — mission, scope, batches, M-A# acceptance, non-negotiables
- **SURVIVAL.md** — start with "READ THIS FIRST." Stop gate, next action, file paths
- **session.json** — `status` (`running` | `stopped` | `blocked` | `complete`), `stop_allowed: false` until every M-A# has proof, `run_id`, `reminder_id`, `active_fire`
- **LEDGER.md** — last item, last outcome, last record id, next action

Proof is a count, file, or record id. "The important ones are done" is not proof.

## Stop gate

Stay closed until acceptance is proven, unless `status` is already terminal.

Not a stop: a recap, the first slice, silence, "this is a lot," a natural pause, a quiet inbox.

Hard stop only: user said stop, auth is dead, or the next write would break a rule. On a hard stop, set `status` to `stopped` or `blocked` before you return, then delete that exact reminder. Every later fire that sees a terminal `status` exits without work.

Mid-run ping: answer in a few sentences and continue.

## Watchdog

One reminder only, every minute, around the clock (cron: `* * * * *`). Overnight unattended work is the point — the user may go to bed after kickoff. Persist the reminder id. Each fire: confirm run id and reminder id, then read survival → session → plan → ledger. If `status` is terminal, delete this reminder if it still exists and exit. If the gate is closed, do the next batch. Do not recap instead of working. When all M-A# are proven, set `status: complete`, recap once, and delete that exact reminder.

An interrupted fire (status error "Interrupted before it finished") is NOT a stop. Next fire continues from SURVIVAL/LEDGER after reconciling any in-flight item.

One fire at a time. If session.json `active_fire` is younger than two minutes, skip this fire. Otherwise set `active_fire` now, do one batch, then clear it. If LEDGER says a batch is in progress, continue that batch from the last proven record id. Do not start a parallel copy.

Before each send, CRM write, or post: write the item intent and a stable operation key to the ledger. After it lands, write the record id (Gmail message id, CRM id, file) before the next item. After an interrupt, look up that key remotely. Retry only when the remote side has no record. If the outcome is unknown, block and report; do not send again.

When a real batch or person lands, send a short progress note. Do not vanish into tool calls after announcing a step.

## Each wake

Read survival. If `status` is terminal, stop. Count remaining from files. Ship the next batch. Update ledger and session. If work remains, keep going.

Preflight logins before you walk away. Retry a failed worker; do not relaunch into an unchanged workspace. If the session died, report it — do not redo side effects.

No git/PR/merge. Grok Bot skill.
