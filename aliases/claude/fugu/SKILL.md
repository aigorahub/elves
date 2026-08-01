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
short `Fugu route: …` line:

1. Task mode: general (default) vs `review <scope>` when the user asked for a review/audit.
2. Profile (locks model + effort; mutually exclusive; explicit user flags always win):
   plain → `fugu/high` (default; prefer first); `--deep` → `fugu/xhigh` (only when multi-module
   design/security needs it); `--ultra` → `fugu-ultra-v1.1/high` (compact high-stakes with reserved
   synthesis); `--max` → `fugu-ultra-v1.1/max` (one narrow gate, 60-minute wall). Prefer the
   cheapest matching lane. Prefer `--max-wait` over automatic `--deep` for slightly long plain work.
3. Write: read-only default; `--write` only with independent implementation authority on qualified
   Linux bwrap PID-namespace (unavailable on macOS).
4. Context: the isolation snapshot is always on. Default admitted tracked + safe non-ignored
   untracked context is enough for most tasks; add exact `--include PATH` only for host-selected
   files that must be admitted (never gitignored paths). There is no separate "minimal snapshot"
   product. Use `--preflight` to validate includes/route without provider cost.

**Fugu economy:** host-native first for inventory/triage/greps; narrow the packet before raising
the profile; default plain; fail-fast includes via preflight.

Full decision table: `references/provider-shortcuts.md` (**Host routing when the user says "use Fugu"**).

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
