# Enterprise roadmap

**Status:** planning  
**Platform overview:** [ENTERPRISE-PLATFORM.md](./ENTERPRISE-PLATFORM.md)  
**Multi-user phases:** [MULTI-USER.md](./MULTI-USER.md)

Maps product engineering (M0–M4) to **enterprise milestones (E0–E5)** and distro/cloud delivery.

---

## Milestone table

| Milestone | Scope | MULTI-USER | Distro / cloud impact | Exit criteria |
|-----------|--------|------------|------------------------|---------------|
| **E0 — Prep** | Architecture docs, `distro/` scaffold, team/enterprise compose & env stubs, JSON schemas | — | Scaffold only; no GA claims | Docs + overlays validate; desktop path unchanged |
| **E1 — Auth (M0)** | Principals, OIDC/local login, JWT on all Hub `/api/*`, project roles | M0 | Team Server ISO **alpha** (auth services on image) | Non-loopback refused without auth; ACL unit tests |
| **E2 — Shared research (M1)** | Project memory namespaces, research library, audit log | M1 | Team Server **beta** | Members share project memory; audit query API |
| **E3 — Edit guards (M2)** | Redis file leases; agent `workspace_write` requires lease; VS Code lock UI | M2 | Team Server **GA candidate** | Concurrent write blocked without lease |
| **E4 — User spaces (M3)** | Per-user CLI bridge + git worktrees; presence SSE | M3 | Desktop clients attach to Team Server cleanly | Two users, two worktrees, no cwd clobber |
| **E5 — Scale + Cloud (M4)** | Fair queue, remote GPU workers, metering, multi-tenant SaaS, hybrid VPC | M4 | Cloud public beta; Enterprise VPC runbook | Seat admin + quota; isolation tests green |

---

## E0 detail (current)

**In repo when prep lands:**

- [ENTERPRISE-PLATFORM.md](./ENTERPRISE-PLATFORM.md)
- [distro/](../distro/) live-build/package/systemd stubs
- [docker-compose.team.yml](../docker-compose.team.yml), [docker-compose.enterprise.yml](../docker-compose.enterprise.yml)
- [.env.team.example](../.env.team.example), [.env.cloud.example](../.env.cloud.example)
- [schemas/tenancy-v0.json](./schemas/tenancy-v0.json), [audit-event-v0.json](./schemas/audit-event-v0.json), [file-lease-v0.json](./schemas/file-lease-v0.json)
- CI: compose config + schema presence checks

**Not in E0:** OIDC implementation, ISO binaries, billing, production multi-tenant Hub.

---

## Suggested sequencing after E0

```text
E0 Prep
  └─► E1 Auth ─────────────────────────────┐
        └─► E2 Shared research              │
              └─► E3 Leases ──► Team Server GA
                    └─► E4 Workspaces
                          └─► E5 Cloud / Hybrid + metering
```

Self-hosted **Team Server GA** should not wait for full Cloud (E5). Cloud reuses E1–E4 services with `AETHER_TENANT_MODE=multi`.

---

## SKU readiness

| SKU | First usable | GA target milestone |
|-----|--------------|---------------------|
| Desktop (current appliance) | Now | Continuous |
| Desktop ISO | After live-build green | Parallel to E1–E2 |
| Team Server self-host | E1 alpha | E3–E4 |
| Cloud Team | E5 beta | E5 + ops hardening |
| Enterprise Hybrid | E5 | Contract-driven |

---

## Ownership (suggested)

| Area | Owner focus |
|------|-------------|
| Hub authz + tenancy | Backend |
| VS Code locks / worktrees | Extension |
| Distro / ISO / packages | Platform |
| IdP + TLS defaults | Platform + security |
| Cloud multi-tenant ops | Platform + SRE |
| Pricing / seats | Product (see MULTI-USER envelopes) |

---

## Tracking

Update this file when a milestone starts or exits. Keep MULTI-USER phase text authoritative for feature behaviour; keep this file authoritative for **release order** and **distro coupling**.
