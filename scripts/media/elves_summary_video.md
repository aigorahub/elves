# Elves run summary video

Generate a short end-of-run summary video from the Elves Report or execution-log
digest.

## Preferred pipeline

1. Collect title, mission one-liner, batch list, and residual risks from the Elves
   Report HTML or `docs/elves/execution-log-*.md`.
2. Author a HyperFrames composition (or Remotion project if HyperFrames is
   unavailable) with one scene per batch close plus a title card.
3. Render under `/tmp` or the run's artifact dir; do not commit large binaries.

## CLI sketch

```bash
# HyperFrames (when installed)
hyperframes init elves-summary --title "Elves run summary"
# paste scenes from the report, then:
hyperframes render
```

Remotion remains supported as an alternate when a project already uses it; the
contract is the **artifact** (mp4) + report path in the final notification, not a
specific engine.
