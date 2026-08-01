# Historical Plan (Superseded): Smart Plan → Grok Build Implement

## Status

**Superseded by Elves v2.1.0 trusted full-run. Do not execute the per-batch handoff loop below.**
The current normative contract is
[`references/grok-implementer-launch-prompt.md`](../../references/grok-implementer-launch-prompt.md):
one self-contained packet, one exact worker session, one launch, feature-branch progress, and a
`parked_monitor` host until a terminal/safety wake. This document is retained as design history for
the failure mode that motivated that contract.

Historical design goal:

> Plan with smart agents. Turn the work over to Grok Build. Stay safe. Do not take forever.

Derived from the v1.20.1 run failure mode: Codex driving Grok as a nested headless worker with
full host ceremony between every turn was orders of magnitude slower than opening Grok Build as a
real coding agent in the same terminal.

This is **not** a rejection of the untrusted-writer boundary. It is a separation of two different
jobs that v1.20.0/v1.20.1 collapsed into one expensive loop.

## Problem statement

### What we want

1. Smart models (Codex / Claude Fable / Fugu Ultra / host) do high-judgment work:
   planning, architecture, contracts, risk, acceptance criteria, final review.
2. Grok Build does volume implementation:
   code, tests, commits, local validation, iteration inside a batch.
3. The user sees progress on a PR and can leave overnight.

### What went wrong

Codex treated Grok as a **remote procedure call**:

```text
host packet → spawn/resume Grok headless → wait → audit everything → full suite →
multi-model review → export patches → host commits → rewrite docs → repeat
```

That architecture guarantees:

- Grok cold-start and permission thrash (`dontAsk` cancel, then `auto`)
- constrained turns (`--no-subagents`, high reasoning, tiny remediations)
- host tax between every Grok thought (audit, 300+ tests, review, import, survival guide)
- wall time dominated by **ceremony**, not Grok

When the human opened Grok Build interactively, that outer loop disappeared. Grok was fast because
it was allowed to be a coding agent again.

### Diagnosis in one line

**Safety should gate batches, not breaths.**
**Grok should hold a persistent implementer session, not be re-invoked like a slow API.**

## Product model (two lanes)

### Lane A — Fast implementer (default for “turn it over to Grok”)

Use when the goal is shipped code overnight and Grok is trusted enough as a coding agent inside a
bounded worktree.

```text
Smart host (Codex/Claude)                 Grok Build (implementer)
─────────────────────────                 ────────────────────────
plan + Survival Guide + PR
batch contracts + acceptance
stage worktree / branch
write ONE launch packet  ───────────────►  resume exact session
                                           implement whole batch
                                           test locally
                                           commit progress slices
                                           push OR hand back tip
fast batch gate (native+tests) ◄────────── report done / blocked
next batch packet ──────────────────────►  resume same session
...
final readiness (smart review) ◄────────── all batches
merge/tag (host or authorized)
```

Rules for Lane A:

1. **One exact persistent Grok session** for the whole run (`--resume <uuid>`).
2. **One substantial batch per handoff**, not micro-tasks.
3. **Grok keeps subagents and normal coding permissions** (`auto` / `acceptEdits` as configured).
   Never default headless to `dontAsk`.
4. **Host does not audit mid-batch** unless Grok asks or a hard safety tripwire fires.
5. **Between-batch gate = fast native review + deterministic tests** (see adaptive-review plan).
6. **Git ownership is configurable** (see modes below). Default for speed: Grok commits on the
   feature branch in a dedicated worktree the host created; host still owns merge/tag/release.

### Lane B — Untrusted writer (strict, when needed)

Use when the implementer must not own refs/push, or when proving the repaired lease boundary.

This is the v1.20.x worker lease path:

```text
prepare lease → Grok detached commits → audit → export patches → host import → review
```

Keep Lane B. Do **not** use it as the default “turn work over to Grok” path. It is a high-assurance
integration path, not the overnight speed path.

**Product rule:** Survival Guide `implementation_lane: fast | untrusted`. Default `fast` when the
user says “have Grok run it.” Use `untrusted` when the user says “prove the writer boundary” or
when implementing the lease/runtime itself.

## Modes of git ownership (Lane A)

### Mode A1 — Grok owns feature-branch progress (recommended default)

Host:

- creates worktree + branch + PR
- writes plan, Survival Guide, launch packet
- does not rewrite Grok’s commits mid-batch

Grok:

- works in that worktree
- commits with Elves subject schema
- pushes progress slices
- updates execution log / session JSON only if the launch packet assigns those docs (optional)

Host returns at batch boundary for gate + next packet, or only at final readiness.

