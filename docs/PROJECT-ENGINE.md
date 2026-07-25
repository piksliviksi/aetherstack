# Project Data Management Engine

Advanced (but practical) engine for **disk optimization**, **project → PC impact**, and **live resource pressure**.

## Start

| OS | Command |
|----|---------|
| Windows | `.\project-engine\start-engine.ps1 -Project C:\path\to\app` |
| macOS / Ubuntu / Linux | `./project-engine/start-engine.sh /path/to/app` |
| Any | `cd project-engine && python server.py --project /path` |

Dashboard: **http://127.0.0.1:8765**

Optional: `pip install -r project-engine/requirements.txt` (`psutil` for better live metrics).

## Capabilities

### Live pressure
- CPU utilization and core counts  
- Memory used / free / %  
- Per-volume disk capacity  
- Disk **read/write MB/s** (sampled)  
- GPU: NVIDIA via `nvidia-smi`; AMD name via WMI; WSL ROCm agent probe on Win11  

### Project impact
- Total size and file count (approx)  
- Top-level and **heavy** dirs (`node_modules`, `.venv`, `.git`, caches, …)  
- **Reclaimable** estimate for regenerable caches  
- Manifests: `package.json`, `requirements*.txt`, `pyproject.toml`, etc.  
- Torch/TF hints from dependency lists  

### System installations
- Docker presence + `docker system df` snippet  
- WSL distro list + `ext4.vhdx` sizes under common paths (`D:\wsl`, …)  
- Ollama models directory size  
- Python + `pip show` for torch/transformers/…  
- AetherStack repo path  

### Optimize
- **Suggestions only** — severity `safe` / `medium` / `info`  
- Never auto-deletes  

## VS Code

**AetherStack: Open Project Data Engine** opens the dashboard with `?project=<workspace>`.

## API

```
GET /api/live
GET /api/system
GET /api/project?path=C:\code\app
GET /api/full?path=C:\code\app
```

## Limits

- Full recursive size on multi-hundred-GB trees is capped by file walk limits (still useful for top-level hogs).  
- AMD **live** GPU % on Windows is limited without Adrenalin export APIs; use WSL `rocminfo` / Ollama for inference load.  
- Run the engine **on the host** (not only inside a minimal container) for accurate WSL/Docker/host disk numbers.