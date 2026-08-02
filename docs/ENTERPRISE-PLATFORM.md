# AetherStack Enterprise Platform

**Status:** design / preparation (E0)  
**Audience:** platform engineers, enterprise architects, distro maintainers  
**Related:** [MULTI-USER.md](./MULTI-USER.md) · [DEBIAN-DISTRO-BUILD.md](./DEBIAN-DISTRO-BUILD.md) · [ENTERPRISE-ROADMAP.md](./ENTERPRISE-ROADMAP.md) · [SECURITY-NOTES.md](./SECURITY-NOTES.md)

AetherStack today is a **single-tenant local appliance**. This document defines the **enterprise product line**: Debian-based delivery, team multi-user control plane, and cloud support for organizations — without forcing cloud on individual desktop users.

---

## 1. Product SKUs (one codebase)

| SKU | Form factor | Network | Auth | Tenancy | Primary audience |
|-----|-------------|---------|------|---------|------------------|
| **Desktop** | Debian/Ubuntu live or install ISO; also stock OS + Compose | Loopback default | Single local operator | None (implicit one user) | Individual developer |
| **Team Server** | Debian server image / VM / bare metal (self-host) | LAN/VPN + TLS reverse proxy | OIDC (preferred) + local users (air-gap) | Single org, many users/projects | 3–50 seats, customer hardware |
| **Cloud** | Managed multi-tenant control plane | Public SaaS or private link | OIDC/SAML, org SSO | Multi-org (`tenant_id`) | Teams wanting zero ops |
| **Enterprise (Hybrid)** | Cloud auth/billing + compute in customer VPC | Private link / VPC peering | Customer IdP | Single or multi-org per contract | Regulated / air-gapped segments |

**Principle:** Desktop remains a first-class, offline-capable appliance. Team and Cloud **add** auth, ACLs, and ops — they do not remove the local operating model (pass-through Auto, shared memory, local fallback).

