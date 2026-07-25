# Future development

Planned product capabilities. Not implemented in the current lab/single-tenant stack.  
Status column: **planned** until shipped and documented as operational.

---

## 1. Enterprise shared AetherStack account

### Intent

One **paying enterprise account** hosts a siloed AetherStack tenant. Multiple users in that tenant share:

| Shared asset | Scope |
|--------------|--------|
| Distilled research (papers, findings, digests) | Tenant memory pool |
| Session / agent memory (non-private) | Tenant pool |
| Code concepts, tested patterns, research notes | Tenant pool |
| LLM orchestration scripts | Combos, pipelines, node graphs |
| Common **token pool** | Single billed account balance / quota |

Individual users may hold a **personal token budget** drawn from that one pool. Billing remains on the enterprise account.

### Billing model

| Element | Rule |
|---------|------|
| Payer | Single enterprise account (one invoice / one cloud-key owner) |
| Token pool | Shared quota for the tenant |
| Per-user budget | Optional hard or soft cap per user/seat |
| Exhaustion | User-level block when personal budget hits zero; pool-level block when tenant quota hits zero |
| Local GPU | Tenant policy: local inference may bypass cloud token meters per seat policy |

### Shared orchestration

| Artifact | Enterprise behavior |
|----------|---------------------|
| Combos | Tenant library; import/export within silo |
| Pipelines | Shared stage scripts; votes ranked inside tenant |
| Node graphs | Shared canvas templates; no cross-tenant export by default |
| Capability matrix | Tenant-scoped live routes |
| Slash / memory hygiene | Same `/done` → `/clear` flow; archives land in tenant pool |

### Isolation and crypto (silo)

Enterprise tenants are **encrypted and siloed**. No cross-tenant reads.

| Control | Requirement |
|---------|-------------|
| Tenant boundary | Cryptographic and logical silo per enterprise account |
| Encryption at rest | Tenant data (memory, archives, scripts metadata) encrypted with tenant keys |
| Encryption in transit | TLS for all remote surfaces |
| Key custody | Per-tenant keys; no shared master plaintext across tenants |
| Leak prevention | No common global memory index across enterprises |
| Operators | Platform ops cannot read tenant vault content without break-glass procedure (if any is offered) |
| Private mode | Coexists: user/project private vaults remain isolated **inside** the tenant; never auto-promote to tenant pool until release |
| Audit | Tenant-visible access logs; no content leakage into shared platform logs |

Relationship to current local private mode: [PRIVATE-MODE.md](./PRIVATE-MODE.md) is the single-machine isolation primitive. Enterprise silos extend the same rules to multi-user, multi-seat tenancy.

### Identity and seats

| Element | Planned |
|---------|---------|
| Auth | Enterprise IdP (OIDC/SAML) or managed seats |
| Roles | Admin (billing, budgets, scripts), member (chat/memory), reader (distilled research only) |
| Session binding | User → seat → tenant pool; private projects bind to user vault inside tenant |

### Out of scope for this item

| Item | Note |
|------|------|
| Public multi-tenant free tier | Separate product decision |
| Cross-enterprise research marketplace | Not part of siloed enterprise account |
| Shipping date | Unspecified until implementation starts |

---

## 2. Related backlog (pointers only)

| Area | Direction |
|------|-----------|
| Private mode | Shipped for local hub — [PRIVATE-MODE.md](./PRIVATE-MODE.md) |
| Cross-project memory | Shipped local multi-project — [CROSS-MEMORY.md](./CROSS-MEMORY.md) |
| Enterprise tenant control plane | This document §1 |
| Hardened multi-user Hub auth | Required before enterprise expose beyond lab bind |

---

## Status legend

| Status | Meaning |
|--------|---------|
| **shipped** | In tree and documented as operational |
| **planned** | Specified here; not available in current release |
