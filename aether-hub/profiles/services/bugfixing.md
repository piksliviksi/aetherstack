# Bug-fixing behavior

- Capture a minimal reproduction and trace the actual failing path.
- Establish root cause before editing; do not stop at a symptom patch.
- Keep the repair narrow and protect adjacent behavior.
- Add a regression test that fails before and passes after the repair.
- Finish with root cause, fix, evidence, and remaining risk.
