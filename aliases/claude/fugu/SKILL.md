---
name: fugu
description: Run a bounded Sakana Fugu repository task or explicit review through codex-fugu. Use when the user types /fugu, asks to use Fugu, or asks for a Fugu review.
disable-model-invocation: true
---

<!-- elves-managed-alias: claude-skill-alias v1 -->

# Fugu Task or Review

This is the Elves-managed Claude Code alias for
`/fugu [--deep|--ultra|--max] [--max-wait SECONDS] [--preflight] [--write] [--include PATH] <task>`
and
`/fugu [--deep|--ultra|--max] [--max-wait SECONDS] [--preflight] review <scope>`.

Load the installed `elves` skill's **Provider shortcut protocols** and
`references/provider-shortcuts.md`. Resolve `scripts/run_fugu.sh` from the active Elves skill root,
keep the target repository as the working directory, pass through the validated mode/profile/context,
and run it.

**Host Fugu routing (required when the user omits a profile flag).** Natural language "use Fugu"
or plain `/fugu <task>` is **not** always bare `fugu/high`. Before launch, decide and state one
short `Fugu route: …` line. Prefer the **cheapest** matching lane; **explicit user flags always win**.
Profile **locks model + effort**.

1. Host-native first if `rg`/`git`/`gh` can finish in under a minute.
2. Task mode: general (default) vs `review <scope>` when the user asked for a review/audit.
3. Profile: **first paid call is plain** (`fugu/high`) unless the user set a flag. `--deep` only
   after plain failed or for real multi-module/security xhigh need. Prefer `--ultra` over plain/deep
   when the run **must** return a written report (reserved synthesis survives the wall; plain/deep
   die empty on timeout). `--max` only for one already-tight high-stakes gate (Ultra/Max often run
   20–60+ minutes). Prefer `--max-wait` over automatic `--deep` when you only need more wall.
4. Write: read-only default; `--write` only with independent implementation authority on qualified
   Linux bwrap PID-namespace (unavailable on macOS: say so in one line).
5. Context: the isolation snapshot is always on. Put goal, paths, done-when, and out-of-scope in the
   task string. Add exact `--include PATH` only for non-gitignored files; **if any include, run
   `--preflight` first** and launch only when admitted. No separate "minimal snapshot" product.
6. Capture: redirect to a log file (never `| tail` / `| head`). Chat cancel does not stop the
   provider; wait up to the wall or kill the process group. Verify Fugu findings host-native before
   acting.

Full decision table, route templates, wait/poll contract, and field notes:
`references/provider-shortcuts.md` (**Host routing when the user says "use Fugu"**) and
`references/fugu-calling-guide.md`.

Plain `/fugu <task>` is a general read-only task whose answer follows the request;
`/fugu review <scope>` is the opinionated read-only review. Use `--write` only when the user's
surrounding request independently authorizes implementation and the platform provides qualified
recursive Linux bwrap PID-namespace containment. It is unavailable on macOS today. A qualified
write edits solely inside the disposable kernel-isolated snapshot and returns a bounded mode-aware
audited handoff for host inspection, never an automatic checkout edit. Exact includes must be
admitted and copied; both `.env.*` and `*.env` names are excluded. Live writable-state limits
tolerate benign disappearing temporary subtrees and fail closed on other audit errors. macOS
read-only cleanup remains best-effort and never claims recursive containment.

The runner uses the official `codex-fugu` launcher with policy-admitted tracked and non-ignored
untracked context, closed interactive input, and a hard wall-clock bound. It selects regular
`fugu/high` when the host chooses plain, `fugu/xhigh` with `--deep`, `fugu-ultra-v1.1/high` with
`--ultra`, or `fugu-ultra-v1.1/max` with `--max`.
Regular/deep sessions are ephemeral; Ultra uses exact-session staged synthesis, with its state
confined to the disposable isolated lane, events carried by a bounded host-owned pipe, final
output pinned to a no-follow descriptor, and a final descriptor-safe writable-state audit after
each settled phase.
Do not replace it with an improvised API request or remove its sandbox and timeout controls.
