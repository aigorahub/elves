# Gotchas

- This repo is documentation-heavy, so regressions usually show up as drift between `SKILL.md`,
  `AGENTS.md`, templates, README, and changelog rather than broken code execution.
- `README.md` repeats concepts from the skill files and often lags unless it is updated as part of
  the same batch.
- A morning checkpoint, return time, or delivery target can look like a natural stopping point, but
  it is not a stop condition unless the survival guide explicitly says it is a hard stop.
- The survival guide can silently rot into an append-only history log if updates get stacked at the
  bottom. Rewrite the live sections in place and keep chronology in the execution log.
- Paid pods, remote jobs, and long-lived local services become invisible quickly unless `Active
  Compute` is updated after every push and resource change.
- `.elves-session.json` is ignored by default in the repo baseline, but live Elves runs may need to
  force-add it so the branch carries structured session state during the run.
- Local project installs can quietly shadow global installs. When behavior differs from what the
  user expects, check `scripts/install_doctor.py --doctor` before assuming the upgrade failed.
- PR review automation only becomes useful once the branch is pushed and the PR exists. Opening the
  PR late starves the review loop.
- This repo has no package-managed lint/typecheck/build/test pipeline, so proof comes from
  preflight sanity, reference consistency, and PR review cleanliness.
