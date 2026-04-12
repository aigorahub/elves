# Gotchas

- This repo is documentation-heavy, so regressions usually show up as drift between `SKILL.md`,
  `AGENTS.md`, templates, README, and changelog rather than broken code execution.
- `README.md` repeats concepts from the skill files and often lags unless it is updated as part of
  the same batch.
- `.elves-session.json` is ignored by default in the repo baseline, but live Elves runs may need to
  force-add it so the branch carries structured session state during the run.
- PR review automation only becomes useful once the branch is pushed and the PR exists. Opening the
  PR late starves the review loop.
- This repo has no package-managed lint/typecheck/build/test pipeline, so proof comes from
  preflight sanity, reference consistency, and PR review cleanliness.
