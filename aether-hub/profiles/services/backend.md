# Backend behavior

- Define inputs, outputs, authorization, validation, and failure contracts first.
- Preserve data integrity across concurrency, retries, and migrations.
- Add useful observability without logging secrets or sensitive payloads.
- Trace the real call path and cite handlers, data owners, synchronization boundaries, and observed failure output.
- The critic checks authorization, validation, concurrency, retries, partial failure, compatibility, and rollback.
- Keep changes bounded and compatible unless migration is explicit.
- Finish with contract tests, operational checks, and rollback notes.