```text
┌──────────────────────────────────────────────────────────────────┐
│  Enterprise platform                                             │
│                                                                  │
│  Identity (OIDC/SAML) ──► Hub Authn/Authz (JWT) ──► ACLs         │
│       │                        │                                 │
│       ▼                        ▼                                 │
│  Team / Project ── memory namespaces ── leases ── audit          │
│       │                                                          │
│       ├── Client: VS Code / CLI worktrees (per user)             │
│       ├── Compute: host Ollama | remote GPU workers | cloud LLM  │
│       └── Data: Postgres (tenancy+spend) · Redis · object store  │
│                                                                  │
│  Delivery:                                                       │
│    Desktop ISO · Team Server ISO/qcow2 · Cloud Compose/Helm      │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Trust boundaries

| Edition | Hub `/api/*` | Open WebUI proxy | Bind defaults | Master secrets |
|---------|--------------|------------------|---------------|----------------|
| **Desktop** | Loopback; effectively open to local processes (today) | Loopback passwordless local session | `127.0.0.1` | One operator `.env` |
| **Team Server** | **Must** require JWT/session when published | **No** passwordless proxy on non-loopback | Proxy terminates TLS; app ports internal or loopback behind proxy | Org-scoped keys; per-user gateway tokens preferred |
| **Cloud** | JWT + org membership on every control path | Per-user auth only | Edge only; no raw Hub on public IP | Platform secrets vault; customer BYOK optional |

**Hard rule for Team/Cloud:**  
`AETHER_REQUIRE_AUTH=1` whenever `AETHER_BIND_HOST` is not loopback **or** `AETHER_EDITION` is `team` / `cloud`. Future Hub code must refuse unsafe combinations (see roadmap E1).

Schemas for principals and events: [schemas/](./schemas/).

---

## 3. Tenancy model (MULTI-USER M0+)

Aligned with [MULTI-USER.md](./MULTI-USER.md):

| Principal | ID | Notes |
|-----------|-----|--------|
| User | `user_id` | From IdP `sub` or local user table |
| Team | `team_id` | Billing/seat boundary (self-host: usually one team per deployment) |
| Project | `project_id` | Shared research + workspace scope |
| (Cloud) Org / tenant | `tenant_id` | Isolates orgs on shared control plane |

**Roles (project):** `owner` | `member` | `viewer`

**Memory namespaces (target):**

| Namespace | ACL |
|-----------|-----|
| `project:{project_id}:…` | Members read; write per role |
| `user:{user_id}:…` | Private scratch |
| Private vault (existing) | Unchanged semantics; scoped to user/project flags |

**File leases (M2):** `lock:{project_id}:{path}` with TTL + heartbeat — agents need a lease for `workspace_write`.

---

## 4. Identity

| Deployment | Recommendation |
|------------|----------------|
| Team Server (self-host) | **Authentik** or **Keycloak** on the Team Server image / compose profile |
| Air-gapped Team | Local user table + optional LDAP; OIDC offline IdP |
| Cloud / Enterprise | Auth0, Okta, Entra ID, or customer SAML via bridge |

Hub accepts **JWT** (OIDC access/ID token) with claims mapping:

```text
sub            → user_id
org_id/tid     → tenant_id (cloud)
groups/roles   → team roles (configurable claim paths)
```

VS Code / CLI: device code or PAT issued by Hub after OIDC login; CLI bridge becomes **per-user** (token + worktree cwd).

---

## 5. Secrets and provider keys

| Anti-pattern | Enterprise pattern |
|--------------|-------------------|
| One shared `LITELLM_MASTER_KEY` for all humans | Platform admin key separate from **per-user / per-project virtual keys** |
| Cloud API keys in every developer `.env` | Org-level keys in server secret store; users get budgeted gateway tokens |
| Committing keys in ISO | Templates only; first-boot / cloud-init / vault inject |

Reuse multi-account aliases ([MULTI-KEYS.md](./MULTI-KEYS.md)) at **org** scope (`*-personal` / `*-enterprise` still valid for dual billing).

---

## 6. Networking (Team Server)

```text
                    ┌─────────────┐
  Users ──TLS──────►│ Caddy/      │──► open-webui (auth)
                    │ Traefik     │──► aether-hub :8766
                    │             │──► litellm :4000
                    └─────────────┘
                           │
                    docker network (internal)
                           │
                    redis · postgres · (optional minio)
                           │
                    host.docker.internal → Ollama / GPU
```

- Publish **only** the reverse proxy (443).  
- Keep Compose service ports on `127.0.0.1` or internal networks.  
- Optional mTLS between desktop CLI bridge agents and Hub for high-security sites.

Desktop ISO stays loopback-only; Team Server edition enables proxy + auth profiles via [distro/editions/](../distro/editions/).

---

## 7. Compute and data plane

| Layer | Desktop | Team Server | Cloud |
|-------|---------|-------------|-------|
| Inference | Host Ollama (GPU) | Host/shared Ollama or GPU workers | Shared/regional GPU + customer VPC workers |
| Control plane | Compose on laptop | Compose on server image | Multi-node / k8s when forced |
| Spend DB | LiteLLM Postgres | Same + hub tenancy tables | Shared Postgres with `tenant_id` |
| Artifacts | Local disk | MinIO/S3 optional | S3-compatible |
| Backup | [BACKUP.md](./BACKUP.md) | Scheduled + off-box | Platform-managed + customer export |

Hardware envelopes remain as in MULTI-USER (Starter / Team / Heavy).

---

## 8. Debian / distro delivery

| Image | Content | Config source |
|-------|---------|---------------|
| **Desktop ISO** | Toolkit + host Ollama + loopback Compose | `distro/editions/desktop.yaml` |
| **Team Server ISO / qcow2** | Toolkit + Docker + proxy + IdP profile + no desktop fluff | `distro/editions/team-server.yaml` |
| **Cloud** | Not an ISO; deploy manifests from `cloud-control-plane` edition flags | `distro/editions/cloud-control-plane.yaml` |

Build guide: [DEBIAN-DISTRO-BUILD.md](./DEBIAN-DISTRO-BUILD.md)  
Scaffold: [distro/README.md](../distro/README.md)

Compose overlays (opt-in; default path unchanged):

| File | Role |
|------|------|
| [docker-compose.team.yml](../docker-compose.team.yml) | Team Server edge (proxy, auth profile placeholders) |
| [docker-compose.enterprise.yml](../docker-compose.enterprise.yml) | Multi-tenant / metering flags |

```bash
# Example (Team Server — after auth is implemented)
docker compose \
  -f docker-compose.yml \
  -f docker-compose.team.yml \
  --env-file .env.team \
  up -d
```

---

## 9. Compliance and enterprise controls

| Control | Target behaviour |
|---------|------------------|
| Audit log | Who ran which preset/graph; authn events; lease grants (schema: [schemas/audit-event-v0.json](./schemas/audit-event-v0.json)) |
| Private mode | Existing vault; enforce no cross-tenant index in Cloud |
| Data residency | Cloud region pin; Team Server = customer premises |
| Retention | Configurable session/memory TTL per org policy |
| Admin break-glass | Documented; dual control for Enterprise contracts |
| SBOM / signing | ISO and runtime tarballs signed; see distro `sbom/` |

SLO placeholders (Enterprise contracts — finalize with ops):

| Metric | Target (draft) |
|--------|----------------|
| Control plane availability | 99.5% monthly (Cloud) |
| Auth token validation latency | p99 &lt; 50 ms |
| RPO / RTO (Team backup) | Customer-defined; document defaults 24h / 4h |

---

## 10. Threat model (summary)

| Actor | Risk | Mitigation |
|-------|------|------------|
| Local process on Desktop | Read open Hub API | Accept for single-user OS account model; optional engine token |
| Team member | Read other projects | Project ACLs + namespace isolation |
| Team admin | Over-broad secrets | Org key vault; virtual keys with budgets |
| Network attacker | Hit open Hub on LAN | Auth mandatory + TLS + no raw port publish |
| Malicious ISO build | Supply chain | Reproducible builds, signed artifacts, pinned digests |

---

## 11. Explicit non-goals (near term)

- Replacing Desktop with mandatory cloud accounts  
- CRDT multi-cursor coding (leases + git worktrees first)  
- One shared OS login + one CLI bridge for a whole team  
- Full OT collaborative editing in v1  

---

## 12. GA checklist (Team Server)

Before calling Team Server generally available:

1. [ ] All Hub `/api/*` authenticated when `AETHER_EDITION=team`  
2. [ ] JWT validation + project ACL on memory and runs  
3. [ ] No passwordless WebUI proxy on non-loopback  
4. [ ] TLS reverse proxy documented and default in team edition  
5. [ ] Per-org/provider secret isolation  
6. [ ] Audit log for auth and preset runs  
7. [ ] Backup/restore of Postgres + Redis memory volumes  
8. [ ] QEMU/smoke + security review for non-loopback mode  
9. [ ] Debian Team Server image boots to healthy stack with OIDC or local admin  

Cloud GA adds: multi-tenant isolation tests, metering, seat admin UI, SOC2-oriented logging.

---

## 13. Related paths

| Path | Role |
|------|------|
| [MULTI-USER.md](./MULTI-USER.md) | M0–M4 feature phases |
| [ENTERPRISE-ROADMAP.md](./ENTERPRISE-ROADMAP.md) | E0–E5 milestones |
| [DEBIAN-DISTRO-BUILD.md](./DEBIAN-DISTRO-BUILD.md) | ISO technical build |
| [distro/](../distro/) | Packaging scaffold |
| [schemas/](./schemas/) | Tenancy / audit / lease contracts |
| [.env.team.example](../.env.team.example) | Team env contract |
| [.env.cloud.example](../.env.cloud.example) | Cloud env contract |
