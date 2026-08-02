# Polishing behavior

- Identify concrete friction, inconsistency, and unfinished states.
- Preserve behavior, accessibility, safety, and existing product intent.
- Prefer small simplifications over new abstractions or scope expansion.
- Cite each inconsistency in the current implementation and verify that cleanup does not change behavior.
- The critic checks stale state, duplicated logic, dead documentation, responsive details, and packaging/release mismatches.
- Check visual, copy, loading, empty, error, and responsive states.
- Finish with the improvements made and any deliberately deferred work.

## Self-audit prompt

Audit AetherStack for user-visible rough edges, inconsistent wording/tokens, dead controls, layout problems, confusing status, and avoidable complexity. Ground findings in code and run or identify visual, structural, or interaction tests that demonstrate them.
