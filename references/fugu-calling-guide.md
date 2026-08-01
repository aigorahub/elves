# Calling Fugu effectively (host-agent guide)

Companion to `references/provider-shortcuts.md`, which is authoritative on the Fugu
**contract** (profiles, isolation policy, safety, transport) and the short **Host routing
when the user says "use Fugu"** decision path. This file covers how a **host agent should
place the call** so the run produces a usable answer instead of a dead lane.

Written from two real review runs on a 2,600-line refactor diff: one that burned its full
budget and returned no findings, and one that returned an ordered P0-P3 report with two
genuine regressions. The difference was entirely in how the call was placed. Cross-checked
against 2026 Claude Code / Codex agent practice (scope the task, goal + constraints +
done-when, separate research from implementation, verify before acting) and public Fugu
operator notes (Ultra is slow; do not max everything).

## The one-line version

Do not pipe a Fugu run through `tail`. Prefer plain for work that finishes inside the wall.
When the run **must** produce a written answer after heavy exploration, use a profile that
reserves synthesis (`--ultra` / `--max`). Tell the model its budget is finite.

## 1. Capture the output raw, never through `tail`

Fugu streams as it works: tool calls, files read, reasoning. That stream is the only
progress signal a host agent gets, and it is also the only record that survives, because
the isolation lane is deleted on completion (`cleanup` / `shutil.rmtree` in
`scripts/cobbler_runtime/isolation.py`). There is no log to recover afterwards.

A host agent that runs the launcher in the background and pipes it through `tail -N`
destroys that signal. `tail` cannot emit anything until its input closes, so the capture
file stays at **zero bytes for the entire run** and then dumps the last N lines at exit. If
the run is killed on timeout, what lands is whatever `tail` happened to be holding: an
exploration trace with no conclusions.

    # Wrong: silent for 20 minutes, then a truncated trace
    run_fugu.sh --deep review "..." 2>&1 | tail -200

    # Right: the file grows live and can be read mid-run
    run_fugu.sh --deep review "..." > fugu-review.log 2>&1

Read the log while the run is in flight. Two things are worth watching for:

- **Which files it is opening.** If it is 10 minutes in and still reading unrelated
  source, the scope was too broad and the run will not reach a report. Kill it and
  re-place the call rather than paying for the rest.
- **Whether it is looping.** Repeated reads of the same file are a sign the prompt did not
  give it a decision to make.

If the host wants a single completion notification rather than a live view, that is a
reason to background the process, not a reason to pipe it. Redirect to a file and watch
the file.

## 2. Profile choice is about the report, not about depth

The four profiles split into two structurally different execution shapes, and the split is
not the one the names suggest.

| Profile | Model / effort | Default wall | On timeout |
|---|---|---|---|
| plain | `fugu` / high | 600s | killed, **nothing returned** |
| `--deep` | `fugu` / xhigh | 1200s | killed, **nothing returned** |
| `--ultra` | `fugu-ultra-v1.1` / high | 1800s | synthesis phase still runs |
| `--max` | `fugu-ultra-v1.1` / max | 3600s | synthesis phase still runs |

(Walls are `DEFAULT_MAX_WAIT` in `scripts/run_fugu.sh`.)

Plain and `--deep` are **one-shot ephemeral sessions**. When the wall expires the lane is
terminated with `SystemExit(124)` and the result is rejected. The model does not get told
"time is up, write what you have." Everything it worked out is lost.

`--ultra` and `--max` reserve part of the budget up front:

    synthesis_floor = min(60.0, max_wait / 3.0)
    max_explore_wait = max_wait - shutdown_budget - synthesis_floor

When exploration ends, the **same session** is re-prompted with tools forbidden and told to
write its output. That reservation is why an ultra run returns findings even when it used
every second of exploration it was given.

**So: choose by whether the run must produce a written deliverable, not by how hard the
problem is.** A narrow question that fits the wall: plain first (or plain + `--max-wait`).
A review or audit that ends in a ranked report after heavy reading: `--ultra`, with a
tight prompt. Plain or `--deep` are for work that will comfortably finish inside its wall,
where being killed at the boundary means the task was mis-scoped anyway.

This does not cancel economy routing in `provider-shortcuts.md`: still host-native first,
still first paid call plain for finishable work, still no open-ended `--max`. The synthesis
rule only upgrades when the **report itself** is the product and plain/deep would die empty.

