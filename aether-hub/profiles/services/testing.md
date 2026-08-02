# Testing behavior

- Convert requirements into observable happy-path, boundary, and failure cases.
- Reproduce claimed failures before treating them as fixed.
- Prefer deterministic tests and include the real integration boundary when practical.
- Distinguish a mocked check from a live-system result.
- Include exact commands, observed pass/fail output, fixtures, boundaries, and the behavior each assertion proves.
- The critic identifies false positives, missing negative paths, nondeterminism, and mocked-away integration risk.
- Finish with pass/fail evidence and explicit untested assumptions.
