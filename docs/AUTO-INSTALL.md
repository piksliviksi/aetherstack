# Optional auto-install of missing packages

Aether can **detect** missing pieces (scan) and optionally **install** them.  
**Default is OFF** — nothing is installed until you opt in.

| Piece | Location |
|-------|----------|
| Policy | [`aether-hub/bootstrap.yaml`](../aether-hub/bootstrap.yaml) |
| Hub API | http://127.0.0.1:8766/api/bootstrap |
| Windows | `.\scripts\auto-install.ps1` |
| Linux/macOS | `./scripts/auto-install.sh` |

---

## What it can install

| Category | Examples | Safe auto? |
|----------|----------|------------|
| **python_pip** | `redis`, `PyYAML`, `psutil` | Yes |
| **ollama_models** | `tinyllama`, `nomic-embed-text` | Yes (if Ollama up) |
| **docker_compose_services** | redis, litellm, hub, open-webui | Yes |
| **docker_images** | pull base images | Yes (optional) |
| **host_tools** | WSL ROCm Ollama package, portproxy, stop dual Ollama | **No** — needs `-IncludeElevated` / host script |

---

## Quick use

### Dry-run (always safe)

```powershell
.\scripts\auto-install.ps1
# or
curl -s http://127.0.0.1:8766/api/bootstrap?refresh=1 | jq .actions
```

### Enable + apply safe installs

```powershell
.\scripts\auto-install.ps1 -Enable -Yes
```

```bash
./scripts/auto-install.sh --enable --yes
```

### Include elevated host fixes (AMD / WSL)

```powershell
.\scripts\auto-install.ps1 -Yes -IncludeElevated
```

This may:

- Stop Windows Ollama when WSL Ollama is preferred  
- Fix `localhost:11434` → WSL via portproxy  
- Re-run Ollama install script for **ROCm** libs in Debian WSL (large download)

---

## Hub API

```bash
# Status + plan (from latest discover)
curl -s "http://127.0.0.1:8766/api/bootstrap?refresh=1" | jq .

# Turn on
curl -s -X POST http://127.0.0.1:8766/api/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"enabled":true}'

# Dry-run apply
curl -s -X POST http://127.0.0.1:8766/api/bootstrap/run \
  -H "Content-Type: application/json" \
  -d '{"confirm":true,"dry_run":true,"only_safe":true}'

# Real apply (safe actions only from inside hub)
curl -s -X POST http://127.0.0.1:8766/api/bootstrap/run \
  -H "Content-Type: application/json" \
  -d '{"confirm":true,"dry_run":false,"only_safe":true}'
```

Env equivalent: `AETHER_AUTO_INSTALL=1` (enables; still needs `confirm` unless `auto_apply`).

---

## Flow

```
scan-system /api/discover
        ↓
 /api/bootstrap     → plan of missing pieces
        ↓
 user enables + confirms
        ↓
 auto-install.ps1 / hub run
        ↓
 pip · ollama pull · compose up · (optional) WSL ROCm
        ↓
 discover again
```

---

## Safety

1. **Off by default** — no surprise installs.  
2. **confirm=true** required to apply (unless `auto_apply`).  
3. **Elevated** actions never run from hub alone; host script + `-IncludeElevated`.  
4. Does **not** write cloud API keys or touch billing.  
5. Large models skipped if host reports low RAM (see `bootstrap.yaml` limits).

---

## Start script integration

```powershell
# Normal start (scan only, no install)
.\start.ps1

# Start with auto-install of missing safe packages
.\start.ps1 -AutoInstall
```
