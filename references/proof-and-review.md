# Proof and convergent review

Machine sources: `scripts/cobbler_runtime/evidence_review.py`, `risk_policy.py`.

## Proof budget

**validate once, verify changes, attest final**

- Per-batch default: touched surfaces via impact path.
- Broad proof: high-risk checkpoints and terminal readiness.
- Never weaken, skip, or delete tests merely to obtain green.
- **Mid-run:** selected impact tests and blockers only. Do not re-run a large full suite between
  ordinary batches when the impact path is green.
- **Terminal:** full suite (or project full gate), one cumulative review, then drain **deferred
  hygiene** (advisory nits banked mid-run). See `references/validation-guide.md`.

## Impact path

```text
changed surface -> affected consumer -> selected test
```

Evidence records `inputs_digest` and `invalidation_scope`. Unchanged digests may be reused.
Cleanup-only operational deletes reuse product proof; new product/runtime/security surfaces
broaden proof automatically.

## Risk × trust

| risk | trust_mode | typical proof |
|------|------------|---------------|
| low | trusted | docs/touched only |
| standard | trusted | focused impact tests |
| high | trusted | checkpoint or terminal broad |
| * | untrusted | strict detached/import + broad |

Legacy 2.2 tier names map onto these axes for compatibility.

## Convergent review loop

1. **One cumulative review** at terminal: completeness, constitution, declared risks, concrete regressions.
2. **Consolidate** blocking findings before revision. Advisory findings do not delay readiness;
   mid-run advisories belong in deferred hygiene until terminal.
3. **Revise** once for the consolidated set.
4. **delta re-review** only the revision delta and unresolved blockers — no rescan of settled work.
5. New re-review blockers require a concrete serious category: regression, acceptance/constitution
   breach, security, data integrity, or failure introduced by the revision.
6. **Stop** when exact-tip evidence is sufficient — not when reviewers run out of suggestions.
7. Healthy trusted full-runs do **not** add per-batch driver reviews; workers use impact proof
   mid-run and the host reviews once at terminal.

## Final readiness

Independent review of `git diff <default-branch>...HEAD`, plan, execution evidence, acceptance
rows, PR feedback, and required CI. Use a review subagent when available.
