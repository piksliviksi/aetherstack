# AetherStack Project Data Management Engine

Disk footprint, system dependencies (WSL, Python, torch, Docker…), and **live** CPU / memory / disk / GPU pressure — per project and whole PC.

Dashboard: compact dark UI with a **terminal** mode (`dash` / `term` tabs).

## Quick start

```bash
# From repo root (AetherStack)
cd project-engine
python server.py
# Dashboard: http://127.0.0.1:8765
# Optional project: python server.py --project C:\path\to\myapp
```

Windows:

```powershell
.\project-engine\start-engine.ps1
# or with project:
.\project-engine\start-engine.ps1 -Project D:\code\myapp

# Optional API token (shared secret for /api/*)
$env:AETHERSTACK_ENGINE_TOKEN = "your-secret"
.\project-engine\start-engine.ps1 -Project D:\code\myapp
```

Ubuntu:

```bash
chmod +x project-engine/start-engine.sh
./project-engine/start-engine.sh /path/to/project

export AETHERSTACK_ENGINE_TOKEN=your-secret
./project-engine/start-engine.sh /path/to/project
```

## What it shows

| Area | Content |
|------|---------|
| **Live pressure** | CPU %, RAM used/available, disk free/total, disk I/O rates, GPU (NVIDIA / AMD probes) |
| **Project impact** | Folder size, heavy dirs, estimated reclaimable space, manifests, suggestions |
| **Installations** | WSL VHDX, Docker, Python, torch, Ollama, AetherStack |
| **Terminal UI** | Commands: `help`, `live`, `sys`, `scan`, `roots`, `neofetch`, `matrix`, … |

## Safety

- **Read-only by default** — no automatic deletes.
- Project scans limited to **cwd, home, AetherStack repo, `--project`** (and its parent). No whole-drive allowlist.
- Optional auth: `AETHERSTACK_ENGINE_TOKEN` or `--token` → send `X-Aether-Token` (dashboard token field / `?token=`).
- Optimize mode only **lists** candidates; you confirm cleanup yourself.

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard HTML (dash + term) |
| `GET /api/live` | Live CPU/RAM/disk/GPU snapshot |
| `GET /api/project?path=` | Project disk + deps + suggestions |
| `GET /api/system` | System installations / footprint |
| `GET /api/full?path=` | Combined report |
| `GET /api/roots` | Allowed scan roots |
| `GET /api/health` | Liveness (no token required) |

When a token is configured, all `/api/*` routes except `/api/health` require `X-Aether-Token` or `?token=`.

## VS Code

Command palette (after installing the [Marketplace extension](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack)):

- **AetherStack: Open Project Engine** → `http://127.0.0.1:8765/?project=<workspace>`

## Architecture

```
Browser / VS Code
       │
       ▼
 project-engine :8765  (Python stdlib HTTP)
       │
       ├─ live collectors (psutil if installed, else OS fallbacks)
       ├─ project walker (disk + manifests) — path-gated
       └─ system probes (WSL, Docker, Python, torch, …)
```
