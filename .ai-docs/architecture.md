# Architecture

## Repo shape

This repo is a portable skill package, not an application. Its primary surfaces are documentation,
templates, and small support scripts:

- `SKILL.md`: canonical Claude-style skill surface
- `AGENTS.md`: canonical Codex-style skill surface
- `references/*`: reusable templates and supporting guidance
- `README.md`, `CHANGELOG.md`, `TODO.md`: human-facing project docs
- `scripts/*`: supporting operator utilities, such as preflight
- `docs/plans/*` and `docs/elves/*`: run-specific working memory during an active Elves session

## Memory layers

Elves now uses distinct layers instead of one giant note pile:

1. `plan`: authoritative scope and batch structure for the current run
2. `survival guide`: current run control, next exact batch, and operator constraints
3. `learnings`: durable reusable lessons that should survive this run
4. `execution log`: chronological proof of what happened
5. `.ai-docs/*`: curated durable truths about this repo

The point of the layering is to keep raw chronology, reusable lessons, and stable repo knowledge in
different places so later agents do not need to infer intent from noisy notes.

## Documentation system

This repo now treats documentation as a maintained surface:

- Raw observations belong in the execution log.
- Reusable lessons belong in the learnings file.
- Stable architecture, conventions, and traps belong in `.ai-docs/*`.
- Human-facing explanations and release notes belong in `README.md`, `CHANGELOG.md`, and `TODO.md`.

Because this repo *is* a skill, changes almost always cross multiple surfaces. Updating one file in
isolation is usually not sufficient.
