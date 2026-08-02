# Security notes

This page records security review notes for AetherStack and mitigations applied.

## Ranking

| Sev | Finding | Reachable | Status |
|-----|---------|-----------|--------|
| **High** | Project engine scans caller-supplied filesystem paths over HTTP | Yes (localhost) | Mitigated — path allowlist (no whole drives) |
| **High** | Extension writes connection secrets into workspace files | Yes (user command) | Mitigated — no key in workspace |
| **Medium** | CORS was `Access-Control-Allow-Origin: *` on engine | Yes | Mitigated — tightened |
| **Medium** | Engine APIs unauthenticated on shared lab machines | Yes | Token gate — `AETHERSTACK_ENGINE_TOKEN` / `--token` |
| **Low** | LiteLLM master-key handling | Generated on first start | Keep `.env` private; no shared default key is accepted |
| **Low** | `/api/system` discloses host install layout | Localhost | By design; token when shared |
| **Info** | Host bind warning if not 127.0.0.1 | Config | Warning printed |
| **Medium** | Browser/proxy cache may retain Open WebUI auth and user responses | Local browser | Mitigated — global `no-store` |
| **Medium** | LiteLLM response cache persisted prompts/completions in Redis AOF | Local Docker volume | Mitigated — cache disabled |

---

## 1. Local HTTP engine — path inspection

### Reachability

- Process: `project-engine/server.py` (default `127.0.0.1:8765`)
- Endpoints: `GET /api/project?path=…`, `GET /api/full?path=…`
- Any local client can pass a path; without allowlist, `project_impact()` walked it.

### Risk

Local recon of directory trees (sizes, file names under heavy dirs, manifests). Bound to localhost by default, but still useful to an untrusted local process.

### Mitigation (current)

- `resolve_project_path()` allowlists **only**:
  - process cwd
  - user home
  - AetherStack repo root (`project-engine` parent)
  - optional `--project` path and its parent
- **No whole drive letters** (`C:\`…`J:\`) and **no** blanket `/var` `/opt` `/tmp`.
- Membership uses `Path.relative_to` (no `startswith` prefix tricks).
- Paths outside allowlist return HTTP **400**.
- Optional shared secret: env `AETHERSTACK_ENGINE_TOKEN` or `--token` → require header `X-Aether-Token` or `?token=` on `/api/*` (except `/api/health`).
- Static file handler blocks `..` segments + resolve-under-STATIC.
- CORS is `null` (not `*`).
- Non-localhost bind prints a warning.

### Dashboard

Compact dark UI with **dash** + **term** modes at `/`. Token field when auth is enabled.

---

## 2. Extension persists connection config into workspace

### Reachability

- Commands: **Wire Continue.dev**, **Write .vscode Settings**
- Files written under the open workspace (often git-tracked).

### Risk

API keys / gateway secrets committed to git or shared workspaces.

### Mitigation

- Continue config uses `${env:AETHERSTACK_API_KEY}` placeholder, not the live key.
- Workspace `.vscode/settings.json` stores baseUrl/UI/model only; **strips** any existing `aetherstack.apiKey`.
- API key, if set, is written to VS Code **SecretStorage** (`context.secrets`), not `settings.json`; a legacy key found in **User** settings (`ConfigurationTarget.Global`) is migrated in and cleared from config.
- Overview JSON omits secrets.

---

## 3. Other checks

| Check | Result |
|-------|--------|
| Static path traversal under `/static/` | `resolve()` + prefix check + `..` reject |
| Command injection in collectors `_run` | Fixed command lists (no shell), low risk |
| WSL `rocminfo` via `wsl -d Debian` | Fixed args; local only |
| Docker compose secrets in repo | `.env` gitignored; `.env.example` has placeholders only |
| Open WebUI authentication | Enabled by default; port 3000 is loopback-only |
| Open WebUI password storage | Bcrypt hashes in the private Docker data volume; no plaintext password cache |
| Browser/proxy caching | `CACHE_CONTROL=no-cache, no-store, must-revalidate, max-age=0` |
| Open WebUI data permissions | Startup applies `umask 077` and removes group/other access |
| LiteLLM response caching | Disabled; prompts/completions are not written to Redis cache/AOF |

---

## Operator rules

| Rule | Requirement |
|------|-------------|
| Project Engine bind | `127.0.0.1` only unless token + network policy applied |
| `LITELLM_MASTER_KEY` | Strong value when ports are LAN-reachable |
| Continue key | `AETHERSTACK_API_KEY` env; never commit keys |
| Shared machines | `AETHERSTACK_ENGINE_TOKEN` before starting the engine |
| `.continue/config.yaml` | No secrets in git; gitignore local overrides |
| Open WebUI volume | Treat `webui.db`, WAL, uploads, and vector DB as sensitive user data |
