# E2E chat-to-work and chat-to-land (design)

## Natural entry

From either supported host, the smallest happy-path request is: “Implement this plan while I’m
offline; leave the PR unmerged.” Elves classifies the plan, recommends a separate
subscription-native worker by default, offers at most one remembered provider choice, binds a
proven native view or exact follow command before the driver parks, and returns to the capable driver for cumulative
review. Permitted Grok remains optional. See
[`adaptive-worker-routing.md`](adaptive-worker-routing.md).

**Status:** **recommended default user path.** Trusted Grok full-run delegation is the optional parked shape.
The current default uses a separate subscription-native worker, with optional permitted Grok or
another configured adapter. Classic **two-call stage-then-start** remains optional for huge or
unstable plans. A behaviorally qualified subscription-native route may optionally use
**exact-session prewalk**: the worker packet is still staged once, but the same worker session
orients, creates its TODO, makes the first real edit, and resumes on the execution route. See
[`prewalk.md`](prewalk.md).

**Product intent:** efficient, intelligent workflows for agentic development and research —
chat to conceptual agreement (optionally multi-planner), then **one prompt** runs plan + stage +
batches, without locking the user into one model ecosystem. Cobbler coordinates; Claude Code or
Codex is the main driver. User chooses **landable PR only** (chat-to-work) or **merge ceremony**
(chat-to-land).

**Why single kickoff:** requiring a separate human “stage” call often failed — incomplete staging
meant the overnight run never really started. The agent now owns staging quality; the human owns
intent and merge policy.

## Two user-facing prompts

| Mode | User outcome | Merge |
| --- | --- | --- |
| **Chat-to-work** | Plan + stage + implement + validate + review → **landable PR** | **Never** merge unless the user later opts in |
| **Chat-to-land** | Same as chat-to-work, then **reviewed-PR landing ceremony** through merge | Explicit opt-in in the kickoff (merge-commit only, never squash) |

Both modes may start from a **conversation** (not only a pre-written plan file). The host agent
still materializes a plan and full run docs on disk before unattended batches.

Internally, keep **stage then execute** as separate *phases* even when the user sends one message:
plan/docs/PR first, then batch loop. One *user* message is the recommended product path; coding
before launch-ready is still forbidden. After launch-ready in E2E mode, **continue into the batch
loop without waiting for a second human call.**

## Flow

```text
User chat (intent, constraints, non-negotiables)
    │
    ├─ optional multi-planner panel (Cobbler / OpenRouter / Gemini / …)
    │     re-chat if intent still fuzzy
    ▼
Host materializes plan + survival guide + learnings + execution log + session scaffold
    │
    ▼
Stage: branch, PR, Cobbler session state, Stop Gate, merge policy
    │
    ▼
Acceptance staging: derive/validate session rows from the plan; bind the exact worker packet
    │
    ▼
Preflight and launch-ready checks
    │
    ├─ optional: /goal (Codex) or host continuation harness (Claude Code)
    ▼
Execution route
    │
    ├─ host-native / legacy bounded driver:
    │    batch loop → validate → review → document → host push
    │    after each bounded return: labor completeness check
    │
    └─ separate trusted worker (native, Grok, or another configured adapter):
         one complete packet → one persistent launch → proven view or exact follow command
         worker implements, validates, and commits without host re-prompts
         qualified native prewalk: guide route → meaningful-edit checkpoint → same-session
         execution route with only `Continue.` (no driver transition approval)
         parked host wakes only on safety, blocked, or terminal events, then reviews cumulatively
    ▼
Readiness Gate (landable PR)
    │
    ├─ chat-to-work: STOP here (PR open, green, reviewed; user merges)
    └─ chat-to-land: reviewed-PR landing
         resolve PR → read review surfaces → Elves-routed Fugu review → host review
         → fix blockers → docs + conditional version bump → wait for checks → merge commit
         → worktree teardown
```

## Reviewed-PR landing ceremony (chat-to-land tail)

The landing ceremony is the same ordered sequence for chat-to-land and for an explicit
`\land-pr` / `/land-pr`. Canonical text: `SKILL.md` **Reviewed PR Landing Command** and
[`review-subagent.md`](review-subagent.md).

