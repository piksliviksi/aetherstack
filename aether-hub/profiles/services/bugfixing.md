# Bug-fixing behavior

- Capture a minimal reproduction and trace the actual failing path.
- Include the exact failing probe, error text, relevant path/symbol, and before/after result.
- Establish root cause before editing; do not stop at a symptom patch.
- The critic must try to falsify the root cause and identify adjacent cases the repair could break.
- Keep the repair narrow and protect adjacent behavior.
- Add a regression test that fails before and passes after the repair.
- Finish with root cause, fix, evidence, and remaining risk.

## Self-audit prompt

Investigate AetherStack for reproducible bugs in startup, model discovery, fallback, preset execution, streaming, and UI state. Trace likely root causes and run or identify regression tests that would fail before each fix and pass after it.
