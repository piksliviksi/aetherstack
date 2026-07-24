# AetherStack as a Docker Desktop Extension

Docker Extensions are a supported way to ship a UI + optional backend next to Docker Desktop. AetherStack maps well:

| Extension piece | AetherStack mapping |
|-----------------|---------------------|
| UI panel | Start/stop status, links to :3000 / :4000 |
| Backend / compose | Existing `docker-compose.yml` |
| Marketplace | Optional later publish |

## What we ship in-repo

Directory: [`extension/`](../extension/)

| File | Role |
|------|------|
| `metadata.json` | Extension metadata + compose path |
| `Dockerfile` | Packages UI + metadata |
| `docker-compose.yaml` | Points at parent stack services |
| `ui/index.html` | Minimal dashboard (open Chat / Gateway) |

## Build & install (developer)

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

## Limitations

- Extensions run in **Docker Desktop** (Windows/Mac), not headless Linux servers.  
- GPU still follows host rules (NVIDIA Desktop GPU, AMD via host Ollama, etc.).  
- Marketplace listing needs Docker’s review process — local install is enough for development.

## Alternative

For most users, **`start.bat` / `./start.sh` is simpler** than an Extension. The Extension is optional polish for Docker Desktop users.