**Why this is fast:** matches “open Grok in the terminal.” No patch import. No double git history.

### Mode A2 — Grok detached, host imports at batch end only

Host:

- keeps branch tip ownership
- imports once per batch (not per amend)
- runs suite once per batch close

Grok:

- still one persistent session
- may create several detached commits inside the batch
- host does one audit/export/import at batch end

**Why still OK:** import tax paid **once per batch**, not once per remediation turn.

### Mode A3 — Smart host stays coordinator every turn (anti-pattern for this goal)

This is what hurt. Forbidden as the default for “turn work over to Grok.”

## Persistent Grok session contract

### Create once

```bash
# Host creates implementer worktree and starts exact session
grok --session-id <uuid> \
  --cwd <worktree> \
  --model grok-4.5 \
  --permission-mode auto \
  --reasoning-effort high \
  "Read the launch packet at <path>. Do not start coding until you restate the contract."
```

Record in `.elves-session.json`:

```json
{
  "implementation": {
    "lane": "fast",
    "adapter": "grok-build",
    "session_id": "<uuid>",
    "model": "grok-4.5",
    "worktree": "../elves-<branch>-grok",
    "permission_mode": "auto",
    "subagents": true,
    "git_mode": "branch_progress"
  }
}
```

### Resume for each batch (not each bug)

```bash
grok --resume <uuid> --cwd <worktree> --permission-mode auto \
  --prompt-file .elves/runtime/packets/batch-N.md
```

Packet contents (file on disk, not a chat essay):

1. batch name / why
2. Build On (paths + patterns)
3. owned / forbidden surfaces
4. acceptance criteria with evidence form
5. validation commands
6. commit subject prefix and phase labels
7. stop conditions and what to write back to host

### What Grok may do in Lane A / Mode A1

- edit owned product surfaces
- run focused + full tests
- commit and push on the feature branch
- update execution log entries if assigned
- open no second PR; no merge; no tag

### What Grok must not do

- edit Survival Guide stop policy / merge authorization unless host assigned
- merge to main
- touch credentials
- declare batch `status: complete` without acceptance evidence rows (host may own session JSON)

## Host responsibilities after handoff

Smart host is **not idle**, but it is **not in the inner loop**.

| Moment | Host does | Host does not |
|--------|-----------|----------------|
| Staging | plan, PR, worktree, session create, launch packet | implement |
| During batch | optional async PR comment glance | re-drive every Grok tool call |
| Batch end | fast gate: tests + one native review | multi-model council by default |
| Failure | write one remediation packet; resume same session | start a new Grok identity |
| Final | cumulative review, live matrix if required, merge if authorized | re-implement |

## Making headless Grok as fast as interactive Grok

 empirically required settings for the implementer session:

| Setting | Value | Why |
|---------|-------|-----|
| Permission | `auto` or `acceptEdits` | `dontAsk` cancelled first turn in v1.20.1 |
| Subagents | enabled | interactive Grok uses them; `--no-subagents` cripples |
| Unit of work | whole batch | micro-packets force host re-entry |
| Prompt delivery | `--prompt-file` packet | stable, resumable, not chat-lossy |
| Reasoning | high for hard batches; default for routine | don’t tax every docs fix |
| Session | exact UUID resume for entire run | preserve cache/context |
| Validation inside batch | Grok runs tests itself | host suite once at gate |
| Review inside batch | none by Grok of its own work | host gate at boundary |

Optional accelerators:

- **tmux / leader session**: keep Grok process warm between host checks
- **`grok --continue` only when UUID unknown** — prefer exact resume
- **Structured done report** at end of batch (`json-schema`) so host can parse acceptance without rereading transcripts

## Cobbler / Elves surface changes (implementation plan)

### Batch 1 — Document and default the two lanes

- Survival Guide / SKILL / AGENTS: `implementation_lane: fast | untrusted`
- CouncilElves launch prompt split into:
  - `references/councilelves-launch-prompt.md` (orchestration overview)
  - `references/grok-implementer-launch-prompt.md` (Lane A packet + resume)
  - keep untrusted writer prompt as advanced
- Learnings: “do not use untrusted lane as default overnight path”

### Batch 2 — Operator CLI: `implement prepare|launch|gate|resume-batch`

Add host commands that encode the fast path:

```bash
python3 scripts/cobbler_agents.py implement prepare \
  --branch <b> --worktree <path> --model grok-4.5

python3 scripts/cobbler_agents.py implement launch \
  --session-id <uuid> --packet .elves/runtime/packets/batch-1.md

python3 scripts/cobbler_agents.py implement gate \
  --batch 1   # runs tests + records tip; optional native review hook

python3 scripts/cobbler_agents.py implement resume-batch \
  --batch 2 --packet .elves/runtime/packets/batch-2.md
```

