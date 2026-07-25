# Quick start

Service pitch and benefits: root [README](../README.md).  
Operating philosophy: [OPERATING-MODEL.md](./OPERATING-MODEL.md).

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (Desktop on Windows/macOS, Engine on Linux)
- [Ollama](https://ollama.com) **on the host** (recommended for GPU / Metal / ROCm / CUDA)
- Optional cloud keys for providers you actually use

```bash
ollama pull llama3.1:8b
# optional better embeddings for hub memory:
# ollama pull nomic-embed-text
```

```bash
cp .env.example .env
# Edit: LITELLM_MASTER_KEY, XAI_API_KEY, OPENAI_API_KEY,
#       ANTHROPIC_API_KEY, GOOGLE_API_KEY — only what you need
```

Default gateway key in examples: `sk-aether-local` (from `LITELLM_MASTER_KEY`).

---

## Start / stop

| OS | Start | Stop | Full tutorial |
|----|--------|------|----------------|
| Windows | `start.bat` or `.\start.ps1` | `stop.bat` | [TUTORIAL-WINDOWS.md](./TUTORIAL-WINDOWS.md) |
| macOS | `./start.sh` | `./stop.sh` | [TUTORIAL-MACOS.md](./TUTORIAL-MACOS.md) |
| Ubuntu/Linux | `./start.sh` | `./stop.sh` | [TUTORIAL-UBUNTU.md](./TUTORIAL-UBUNTU.md) |

Manual:

```bash
docker compose up -d
docker compose down
```

Optional auto-install of missing pieces (off by default): [AUTO-INSTALL.md](./AUTO-INSTALL.md).

---

## URLs after start

| Surface | URL |
|---------|-----|
| Open WebUI (chat) | http://localhost:3000 |
| LiteLLM gateway | http://localhost:4000 |
| OpenAI-compatible API | http://localhost:4000/v1 |
| Aether Hub (operator) | http://localhost:8766 |
| Node canvas | http://localhost:8766/graph |
| Redis | `localhost:6379` |
| Host Ollama | http://127.0.0.1:11434 |

---

## Wire the IDE once

Any OpenAI-compatible client (Continue, Cline, custom OpenAI base):

```text
Base URL:  http://127.0.0.1:4000/v1
API key:   <LITELLM_MASTER_KEY from .env>
Model:     one alias (e.g. local-default, claude-sonnet-4)
```

- VS Code extension: [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md)  
- Model alias list: [GATEWAY.md](./GATEWAY.md) · [`litellm_config.yaml`](../litellm_config.yaml)

**LiteLLM 401 without a key is expected** — browsers do not send `Authorization`. Use WebUI, the extension, or:

```bash
# Windows
powershell -File scripts/list-models.ps1
# Linux / macOS
./scripts/list-models.sh
# or
curl http://localhost:4000/v1/models -H "Authorization: Bearer sk-aether-local"
```

---

## First operator checks

```bash
# What is available?
curl -s http://127.0.0.1:8766/api/discover | jq .summary

# Host deep scan (GPU / WSL / ports)
# Windows:  .\scripts\scan-system.ps1
# Unix:     ./scripts/scan-system.sh

# Prefer local for code
curl -s "http://127.0.0.1:8766/api/route?need=code&prefer=local"
```

---

## Optional compose profiles

**Ollama inside Docker** (only if not using host Ollama — CPU or NVIDIA-friendly):

```bash
docker compose --profile with-ollama-container up -d
```

**AMD ROCm on Linux bare metal** (`/dev/kfd`, `/dev/dri`):

```bash
docker compose -f docker-compose.yml -f docker-compose.amd.yml --profile with-ollama-container up -d
```

Often for RDNA2 (e.g. RX 6600 XT) in `.env`:

```env
HSA_OVERRIDE_GFX_VERSION=10.3.0
```

Preferred on Windows+AMD: **host/WSL Ollama**, not the container path — [WSL-AMD-GPU.md](./WSL-AMD-GPU.md), [AMD-COMPUTE.md](./AMD-COMPUTE.md).

**NVIDIA** passthrough: [GPU-NVIDIA.md](./GPU-NVIDIA.md) · `docker-compose.nvidia.yml`.

---

## Why host Ollama?

| Platform | Recommendation |
|----------|----------------|
| macOS (Apple Silicon / Intel) | Host Ollama + **Metal** |
| NVIDIA | Host Ollama or container GPU passthrough |
| AMD on Linux | ROCm Ollama native or `ollama/ollama:rocm` |
| Windows / WSL + Radeon | Native/WSL Ollama; Docker GPU for AMD is often flaky |

Docker keeps the **control plane** reproducible; **GPU inference** stays flexible on the host.

---

## Project layout (repo)

```text
aetherstack/
├── docker-compose.yml         # WebUI, LiteLLM, Redis, Hub
├── docker-compose.amd.yml     # ROCm mounts (Linux AMD)
├── docker-compose.nvidia.yml  # NVIDIA passthrough
├── litellm_config.yaml        # Gateway model aliases
├── .env.example
├── start.* / stop.*
├── aether-hub/                # Operator hub service
├── aether-amd/                # AMD userspace adapter
├── combos/                    # Shareable multi-LLM packs
├── pipelines/                 # Pipeline scripts + votes
├── project-engine/            # Footprint / cleanup UI
├── integrations/vscode/       # Extension source
├── scripts/                   # Scan, install, GPU helpers
└── docs/                      # This documentation tree
```

---

## Security (lab defaults)

- `WEBUI_AUTH=false` is for **local lab** only — enable auth before exposing ports  
- Do not commit `.env`; change `LITELLM_MASTER_KEY` for anything shared  
- Prefer localhost bind or TLS reverse proxy if remote  

Details: [SECURITY-NOTES.md](./SECURITY-NOTES.md).
