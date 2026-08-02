# Enterprise / multi-user contracts (v0)

JSON Schema drafts for Team Server and Cloud. **Not enforced by Hub yet** (E0 prep).

| Schema | MULTI-USER | Purpose |
|--------|------------|---------|
| [tenancy-v0.json](./tenancy-v0.json) | M0 | User, team, project, membership, request context |
| [audit-event-v0.json](./audit-event-v0.json) | M1 | Append-only audit events |
| [file-lease-v0.json](./file-lease-v0.json) | M2 | Path leases for edit collision guards |

Validate examples in CI with any Draft 2020-12 checker when fixtures are added.

See [ENTERPRISE-PLATFORM.md](../ENTERPRISE-PLATFORM.md) and [MULTI-USER.md](../MULTI-USER.md).
