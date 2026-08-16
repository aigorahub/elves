---
name: Long-running job
description: Unattended-run kernel for Grok Bot non-git work. Use for outreach, CRM enrichment, data migration, or other long-running jobs that have no PR/merge model. Stages a run folder with plan, survival guide, acceptance ledger, and progress log; enforces a Stop Gate until acceptance is proven on disk; recognizes only hard stops; wakes every 15 minutes until complete.
license: MIT
compatibility: Grok Bot, Grok-assistant agents. Not for coding runs — use root SKILL.md for those.
metadata:
  author: John Ennis
  version: "1.0.0"
  argument-hint: Natural language "run this as a long-running job" or Grok Bot workflow named "Long-running job"
---

# Long-running job

A portable unattended-run kernel for **Grok Bot / Grok-assistant agents** doing long-running
non-git work: HubSpot enrichment, Gmail outreach, LinkedIn prospecting, data migration, or other
side-effect labor with no PR/merge/worktree model.

This is **NOT** a replacement for the Elves coding workflow in the root `SKILL.md`. That skill
remains authoritative for Claude Code, Codex, Grok Build, and Oh My Pi code runs with branches,
PRs, and landing. This portable kernel is for **Grok Bot outreach and CRM work only**.

## Why This Exists

Last night an outreach agent stopped after a "high-signal HubSpot slice" and treated ~1500
contacts as "done." That stop was forbidden. Every acceptance criterion must be checkable on disk
with proof (count, file, CRM record id, Gmail message id). "I think I did it" and "the important
ones are done" are not acceptance.

This skill encodes the **continuity watchdog** from Elves without the git/worktree/PR/merge
apparatus: four files, a Stop Gate that stays closed until acceptance is proven, and a 15-minute
waking-hours routine that keeps the job moving. No git collision tripwires, no `gh pr merge`, no
landing checks — only mission, plan acceptance, the stop gate, and file-backed memory.

## When to Use

Use this skill when:

- The work is **non-git** (no branch, no PR, no merge decision)
- The job is **long-running** (multi-hour, could span multiple waking sessions)
- **Acceptance must be proven on disk** (not "it looks done")
- The job has **side effects** (sends emails, writes to HubSpot, posts to LinkedIn, updates a CRM)
- You need **forbidden-stop enforcement** (no stopping for "useful summary", "first slice done",
  "remaining work feels like a lot", "inbox is quiet", "user silent or offline")

Do NOT use this skill for:

- Coding work with branches and PRs → use root `SKILL.md`
- One-shot tasks that complete in under 30 minutes
- Exploratory research with no side effects
- Work where partial completion is acceptable

## Host Check

This kernel is for **Grok Bot** and **Grok-assistant agents** only. It is NOT for Claude Code,
Codex, Grok Build main-driver coding runs, or Oh My Pi `omp` coding runs. Those hosts should use
the root `SKILL.md` workflow unchanged.

If you are a Grok Bot agent and the user asks to "run this as a long-running job" or invokes the
"Long-running job" workflow, proceed with staging below.

## Staging: Four Files Before Walking Away

All questions happen in **preflight**. After start: decide, log, keep moving.

Before the user goes offline, stage these four files in a run folder
(`/workspace/<run-slug>/` on Grok Bot):

### 1. PLAN.md

```markdown
# Plan: [Mission Name]

## Mission
[One sentence: what outcome, for whom, measured how]

## In Scope
[Concrete deliverables this run will produce]

## Out of Scope
[Adjacent work that this run will NOT do]

## Batches
Each batch is independently verifiable.

- **Batch 1:** [concrete outcome, with count or proof target]
- **Batch 2:** [concrete outcome, with count or proof target]
- ...

## Master Acceptance (M-A#)

These must ALL be proven before stopping.

- [ ] **M-A1:** [checkable criterion, e.g. "500 HubSpot contacts enriched with proof file"]
- [ ] **M-A2:** [checkable criterion, e.g. "Gmail sent log contains 200 sent message IDs"]
- [ ] **M-A3:** [checkable criterion]

## Non-Negotiables

- No duplicate sends
- Wrong list = hard stop
- Destructive write without confirmation = hard stop
- [job-specific constraints]
```

**Mission** is one sentence. **Acceptance rows** use stable `M-A#` ids; each must be checkable
with disk proof (file, count, CRM record id, message id). "I think I sent them all" is not proof.

### 2. SURVIVAL.md

