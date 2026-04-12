# AI Docs Manifest

This directory holds durable agent-facing docs for the Elves repo itself. These files are the
curated layer above the run-specific `docs/elves/*` memory surfaces.

## When to read this directory

- Read `architecture.md` when you need the repo map or want to understand how the docs system fits
  together.
- Read `conventions.md` before making changes that affect skill behavior, versioning, staging, or
  cross-file wording.
- Read `gotchas.md` when a change looks simple but keeps touching multiple docs or workflows.

## Relationship to other docs

- `docs/plans/*`: authoritative scope for the current run
- `docs/elves/survival-guide.md`: active run brief
- `docs/elves/execution-log.md`: chronological run record
- `docs/elves/learnings.md`: durable promotion inbox for reusable lessons
- `.ai-docs/*`: curated durable truths worth keeping beyond one run

Promotion flow: `execution log -> learnings -> .ai-docs`

## Files

- `architecture.md`: what this repo is made of and how the doc layers fit together
- `conventions.md`: stable rules for changing the repo without creating drift
- `gotchas.md`: recurring traps and misleading simplifications
