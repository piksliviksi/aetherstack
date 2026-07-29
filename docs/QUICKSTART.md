# Quick start

Root overview: [README](../README.md).  
Operating model: [OPERATING-MODEL.md](./OPERATING-MODEL.md).

---

## Prerequisites

| Item | Requirement |
|------|-------------|
| Docker | Desktop (Windows/macOS) or Engine (Linux) |
| Ollama | Host install for Metal / Vulkan / ROCm / CUDA inference |
| Cloud keys | Only for providers in use |

```bash
ollama pull llama3.1:8b
# Embeddings for hub memory (higher quality):
# ollama pull nomic-embed-text
```

```bash
cp .env.example .env
# Set: LITELLM_MASTER_KEY, and provider keys as needed
```

Example lab master key: `sk-aether-local` (`LITELLM_MASTER_KEY`).

---

## Start / stop

| OS | Start | Stop | Tutorial |
|----|--------|------|----------|
| Windows | `start.bat` or `.\start.ps1` | `stop.bat` | [TUTORIAL-WINDOWS.md](./TUTORIAL-WINDOWS.md) |
| macOS | `./start.sh` | `./stop.sh` | [TUTORIAL-MACOS.md](./TUTORIAL-MACOS.md) |
| Ubuntu/Linux | `./start.sh` | `./stop.sh` | [TUTORIAL-UBUNTU.md](./TUTORIAL-UBUNTU.md) |

```bash
docker compose up -d
docker compose down
```

Auto-install of missing pieces: off by default — [AUTO-INSTALL.md](./AUTO-INSTALL.md).

---

## Endpoints

| Surface | URL |
|---------|-----|
| Open WebUI | http://localhost:3000 |
| LiteLLM | http://localhost:4000 |
| OpenAI-compatible API | http://localhost:4000/v1 |
| Aether Hub | http://localhost:8766 |
| Node canvas | http://localhost:8766/graph |
| Redis | `localhost:6379` |
| Host Ollama | http://127.0.0.1:11434 |

---

## IDE client

```text
Base URL:  http://127.0.0.1:4000/v1
API key:   <LITELLM_MASTER_KEY>
Model:     one alias (e.g. local-default, claude-sonnet-4)
```

- Extension: [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md)  
- Aliases: [GATEWAY.md](./GATEWAY.md) · [`litellm_config.yaml`](../litellm_config.yaml)

**HTTP 401 without Authorization:** expected for bare browser hits on `:4000`. Use WebUI, IDE client, or:

```bash
# Windows
powershell -File scripts/list-models.ps1
# Linux / macOS
./scripts/list-models.sh
curl http://localhost:4000/v1/models -H "Authorization: Bearer sk-aether-local"
```

---

## Operator checks

```bash
python scripts/runtime-smoke.py
# Optional full live preset sweep:
python scripts/runtime-smoke.py --all-services
curl -s http://127.0.0.1:8766/api/discover | jq .summary
# Windows:  .\scripts\scan-system.ps1
# Unix:     ./scripts/scan-system.sh
curl -s "http://127.0.0.1:8766/api/route?need=code&prefer=local"
```

---

## Compose profiles

**Ollama in Docker** (no host Ollama):

```bash
docker compose --profile with-ollama-container up -d
```

**AMD ROCm Linux bare metal** (`/dev/kfd`, `/dev/dri`):

```bash
docker compose -f docker-compose.yml -f docker-compose.amd.yml --profile with-ollama-container up -d
```

RDNA2 example in `.env`:

```env
HSA_OVERRIDE_GFX_VERSION=10.3.0
```

| Platform | Inference path |
|----------|----------------|
| macOS | Host Ollama + Metal |
| NVIDIA | Host Ollama or `docker-compose.nvidia.yml` |
| AMD Linux | ROCm Ollama native or `ollama/ollama:rocm` |
| Windows + Radeon | Host/WSL Ollama — [WSL-AMD-GPU.md](./WSL-AMD-GPU.md), [AMD-COMPUTE.md](./AMD-COMPUTE.md) |

Docker holds the control plane. GPU inference runs on the host path above.

NVIDIA: [GPU-NVIDIA.md](./GPU-NVIDIA.md).

---

## Repository layout

```text
aetherstack/
├── docker-compose.yml
├── docker-compose.amd.yml
├── docker-compose.nvidia.yml
├── litellm_config.yaml
├── .env.example
├── start.* / stop.*
├── aether-hub/
├── aether-amd/
├── combos/
├── pipelines/
├── project-engine/
├── integrations/vscode/
├── scripts/
└── docs/
```

---

## Security defaults

| Default | Constraint |
|---------|------------|
| `WEBUI_AUTH=true` | Hardcoded in `docker-compose.yml`; port 3000 stays loopback-only, signed in via the local proxy. |
| `.env` | Not committed. |
| `LITELLM_MASTER_KEY` | Rotate before shared or remote use. |
| Bind | Localhost or TLS reverse proxy for remote access. |

Details: [SECURITY-NOTES.md](./SECURITY-NOTES.md).
