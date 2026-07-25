---
name: fugu
description: Run a bounded Sakana Fugu repository task or explicit review through codex-fugu. Use when the user types /fugu, asks to use Fugu, or asks for a Fugu review.
disable-model-invocation: true
---

<!-- elves-managed-alias: claude-skill-alias v1 -->

# Fugu Task or Review

This is the Elves-managed Claude Code alias for
`/fugu [--deep|--ultra] [--write] [--include PATH] <task>` and
`/fugu [--deep|--ultra] review <scope>`.

Load the installed `elves` skill's **Provider shortcut protocols** and
`references/provider-shortcuts.md`. Resolve `scripts/run_fugu.sh` from the active Elves skill root,
keep the target repository as the working directory, pass through the validated mode/profile/context,
and run it. Plain `/fugu <task>` is a general read-only task whose answer follows the request;
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
`fugu/high` by default, `fugu/xhigh` with `--deep`, `fugu-ultra-v1.1/high` with `--ultra`, or
`fugu-ultra-v1.1/max` with `--max`.
Regular/deep sessions are ephemeral; Ultra uses exact-session staged synthesis, with its state
confined to the disposable isolated lane, events carried by a bounded host-owned pipe, final
output pinned to a no-follow descriptor, and a final descriptor-safe writable-state audit after
each settled phase.
Do not replace it with an improvised API request or remove its sandbox and timeout controls.
