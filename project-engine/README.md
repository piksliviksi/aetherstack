# AetherStack Project Data Management Engine

Disk footprint, system dependencies (WSL, Python, torch, Docker…), and **live** CPU / memory / disk / GPU pressure — per project and whole PC.

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
```

Ubuntu:

```bash
chmod +x project-engine/start-engine.sh
./project-engine/start-engine.sh /path/to/project
```

## What it shows

| Area | Content |
|------|---------|
| **Live pressure** | CPU %, RAM used/available, disk free/total, disk queue & transfer rates (when available), GPU (NVIDIA `nvidia-smi`, AMD best-effort) |
| **Project impact** | Folder size, heavy dirs (`node_modules`, `.venv`, `.git`, caches), estimated reclaimable space |
| **Installations** | Detected: WSL distros/VHDX, Docker, Python envs, torch/CUDA hints, Ollama models dir, AetherStack |
| **Dependencies** | `requirements*.txt`, `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod` summaries |
| **Optimize** | Actionable suggestions (safe cleanup targets, not auto-delete by default) |

## Safety

- **Read-only by default** — no automatic deletes.
- Optimize mode only **lists** candidates; you confirm cleanup yourself.
- Live metrics use OS APIs only on the machine where the engine runs (not inside a GPU-less container unless you mount hosts).

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard HTML |
| `GET /api/live` | Live CPU/RAM/disk/GPU snapshot |
| `GET /api/project?path=` | Project disk + deps + suggestions |
| `GET /api/system` | System installations / footprint |
| `GET /api/full?path=` | Combined report |

## VS Code

Command palette (after installing `integrations/vscode`):

- **AetherStack: Open Project Engine** → `http://127.0.0.1:8765/?project=<workspace>`

## Architecture

```
Browser / VS Code
       │
       ▼
 project-engine :8765  (Python stdlib HTTP)
       │
       ├─ live collectors (psutil if installed, else OS fallbacks)
       ├─ project walker (disk + manifests)
       └─ system probes (WSL, Docker, Python, torch, …)
```