Upgrading `--deep` to `--ultra` is not "spending more" in the way it looks. A `--deep` run
that times out spends its whole budget and returns nothing, which is the most expensive
possible outcome.

## 3. Raise the wall deliberately, and separately from the profile

`--max-wait SECONDS` (or `SAKANA_FUGU_MAX_WAIT_SECONDS`) caps the hard wall clock for a
single launch, independent of profile. Prefer it over upgrading the profile when the task is
narrow but the default wall is too short. Upgrading the profile changes the model and the
effort as well as the clock; `--max-wait` changes only the clock.

Note what the wall covers: exploration, the reserved synthesis phase, and cleanup. It is a
true wall-clock bound, not an idle timeout, so a run that keeps emitting heartbeats is still
bounded (see the "Wall limits here are wall limits" note in `provider-shortcuts.md`).

Use `--preflight` to validate launcher, profile, wall, write eligibility, and `--include`
paths and print the launch plan without calling the provider. Cheap way to confirm the call
is shaped the way you meant before spending a budget on it.

## 4. Write the prompt against the budget

A Fugu review prompt is not a wish list. The model has a finite wall and no way to know it
unless told, so an unranked "review everything" invites it to explore until it is killed.

The run that failed asked for a full review of a 2,600-line diff across correctness,
regressions, physics, netcode, and test gaps, with no ordering. The run that succeeded added
four things, and returned an ordered report inside the same wall:

1. **State the budget problem explicitly.** "A previous run at this profile spent its whole
   budget reading files and produced no findings. Read selectively and reserve time to write
   the report. The report is the deliverable; an incomplete report beats none."
2. **Rank the areas.** A numbered priority list, most valuable first, so a run that runs
   short still covers what matters.
3. **Exclude what is already handled.** "Already found and fixed by the reviewer, do not
   re-report: ..." Every finding the host already has is budget the model should not spend.
4. **Name the output shape.** Ordered P0-P3, exact `file:line`, a concrete failure scenario
   per finding, and an explicit statement when a priority level turned up nothing.

Point 4 earns its place twice: it makes the findings checkable, and "say so if you find
nothing at a level" converts silence into information. The successful run closed with a
"priority-area checks with no additional finding" section that was genuinely useful, because
it told the host which suspicions had been examined and dismissed rather than skipped.

## 5. Verify findings before acting on them

Fugu findings are leads, not verdicts. Both real findings in the successful run were correct
and both needed independent confirmation against the current code before the fix was right:
one claimed a regression that was only a regression because of what an earlier batch had
deleted, and the other was reachable only under a condition the report did not name
(a rotated frame, which needed `SPIN` enabled).

Read the cited `file:line`, reproduce the reasoning, and decide the fix yourself. The
"smallest safe repair" a report proposes is a suggestion from something that has not seen
the rest of the system: in one case the proposed repair was a new state machine, where
reusing an existing pause path was smaller and matched the design already in the file.

## 6. What external agent guides add (2026)

These map cleanly onto Elves host routing; they are not Fugu-specific product claims:

- **Scope before spend.** Claude Code's explore → plan → implement pattern: do host-native
  research first, then one paid call with a packet that already names files and success shape.
- **Goal, context, constraints, done-when.** Codex-style prompts that state outcome, paths,
  what must not change, and how completion is checked outperform vague "review everything."
- **Verification criteria.** Prefer a check the model or host can run (tests, build, exact
  `file:line` re-read) over "looks done."
- **Fresh context for review.** A second opinion in a clean session beats the same session
  grading its own work. Fugu is that second opinion only if the host does not paste a kitchen-
  sink chat history into the task string.
- **Do not max everything.** Match model and effort to the task; public Fugu Ultra runs are
  often 20–60+ minutes. Save `--max` for one narrow gate.

## Quick reference

    # Narrow question, default model (first paid call)
    run_fugu.sh "<one specific question; paths; done-when>" > fugu.log 2>&1

    # Narrow question, longer clock only
    run_fugu.sh --max-wait 900 "<one specific question>" > fugu.log 2>&1

    # Review that must produce a report (ranked scope, exclusions, output shape)
    run_fugu.sh --ultra review "<ranked scope…>" > fugu.log 2>&1

    # Confirm the call shape without spending a budget
    run_fugu.sh --ultra --preflight --include NOTE.md review "<scope>"

Never: `| tail`, `| head`, or any pipe stage that buffers. Redirect, then read the file.
