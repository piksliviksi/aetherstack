# Coding behavior

- Read the actual call path and local conventions before editing.
- Report concrete symbols and paths, not a repository inventory or intended inspection steps.
- Make the smallest coherent change that solves the requested behavior.
- Preserve unrelated work and avoid broad mechanical rewrites.
- The critic challenges root assumptions, integration behavior, edge cases, and whether the tests would fail before the change.
- Add focused regression coverage and run the relevant integration path.
- Finish with changed files, verification evidence, and honest gaps.

## Self-audit prompt

Review the AetherStack codebase for concrete correctness and maintainability defects, dead code, needless duplication, fragile abstractions, and mismatched contracts. Cite paths/symbols and run or identify precise unit or integration tests for the strongest findings.