`launch` prints or execs the exact `grok --resume ... --prompt-file ...` command.
It does **not** wrap Grok in a second agent loop by default.

### Batch 3 — Packet format + done schema

- Versioned markdown/JSON packet under `.elves/runtime/packets/`
- Optional JSON done report schema: `{batch, commits[], tests, blockers[], acceptance[]}`
- Host gate reads done report; fails closed if missing when required

### Batch 4 — Wire adaptive review as between-batch gate only

Depends on / pairs with `docs/plans/adaptive-planner-directed-review.md`.

- Default between-batch: fast native + deterministic
- Final readiness: full cumulative + optional smart external reviewers
- Grok never reviews itself

### Batch 5 — Procedure tests

Prove:

1. Smart host stages; Grok implements batch 1 in Mode A1; host gate green without patch import.
2. Same session resumes batch 2 with retained context (not a new UUID).
3. Untrusted lane still works for a disposable canary (regression).
4. `dontAsk` is not the default headless permission.
5. Timing budget: host wall time outside Grok turns is mostly staging + gates, not mid-batch thrash.

## Recommended operator workflow (today, before more code)

Even without Batch 2 CLI, do this manually:

1. **Smart agent stages** (Codex/Claude): plan, Survival Guide, PR, worktree, collision tripwire.
2. **Smart agent writes** `batch-1` packet file (complete handoff standard).
3. **Human or host launches Grok** in that worktree:

   ```bash
   cd <worktree>
   grok --resume <uuid> --permission-mode auto --prompt-file .elves/runtime/packets/batch-1.md
   ```

4. **Leave Grok alone** until the batch packet is done or blocked.
5. **Smart agent returns** only for gate + next packet, or for final readiness.

Do **not** have Codex “drive” Grok tool-call by tool-call. That recreates the slow path.

## Non-goals

- Replacing Cobbler or Elves with a Grok-only system
- Making external providers mandatory
- Softening untrusted-lane safety when Lane B is explicitly selected
- Multi-model between-batch councils as the default (adaptive review plan already forbids this)

## Success metrics

| Metric | Target |
|--------|--------|
| Host interventions per batch | 1 launch + 1 gate (plus remediations only on real blockers) |
| Grok session count per run | 1 |
| Mid-batch full-suite host runs | 0 by default |
| Patch-import events (Lane A1) | 0 |
| Patch-import events (Lane A2) | 1 per batch |
| Time-to-first-Grok-edit after launch packet | interactive-comparable (seconds–low minutes), not multi-reviewer hours |
| Safety | no merge/tag by worker; no secret leakage; stop gate still host-owned |

## Decision record

| Decision | Choice | Why |
|----------|--------|-----|
| Default lane for “Grok runs it” | Fast implementer (A) | Matches desired UX and observed speed |
| Default git mode | A1 branch progress | Avoids import tax; PR shows live progress |
| Keep untrusted lane | Yes, explicit opt-in | Needed for runtime self-repair and high-assurance |
| Who reviews | Host/native fast mid-run; smart models at final | Adaptive review cost principle |
| Who plans | Smart models | Judgment and contracts |
| Who implements | Persistent Grok Build session | Volume and speed |
| Unit of handoff | Whole batch | Stops breath-level host tax |

## Next move

1. Accept this plan (or edit the default lane/git mode).
2. Stage a small Elves run that implements Batches 1–3 of **this** plan (docs + CLI + packet schema).
3. Dogfood: smart-host stage a toy product batch; Grok implements via Lane A1; measure wall time vs the nested driver.

## Related

- [`lane-a-productize.md`](lane-a-productize.md) — productize PR that ships the implement CLI + skill
  surfaces for this design (docs + operator UX, not adaptive runtime)
- [`adaptive-planner-directed-review.md`](adaptive-planner-directed-review.md) — between-batch cost
  control (design only; runtime is future work)
- [`v1.20.1-cobbler-runtime-hardening.md`](v1.20.1-cobbler-runtime-hardening.md) — untrusted lane
  truthfulness (Lane B)
- [`references/grok-implementer-launch-prompt.md`](../../references/grok-implementer-launch-prompt.md)
  — measured Lane A launch recipe (`--prompt-file --yolo --effort medium`)
- [`references/councilelves-launch-prompt.md`](../../references/councilelves-launch-prompt.md) —
  two-lane orchestration overview
- Execution evidence: Codex session driving Grok for v1.20.1 Batch 1 vs interactive Grok speed
