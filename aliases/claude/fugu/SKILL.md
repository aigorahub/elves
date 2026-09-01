---
name: fugu
description: Run a bounded Sakana Fugu repository task or explicit review through codex-fugu. Use when the user types /fugu, asks to use Fugu, or asks for a Fugu review.
disable-model-invocation: true
---

<!-- elves-managed-alias: claude-skill-alias v1 -->

# Fugu Planning or Review

This is the Elves-managed Claude Code alias for
`/fugu [--deep|--ultra|--max] [--max-wait SECONDS] [--preflight] [--include PATH] <planning-task>`
and
`/fugu [--deep|--cyber|--ultra|--max] [--max-wait SECONDS] [--preflight] review <scope>`.

Load the installed `elves` skill's **Provider shortcut protocols** and
`references/provider-shortcuts.md`. Resolve `scripts/run_fugu.sh` from the active Elves skill root,
keep the target repository as the working directory, pass through the validated mode/profile/context,
and run it.

**Host Fugu routing (required when the user omits a profile flag).** Natural language "use Fugu"
or plain `/fugu <task>` uses bare `fugu/high` by default. Before launch, state one
short `Fugu route: …` line. Explicit user flags always win.
Profile **locks model + effort**.

1. Host-native first if `rg`/`git`/`gh` can finish in under a minute.
2. Task mode: planning (default) vs `review <scope>` when the user asked for a review or audit.
3. Profile: use plain `fugu/high` by default. Use `--deep` only when regular Fugu needs xhigh effort. The host may select `--cyber` only for explicit security review or threat-model intent after a successful Cyber call in the current session. Only a user-explicit `--cyber` request may establish that proof. Otherwise, use regular Fugu. The user must explicitly select `--ultra` or `--max`.
4. Write: Fugu is read-only. The runner rejects `--write`.
5. Context: the isolation snapshot is always on. Put goal, paths, done-when, and out-of-scope in the
   task string. Add exact `--include PATH` only for non-gitignored files; **if any include, run
   `--preflight` first** and launch only when admitted. No separate "minimal snapshot" product.
6. Capture: redirect to a log file (never `| tail` / `| head`). Chat cancel does not stop the
   provider; wait up to the wall or kill the process group. On timeout/crash, harvest any
   `Fugu partial salvage` markers before relaunch. Verify findings host-native and clean up leftover process groups (see `references/fugu-calling-guide.md`).

Full decision table, route templates, wait/poll contract, and field notes:
`references/provider-shortcuts.md` (**Host routing when the user says "use Fugu"**) and
`references/fugu-calling-guide.md`.

Plain `/fugu <task>` is a read-only planning task whose answer follows the request;
`/fugu review <scope>` is the opinionated read-only review. Exact includes must be
admitted and copied; both `.env.*` and `*.env` names are excluded. Live writable-state limits
tolerate benign disappearing temporary subtrees and fail closed on other audit errors. macOS
read-only cleanup remains best-effort and never claims recursive containment. The Linux lane
omits procfs and exposes only a synthetic `/proc/self/exe` link to the qualified real Codex
binary.

The runner uses the official `codex-fugu` launcher with policy-admitted tracked and non-ignored
untracked context, closed interactive input, and a hard wall-clock bound. It selects regular
`fugu/high` when the host chooses plain, `fugu/xhigh` with `--deep`, `fugu-cyber/xhigh` with `--cyber`, `fugu-ultra-v1.1/high` with
`--ultra`, or `fugu-ultra-v1.1/max` with `--max`.
Regular/deep sessions are ephemeral; Ultra uses exact-session staged synthesis, with its state
confined to the disposable isolated lane, events carried by a bounded host-owned pipe, final
output pinned to a no-follow descriptor, and a final descriptor-safe writable-state audit after
each settled phase.
Do not replace it with an improvised API request or remove its sandbox and timeout controls.
