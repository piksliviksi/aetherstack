# Control-plane authentication (E1)

**Status:** implemented for Hub API gate + local JWT + optional OIDC  
**SKU:** Desktop off by default · Team Server / Cloud on  
**Related:** [MULTI-USER.md](./MULTI-USER.md) · [ENTERPRISE-PLATFORM.md](./ENTERPRISE-PLATFORM.md) · [ENTERPRISE-ROADMAP.md](./ENTERPRISE-ROADMAP.md)

## Behaviour

| Mode | When | Hub `/api/*` |
|------|------|--------------|
| **Desktop open** | `AETHER_REQUIRE_AUTH=0` and edition `desktop` | Unauthenticated (single operator), as before |
| **Required auth** | `AETHER_REQUIRE_AUTH=1` **or** `AETHER_EDITION=team\|cloud` | Bearer required except public paths |

**Public when auth required:**

| Method | Path |
|--------|------|
| GET | `/api/health` |
| GET | `/api/auth/config` |
| POST | `/api/auth/token` (body must include valid master key) |

Static UI paths (`/`, `/graph`, …) stay loadable; data APIs do not.

**Non-loopback bind:** allowed only when auth is required (see Hub startup check).

## Credentials

1. **Master key** — `Authorization: Bearer $LITELLM_MASTER_KEY` → `platform-admin`
2. **Local JWT (HS256)** — minted with master key; signed by `AETHER_JWT_SECRET` or master key
3. **OIDC JWT** — when `AETHER_OIDC_ISSUER` (+ JWKS) is set; requires `PyJWT[crypto]` in the Hub image

## Mint a user token (air-gap / Team Server)

```bash
curl -s http://127.0.0.1:8766/api/auth/token \
  -H 'Content-Type: application/json' \
  -d '{
    "master_key": "sk-…",
    "user_id": "alice",
    "email": "alice@example.com",
    "role": "member"
  }'
# → { "access_token": "eyJ…", "token_type": "Bearer", "expires_in": 86400, … }

curl -s http://127.0.0.1:8766/api/auth/me \
  -H "Authorization: Bearer eyJ…"
```

## Tenancy (M0 primitives)

File store: `AETHER_TENANCY_FILE` (default `.aetherstack/tenancy.json`).

| Method | Path | Notes |
|--------|------|--------|
| GET | `/api/tenancy` | Snapshot |
| GET/POST | `/api/tenancy/projects` | List / create (creator becomes owner) |
| GET | `/api/tenancy/projects/{id}` | Project + memberships |
| POST | `/api/tenancy/projects/{id}/members` | Owner/admin adds member |
| DELETE | `/api/tenancy/projects/{id}/members/{user}` | Owner/admin removes |

Optional request header: `X-AetherStack-Project: {project_id}` attaches project role to the context.

Memory namespace convention: `project:{project_id}` (enforced in later milestones for all memory writes).

## Env reference

See `.env.example` and `.env.team.example`. Compose passes auth vars through `docker-compose.yml` / `docker-compose.team.yml`.

## Not in E1

- Browser OIDC login UI / PKCE flow  
- Per-user LiteLLM virtual keys  
- Automatic memory namespace isolation on every store path (schemas + project create only)  
- File leases (M2)  

## Code

| Module | Role |
|--------|------|
| `aether-hub/auth.py` | require_auth, JWT mint/verify, OIDC, request gate helpers |
| `aether-hub/tenancy.py` | teams/projects/memberships |
| `aether-hub/server.py` | wires gate + routes |
| `aether-hub/test_auth.py` | unit tests |