```markdown
# Survival Guide: [Mission Name]

**READ THIS FIRST AFTER ANY WAKE**

## Run Control

- **Status:** running
- **Stop Gate:** CLOSED (opens only when all M-A# rows proven)
- **Next Required Action:** [exact next step, e.g. "process batch 2: contacts 101-200"]

## Stop Gate

`stop_allowed = false` until every Master Acceptance row is proven.

**Forbidden stop reasons:**
- Useful summary
- High-signal / first slice done
- User silent or offline
- Remaining work feels like a lot
- Natural pause
- Reminder fired
- Inbox/queue is quiet

**Only Hard Stop reasons are allowed:**
- User said stop
- Required auth is dead (HubSpot, Gmail, LinkedIn, etc.)
- Next action would violate a non-negotiable

## Single Next Action

[exact command or step; rewritten after every milestone]

## Plan Acceptance Evidence

Track disk proof for every M-A# row here.

- **M-A1:** [criterion] → not yet met
- **M-A2:** [criterion] → not yet met
- **M-A3:** [criterion] → not yet met

## Active Compute / Logins

[list what external services/APIs are in use; confirm in preflight]

## Progress Notes

[short append-only log of completed batches; one line per batch]
```

This is **live metadata**. Rewrite `Run Control`, `Single Next Action`, and `Plan Acceptance
Evidence` in place every milestone. Do not append old values — replace them.

### 3. session.json

```json
{
  "run_slug": "outreach-2026-08-16",
  "mission": "[one-sentence mission]",
  "status": "running",
  "continuation_guard": {
    "stop_allowed": false
  },
  "next_required_action": "[exact next step]",
  "acceptance": [
    {
      "id": "M-A1",
      "criterion": "[checkable acceptance criterion]",
      "met": false,
      "evidence": ""
    },
    {
      "id": "M-A2",
      "criterion": "[checkable acceptance criterion]",
      "met": false,
      "evidence": ""
    }
  ],
  "last_wake_at": "2026-08-16T07:14:00Z"
}
```

Update `met` and `evidence` when you prove an acceptance row. Set `continuation_guard.stop_allowed`
to `true` only when every row is `met: true`.

### 4. LEDGER.md

```markdown
# Progress Ledger: [Mission Name]

## Last Item

[concrete last item processed, e.g. "HubSpot contact #472, Acme Corp"]

## Last Outcome

[success/failure/partial for that item]

## Next Exact Action

[exact next step: "process contact #473" or "send batch 3 emails: list row 201-250"]

## Milestones

- 2026-08-16 07:30 — Batch 1 complete: 100 HubSpot contacts enriched
- 2026-08-16 09:15 — Batch 2 complete: 100 more contacts enriched
```

Refresh every milestone. This is the file you read first after any wake.

---

## Preflight: Confirm Before Launch

Before the user goes offline, confirm:

1. **Logins work:** HubSpot API key, Gmail OAuth, LinkedIn session, or whatever the job needs
2. **Rate limits understood:** know the API quotas and batch sizes
3. **Rollback plan:** if a batch fails, how do you detect and skip duplicates?
4. **Proof collection:** where will evidence land? (file path, CRM field, message ID log)
5. **Non-interactive mode:** all tools must run without prompts or confirmation dialogs

Write the confirmed details into `SURVIVAL.md` under `## Active Compute / Logins`.

---

## Acceptance Must Be Checkable on Disk

Every Master Acceptance row must be provable with **on-disk evidence**:

- HubSpot contacts enriched → proof file with contact IDs and timestamps
- Gmail messages sent → sent log with message IDs
- LinkedIn posts published → post URLs or API response log
- Data migrated → count in destination plus sample record IDs

"I think I did it" is not acceptance. "The important ones are done" is not acceptance. If you
cannot point at a file, count, or CRM record that proves the criterion, the row is not met.

---

## Stop Gate: Closed Until Every M-A# Proven

`stop_allowed` stays `false` in `session.json` until every acceptance row is `met: true` with
evidence.

**A final recap is forbidden while the gate is closed**, except a short progress note when a real
batch landed.

### Forbidden Stop Reasons

You MAY NOT stop for:

- Useful summary
- High-signal / first slice done (the 1500-contact failure)
- User silent or offline
- Remaining work feels like a lot
- Natural pause
- Reminder fired
- Inbox/queue is quiet

These are not stop reasons. Keep working.

### Hard Stop Reasons

You MUST stop for:

