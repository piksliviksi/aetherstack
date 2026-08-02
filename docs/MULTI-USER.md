# Multi-user AetherStack (roadmap)

Status: **design** — not implemented. Today AetherStack is a **single-tenant local appliance** (one operator, loopback Hub, one CLI bridge cwd, client-chosen `session_id`).

This document captures the product direction for team projects: shared research, login, per-user CLI/VS Code spaces, and edit-collision guards.

## Goals

| Need | Feature |
|------|---------|
| Several people, one project | Team + project membership |
| Share research | Project memory namespace with member read ACL |
| Prevent simultaneous code clobber | File leases + agent `workspace_write` must hold a lease |
| Login | OIDC (preferred) + local accounts for air-gapped installs |
| Own CLI / VS Code space | Per-user worktree + per-user CLI bridge token/cwd |
| See others’ edits | Presence + lock UI in Hub and VS Code |

## What exists today (building blocks)

- Session transcripts keyed by client `session_id` (Redis)
- Memory tiers: tree / project / global / private vault / xref
- Workspace-write gate via master key header
- Host CLI bridge (one bearer token, one cwd)
- SSE phase stream for runs

None of these are multi-user ACLs yet. Loopback Hub `/api/*` is effectively open to any local client.

## Architecture options

| Option | When |
|--------|------|
| **Self-hosted team server** | LAN/VPN Compose stack; each dev’s VS Code connects remotely; git worktrees per user | Default first product |
| **Managed cloud** | Multi-tenant control plane + sandboxed runners | Later ops product |
| **Hybrid** | Cloud auth/billing; compute in customer VPC | Enterprise |

**Cloud is not required** for multi-user. Ship self-hosted team edition first.

## Implementation phases

### M0 — Tenancy primitives

- Principals: `user_id`, `team_id`, `project_id`
- Authn: OIDC (Authentik/Keycloak/Auth0) or local user table
- Authz: `owner | member | viewer` per project
- Gate **all** Hub `/api/*` with JWT/session (close loopback-open control plane)
- Namespace memory: `project:{id}:…`, `user:{id}:…`

### M1 — Shared research

- Default project memory shared to members
- Optional private user scratch
- Research library (claims, handoffs, docs)
- Audit log: who ran which preset

### M2 — Edit collision guard

- Redis leases: `lock:{project}:{path}` with TTL + heartbeat
- Agents must acquire leases before `workspace_write`
- VS Code shows lock badges; soft-warn or hard-block save
- Concurrent agent runs: second agent read-only or queued

### M3 — Per-user CLI / VS Code space

- One bridge per user (token + cwd = user worktree)
- Prefer **git worktrees** under a shared bare repo
- Presence over SSE: `user editing path`

### M4 — Compute multi-tenancy

- Fair queue per team
- Optional remote GPU workers
- Metering: tokens / minutes / seats

## Tools beyond AetherStack core

| Capability | Suggestion |
|------------|------------|
| Identity / SSO | Authentik or Keycloak (self-host); Auth0 (cloud) |
| Git | Customer GitHub/GitLab; optional Gitea |
| Object storage | MinIO / S3 for artifacts |
| Secrets | OpenBao/Vault — do not share one master `.env` across users |
| Billing (SaaS) | Stripe seats + overage |
| Orchestration at scale | Stay on Compose until multi-node is forced |

Avoid CRDT multi-cursor coding in v1; leases + git worktrees first.

## Hardware envelopes (planning)

| Size | Spec | Infra / month | Fits |
|------|------|---------------|------|
| Starter | 8 vCPU, 32 GB, 500 GB | ~$40–80 | 3–5 light users |
| Team | 16 vCPU, 64 GB, 1 TB ± GPU | ~$150–400 (+ GPU $200–800) | 8–15 users |
| Heavy | 32+ vCPU, 128 GB, GPU | ~$600–1500+ | Many concurrent agent runs |

## Pricing envelopes (discussion, not final)

| Plan | List / user / month | Includes |
|------|---------------------|----------|
| Team self-host license | $15–25 | Multi-user Hub, locks, SSO connector (customer hardware) |
| Cloud Team | $39–59 | Hosted Hub + compute quota |
| Cloud + tokens | $79–129 | Higher included token budget |
| Enterprise | Custom | VPC, SSO, SLA, air-gap |

**Hosted COGS** roughly $20–100 / user / month depending on token policy.

**Break-even (illustrative):** at ~$49/user and ~$25 COGS, contribution ~$24/user → tens to low hundreds of seats depending on fixed cost; self-host license model often breaks even around **20–40 paying teams** if ACV is a few k$/year.

Measure real token use per preset before locking list prices.

## Explicit non-goals (near term)

- Moving core local single-user appliance to mandatory cloud
- One shared OS login + one CLI bridge for a whole team
- OT/CRDT simultaneous file editing in v1

## Related docs

- [SECURITY-NOTES.md](./SECURITY-NOTES.md) — tokens, loopback trust
- [AGENT-MEMORY.md](./AGENT-MEMORY.md) — session/vector namespaces
- [PRIVATE-MODE.md](./PRIVATE-MODE.md) — vault isolation patterns
- [OPERATING-MODEL.md](./OPERATING-MODEL.md) — single-operator product intent today
