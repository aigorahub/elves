# Subprocess output budgets

Elves bounds capture while bytes arrive, not after the child exits. The limits
are host-side safety ceilings, not a claim about a provider's normal output or
all memory and disk that a subprocess can allocate.

| Capture path | Limit |
| --- | --- |
| External reviewer stdout | 32 MiB per attempt |
| External reviewer stderr | 8 MiB per attempt |
| Native-worker stdout or stderr | 64 MiB per stream per phase |
| Native-worker individual line | 1 MiB including newline |
| Native-worker persisted JSONL log | 128 MiB across appended phases and retries |
| Lantern callback stdout or stderr | 1 MiB per stream |
| Verification step or continuity helper stdout or stderr | 16 MiB per stream |
| OMP identity discovery file | 16 MiB per candidate |

The constants live beside their callers; the synchronous helpers share the
16 MiB default in `scripts/cobbler_runtime/subprocess_output.py`. There is no
environment override or automatic increase. A legitimate workload exceeding a
ceiling needs a deliberate budget review, not silent truncation.

## Failure behavior

- External capture wakes its supervisor as soon as either stream exceeds its
  ceiling. Existing qualified containment and filesystem cleanup still run.
  Cleanup failures take precedence. Excess output is never a clean review.
- Native-worker reads use bounded binary chunks and complete UTF-8 lines. An
  oversized or unfinished line is never parsed as a partial provider event.
  Raw stream and serialized-log limits are separate. Overflow stops the direct
  producer, closes its pipes, preserves prior redacted diagnostics, and records
  `native_worker_output_limit`; existing Git authority checks still apply.
- The synchronous POSIX helper closes stdin and concurrently drains both pipes.
  Output overflow or timeout kills its owned process group and reaps the direct
  child. Callback output is no longer spooled to unbounded temporary files.
  The callback's message ID remains available for reconciliation; retry is not
  made safe merely because output capture failed.
- Verification treats overflow as a failed gate (exit 125), distinct from timeout
  (124). The watchdog refuses to resume on overflow and never interprets a
  partial result as permission to continue.
- OMP identity discovery uses the existing descriptor-checked bounded artifact
  reader. It refuses oversized/changed files instead of trusting a prefix that
  might omit a conflicting identity. Valid, complete files keep the existing
  identity checks.

The general capture buffers retain complete output below their ceilings; after
an overflow each affected buffer retains at most 64 KiB of diagnostic tail (or
its smaller ceiling). External drains keep discarding excess bytes while their
existing cleanup runs. Native-worker logs retain their bounded prefix rather
than rotating away earlier identity evidence. Existing downstream redaction
still applies to diagnostics; no raw child output is added to error messages.

These are capture limits, not a general filesystem quota or a new isolation
boundary. Native workers keep their existing supervisor process group and do not
gain stronger descendant containment through this change. Runtime support stays
macOS/Linux/WSL2; this does not add native Windows execution.

Regression tests use deterministic subprocess fixtures (including noisy stderr,
missing newline, split UTF-8, zero-exit overflow, inherited pipes, cancellation,
and conflicting identities). They do not establish normal-output distributions
for live AI providers.
