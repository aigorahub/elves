# Assessment: Rust port and RTK-style token efficiency (AIG-283 / #209)

Date: 2026-08-01
Tree: v2.22 full-backlog branch

## Rust port of cobbler_runtime

**Recommendation: no-go for v2.22.**

Reasons:

- The Python runtime is the product surface for host adapters, isolation, and tests;
  a port would freeze feature velocity during Parallelves and planning-harvest work.
- Hot paths are subprocess and filesystem bound, not pure CPU.
- The extract of `fugu.py` and shared context constants already improve
  maintainability without a language rewrite.

Revisit only if profiling shows a single pure-Python module dominating multi-hour
runs after the stdlib compact layer ships.

## RTK-style ideas without RTK

**Recommendation: ship thin stdlib compact layer (AIG-310) — done in-tree as
`cobbler_runtime.tool_output_compact`.**

Do **not** add an RTK dependency. Borrow only: head/tail windows, success-run
collapse, failure-line retention.
