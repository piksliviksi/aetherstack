# Security notes (validated findings)

This page records security review notes for AetherStack and mitigations applied.

## Ranking

| Sev | Finding | Reachable? | Status |
|-----|---------|------------|--------|
| **High** | Project engine scans **caller-supplied filesystem paths** over HTTP | Yes (localhost) | **Mitigated** — path allowlist |
| **High** | Extension writes **connection secrets** into workspace files | Yes (user command) | **Mitigated** — no key in workspace |
| **Medium** | CORS was `Access-Control-Allow-Origin: *` on engine | Yes | **Mitigated** — tightened |
| **Low** | Default LiteLLM master key `sk-aether-local` | Lab default | Documented; change for exposure |
| **Low** | `/api/system` discloses host install layout | Localhost only | By design for local engine |
| **Info** | Host bind warning if not 127.0.0.1 | Config | Warning printed |

---

## 1. Local HTTP engine — arbitrary path inspection

### Reachability

- Process: `project-engine/server.py` (default `127.0.0.1:8765`)
- Endpoints: `GET /api/project?path=…`, `GET /api/full?path=…`
- Any local client can pass a path; before mitigation, `project_impact()` walked it.

### Exact lines (pre-fix)

- `project-engine/server.py`: query parse `path` / `project` → `project_impact(project)` / `full_report(project)`
- `project-engine/collectors.py`: `project_impact()` → `Path(...).resolve()` + `os.walk`

### Risk

Local recon of directory trees (sizes, file names under heavy dirs, manifests). Bound to localhost by default, but still dangerous if a browser or local malware can hit the API.

### Mitigation

- `resolve_project_path()` allowlists roots: cwd, home, AetherStack repo, optional `--project`, drive letters / common Unix roots.
- Paths outside allowlist return HTTP 400.
- Static file handler blocks `..` segments.
- CORS no longer `*`.
- Non-localhost bind prints a warning.

---

## 2. Extension persists connection config into workspace

### Reachability

- Commands: **Wire Continue.dev**, **Write .vscode Settings**
- Files written under the open workspace (often git-tracked).

### Exact lines (pre-fix)

- `integrations/vscode/extension.js` — `continueConfigYaml()` embedded `apiKey: ${c.apiKey}`
- Same file — `configureWorkspace` set `settings["aetherstack.apiKey"] = c.apiKey` then wrote `.vscode/settings.json`
- `buildOverview()` previously dumped full `cfg()` including apiKey into `.aetherstack/project-overview.json`

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
| Static path traversal under `/static/` | Already had `resolve()` + prefix check; added `..` reject |
| Command injection in collectors `_run` | Fixed command lists (no shell), low risk |
| WSL `rocminfo` via `wsl -d Debian` | Fixed args; local only |
| Docker compose secrets in repo | `.env` gitignored; `.env.example` has placeholders only |
| Open WebUI `WEBUI_AUTH=false` | Local lab convenience; do not expose port 3000 publicly |

---

## Operator guidance

1. Keep Project Engine on **127.0.0.1** only.  
2. Set `LITELLM_MASTER_KEY` to a strong value if ports are LAN-reachable.  
3. Use `AETHERSTACK_API_KEY` env for Continue; never commit keys.  
4. Add `.continue/config.yaml` to git carefully (no secrets); prefer `.gitignore` for local overrides if needed.  