- User said stop
- Required auth is dead (HubSpot token expired, Gmail OAuth revoked, LinkedIn session invalid)
- Next action would violate a non-negotiable (wrong list, duplicate send, destructive write)

When a hard stop happens, update the four files, explain why in `SURVIVAL.md` under `Run Control`,
and halt.

---

## Watchdog: 15-Minute Waking-Hours Routine

Create a **standing reminder** that fires every 15 minutes during waking hours (7am–8pm local
time). On Grok Bot, describe this as a routine or reminder, not a tool call.

Cron-style schedule: `14,29,44,59 7-20 * * *` (minute 14/29/44/59, hours 7–20).

**Each fire:**

1. Read `SURVIVAL.md` → `session.json` → `PLAN.md` → `LEDGER.md`
2. If `stop_allowed` is `false`, continue the next batch immediately
3. Do NOT recap instead of working
4. If the session looks dead (same last item for 90+ minutes), detect-and-report; do NOT blindly
   redo side effects (no auto-resend)
5. When all M-A# proven, set `stop_allowed` to `true`, send final recap, **delete the reminder**

---

## Wake Protocol: Files Are Memory

After any compaction, fresh turn, or reminder fire:

1. Read `SURVIVAL.md` **first** (it says "READ THIS FIRST AFTER ANY WAKE")
2. Count remaining work from **files**, not memory
3. Ship the next batch
4. Refresh `LEDGER.md` + `SURVIVAL.md` + `session.json`
5. If work remains, start the next batch without waiting

Files are memory. Trust them over recollection.

---

## Mid-Run User Ping: Ride-Along

If the user checks in mid-run:

- Answer in **a few sentences**
- Incorporate any new information
- Continue immediately

Only an **explicit stop** halts. User silence, "looks good", or "checking in" are not stop signals.

Users may prefix messages with **`ra:`**, **`ride-along:`**, or **`[ride-along]`** to mean
"handle this and keep going." These are optional on Grok Bot; the rule is the same either way:
acknowledge, incorporate, continue.

---

## Transient vs Substantive Failure

### Transient Tool Failures

Retry the same task with backoff (5m → 10m → 20m):

- HubSpot API 500 error
- Gmail rate limit
- LinkedIn transient timeout

Do NOT relaunch into an unchanged workspace. Back off, wait, retry the exact same batch.

### Substantive Failures

These are NOT transient:

- Auth is dead (token expired, OAuth revoked)
- API returns 403 Forbidden
- The wrong list was targeted
- A non-negotiable was violated

Stop, update `SURVIVAL.md` under `Run Control`, and report.

---

## Continuity: Files, Not Chat

After compaction or a new turn:

1. Read the four files (`SURVIVAL.md` first)
2. Trust their state over your memory
3. Resume from `next_required_action`

Do not replay work already logged. Do not guess where you left off. The files know.

---

## What Does NOT Transfer From the Coding Skill

This kernel is **NOT** the full Elves coding workflow. It omits:

- **No worktrees, branches, PRs, or merge authority**
- **No `gh pr merge` or landing checks**
- **No git collision tripwires or protected refs**
- **No review subagents or confidence-guided review**
- **No Cobbler, Council, Fugu, Manus, Devin, or external worker routing**
- **No prewalk, no worker packets, no route-worker decisions**
- **No CI gates, no lint/typecheck/test validation**

Only the **continuity watchdog** transfers: files, stop gate, forbidden stops, wake protocol, and
the 15-minute reminder.

For coding work with branches and PRs, use the root `SKILL.md`. For long-running non-git outreach
and CRM work, use this skill.

---

## Summary: The Kernel

1. **Staging:** Four files (PLAN, SURVIVAL, session.json, LEDGER) before walking away
2. **Preflight:** Confirm logins, rate limits, proof collection, non-interactive mode
3. **Acceptance:** Checkable on disk with proof (no "I think I did it")
4. **Stop Gate:** Closed until every M-A# proven
5. **Forbidden stops:** useful summary, first slice done, user silent, work feels like a lot,
   natural pause, reminder fired, inbox quiet
6. **Hard stops:** user said stop, auth dead, non-negotiable violated
7. **Watchdog:** 15-minute waking-hours routine; delete when gate opens
8. **Wake:** Read SURVIVAL first, count from files, ship next batch, refresh ledger/survival/session
9. **Ride-along:** Answer in a few sentences, incorporate, continue
10. **Transient failures:** Retry with backoff; substantive failures stop

Match the Elves voice: short, normative, fail-closed. Trust files over memory. Keep moving.
