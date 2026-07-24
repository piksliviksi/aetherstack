# Security notes (validated findings)

This page records security review notes for AetherStack and mitigations applied.

## Ranking

| Sev | Finding | Reachable? | Status |
|-----|---------|------------|--------|
| **High** | Project engine scans **caller-supplied filesystem paths** over HTTP | Yes (localhost) | **Mitigated** — narrow path allowlist (no whole drives) |
| **High** | Extension writes **connection secrets** into workspace files | Yes (user command) | **Mitigated** — no key in workspace |
| **Medium** | CORS was `Access-Control-Allow-Origin: *` on engine | Yes | **Mitigated** — tightened |
| **Medium** | Engine APIs unauthenticated on shared lab machines | Optional | **Optional token** — `AETHERSTACK_ENGINE_TOKEN` / `--token` |
| **Low** | Default LiteLLM master key `sk-aether-local` | Lab default | Documented; change for exposure |
| **Low** | `/api/system` discloses host install layout | Localhost only | By design; gate with token if needed |
| **Info** | Host bind warning if not 127.0.0.1 | Config | Warning printed |

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
- API key, if set, is written to **User** settings (`ConfigurationTarget.Global`) only.
- Overview JSON omits secrets.

---

## 3. Other checks

| Check | Result |
|-------|--------|
| Static path traversal under `/static/` | `resolve()` + prefix check + `..` reject |
| Command injection in collectors `_run` | Fixed command lists (no shell), low risk |
| WSL `rocminfo` via `wsl -d Debian` | Fixed args; local only |
| Docker compose secrets in repo | `.env` gitignored; `.env.example` has placeholders only |
| Open WebUI `WEBUI_AUTH=false` | Local lab convenience; do not expose port 3000 publicly |

---

## Operator guidance

1. Keep Project Engine on **127.0.0.1** only.  
2. Set `LITELLM_MASTER_KEY` to a strong value if ports are LAN-reachable.  
3. Use `AETHERSTACK_API_KEY` env for Continue; never commit keys.  
4. For shared machines: `set AETHERSTACK_ENGINE_TOKEN=…` before starting the engine.  
5. Add `.continue/config.yaml` to git carefully (no secrets); prefer `.gitignore` for local overrides if needed.  