1. Resolve branch, PR, base, draft state, checks.
2. Read every review surface.
3. **Fugu review of the current PR diff, routed through Elves** — `/fugu review <scope>` in Claude
   Code, `$elves fugu review <scope>` in Codex, Grok Build, and Oh My Pi.
   **Hosts must not invent a raw Fugu call**: no direct `codex-fugu` or `claude-fugu` invocation,
   no improvised API request,
   no hand-built `run_fugu.sh` command line. **Skip only when Fugu is not installed**; record the
   skip. Fugu output is evidence, never landing authority.
4. Host review of `git diff <default-branch>...HEAD`, adjudicating every Fugu finding.
5. Fix blockers; push.
6. Update the docs the change touches, and bump the version when the repository versions. Elves
   itself versions. A repository with no version scheme skips the bump.
7. Wait for asynchronous reviewers and checks; re-read comments before deciding green.
8. `gh pr merge --merge` once every gate is clean; never squash or rebase.
9. Post-merge worktree teardown for the run's own recorded worktree.

## Run Control fields

Record in the survival guide `## Run Control` (and mirror in `.elves-session.json` when useful):

```markdown
## Run Control
- run mode: finite | open-ended
- e2e mode: chat-to-work | chat-to-land | off
- merge policy: never-merge | merge-commit-on-green | reviewed-pr-landing-command
- work driver: host-native | grok-build | opencode-cli | …
- delegation scope: none | batch | full_run
- driver monitor mode: interactive | parked_monitor | n_a
- driver update policy: default sanitized follow stream, no timed driver chat, material wakes only;
  unchanged healthy polls silent | interactive
- driver poll policy: host wait primitive | half stale window, bounded 60–300s | interactive
- driver review policy: final independent review only | per-batch
- labor re-drive budget: 3
- multi-planner: optional | required-for-plan
- continuation harness: none | codex-goal | host-native
```

Rules:

- **`chat-to-work`** ⇒ `merge policy: never-merge` (default). PR is for the human.
- **`chat-to-land`** ⇒ `merge policy: reviewed-pr-landing-command` (or merge-commit-on-green after
  Final Readiness). Regular **merge commit only**; never squash/rebase for this path.
- Missing optional multi-planner tools never blocks planning; fall back to host-native Cobbler.

## Continuation harness (`/goal` and friends)

Use platform continuation as a **seatbelt**, not as the source of truth:

- **Codex:** after stage (or as part of a single E2E kickoff), wrap the launch with `/goal` so the
  host keeps looping. Goal text must point at the survival guide Stop Gate and Readiness Gate.
  See [`codex-goals.md`](codex-goals.md).
- **Claude Code:** use the host’s long-run / goal-like features if available; otherwise rely on
  Elves open-ended mode + Stop Gate + “do not stop unless…” language in the kickoff.
- Elves memory files remain authoritative. Do not put the whole plan only inside the goal string.

## Labor completeness (work-driver laziness)

Grok Build and similar work drivers often **do some but not all** of a batch. That is a **host
defect** if accepted as “done.”

After every bounded work-driver return, or once at trusted full-run terminal/safety wake (before the
host accepts any reported batch as complete):

1. **Contract** — every acceptance criterion has concrete evidence (not narrative).
2. **Surfaces** — owned files in the packet were touched as required; forbidden paths untouched.
3. **Worker report** — trusted full-run v1 report/events validate at terminal wake; if a legacy
   bounded packet requires `.elves/runtime/implement/done/batch-N.json`, it exists and is coherent
   with the tip.
4. **Gates** — focused + agreed broad tests pass.
5. **Diff honesty** — no “status complete” with empty or off-contract diff.

If incomplete:

1. Write a **gap packet** (remaining criteria, files, commands, exact session id) that states
   what changed since the previous attempt — or the explicit line "workspace unchanged since the
   previous failed attempt — do not repeat the previous approach". The guard output below
   supplies the correct variant. When the wake was a worker death, hang kill, or
   missing/malformed completion, attach the bounded redacted salvage block
   (`cobbler_agents.py salvage tail --log <follow-log>`) as "Last observed worker output" —
   untrusted, never a completion report.
