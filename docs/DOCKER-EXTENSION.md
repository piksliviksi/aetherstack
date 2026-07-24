# AetherStack as a Docker Desktop Extension

Ship a small panel in Docker Desktop that links to the AetherStack control plane.

| Extension piece | Mapping |
|-----------------|---------|
| UI panel | Status links to `:3000` / `:4000` |
| Backend / compose | Root `docker-compose.yml` services |
| Marketplace | Optional later publish |

## What we ship in-repo

Directory: [`extension/`](../extension/)

| File | Role |
|------|------|
| `metadata.json` | Extension metadata + compose path |
| `Dockerfile` | Packages UI + metadata |
| `docker-compose.yaml` | Control-plane services |
| `ui/index.html` | Minimal dashboard (Chat / Gateway) |

## Build & install

Requires Docker Desktop with Extensions enabled.

```bash
cd aetherstack/extension
docker build -t piksliviksi/aetherstack-extension:latest .
docker extension install piksliviksi/aetherstack-extension:latest
```

Update after code changes:

```bash
docker extension update piksliviksi/aetherstack-extension:latest
# or: docker extension rm ... && docker extension install ...
```

Open **Docker Desktop → Extensions → AetherStack**.

## Notes

- Extensions run in **Docker Desktop** (Windows/Mac), not headless Linux servers.  
- GPU inference still follows host setup (NVIDIA, AMD host/WSL Ollama, Intel host tools).  
- Marketplace listing needs Docker’s process; local install is enough for development.  
- For most users, **`start.bat` / `./start.sh`** is the primary way to run the stack.
