# Frontend behavior

- Inspect the existing framework, components, styles, and API contracts first.
- Implement accessible, responsive states against real backend behavior.
- Keep state ownership and error handling explicit and test observable behavior.
- Cite touched components, state owners, API contracts, and browser evidence; do not return a framework inventory.
- The critic checks responsive overflow, stale requests, accessibility, loading/error states, and integration regressions.
- Avoid unrelated visual or architectural changes.
- Finish with tests run, browser states checked, and remaining limitations.

## Self-audit prompt

Audit AetherStack frontend and extension code for async races, stale state, lifecycle leaks, duplicated behavioral logic, unsafe rendering, resizing, keyboard behavior, and error recovery. Run or identify focused frontend tests that reproduce the strongest findings.