2. **Guard first:** record the failure fingerprint at classification time
   (`cobbler_agents.py redrive record-failure --batch <B#>`), then classify the candidate
   (`… redrive evaluate --batch <B#>`). `redrive_futile:workspace_unchanged` still consumes one
   unit of the labor re-drive budget, forbids relaunching the identical packet, and jumps
   straight to step 4. Fingerprint capture errors and over-cap trees always count as changed; a
   fingerprint failure can never manufacture futility.
3. Otherwise **re-drive** the same work driver (prefer exact session resume after interruption)
   up to `labor re-drive budget`. Do not turn a healthy trusted full-run into per-batch
   prompting.
4. If still incomplete (or futile): host finishes the gap **or** hard-stop with remaining
   contract listed.
5. Log every re-drive and every futile classification under **Decisions made** / execution log.

Never silently absorb a partial work-driver turn into batch `status: complete`.

## Multi-planner involvement

- **Before stage freezes the plan:** good time for independent plan/risk lenses.
- **After a bounded-driver return:** host and independent review lenses may review before the next
  bounded turn.
- **During a trusted parked full-run:** do not launch per-batch host review or planning chatter.
  Run independent cumulative review after terminal/safety wake.
- Planners are evidence, not authority; the host synthesizes one plan and owns canonical memory,
  protected refs, PR actions, final review, and merge. The exact registered trusted full-run worker
  may commit/push only its assigned feature branch.

## Relationship to existing modes

| Existing | Relationship |
| --- | --- |
| Stage then launch (two calls) | **Legacy / advanced** for huge or unstable plans; E2E is the default product path |
| Open-ended run | Compatible; chat-to-work often finite-to-Readiness |
| Reviewed PR landing / `\land-pr` | Used by **chat-to-land** at the end |
| Lane A implement / OpenCode labor | Optional work drivers under labor completeness |
| Math domain / AlphaEvolve | Same E2E shell; domain workflow still Cobbler-managed |

## Non-goals (for this design)

- Auto-merge without explicit kickoff language or Run Control opt-in
- Replacing Elves memory with only `/goal` text
- Treating work-driver session end as batch complete
- Requiring multi-provider setup for E2E (native-only E2E is valid)

## Kickoff templates

Copy-paste prompts: [`kickoff-prompt-template.md`](kickoff-prompt-template.md) sections
**Chat-to-work (E2E, no merge)** and **Chat-to-land (E2E through merge)**.

## Implemented v2.1 contract

- Survival-guide Run Control records E2E mode, delegation/Git/monitor policy, and re-drive budget.
- Before any worker launch, `acceptance_contract.py sync-session`/`validate` reconciles exact
  plan/session criterion text, exact normalized Batch sets, and the required session `run_id` plus
  exact 40-character `start_head`. Sync derives batch and Master Acceptance rows symmetrically and
  may migrate an exact legacy `collision_tripwire` to `start_head` without touching evidence.
  Trusted full-run prepare receives
  the canonical `--session` (or the repo-root `.elves-session.json`) and immutably binds that
  plan/session mapping to the packet;
  use the exact recipe in [`grok-implementer-launch-prompt.md`](grok-implementer-launch-prompt.md).
- Legacy `implement gate` and the trusted full-run supervisor validate acceptance/report evidence.
- Trusted full-run uses one packet/session, `branch_progress`, bounded events/report, a parked host,
  and cumulative terminal review; legacy bounded re-drive remains available after an actual return.
- Chat-to-work and chat-to-land share staging/readiness and differ only in explicit merge authority.
- Final Completion follows the committed-evidence sequence in
  [`schema-and-acceptance.md`](schema-and-acceptance.md): commit the session, run the strict landing
  check and terminal readiness, then remove operational run memory and attest the cleanup tip.

---

*Elves v2.1 contract under Cobbler; classic stage-then-start remains available when the plan is
still unstable.*
