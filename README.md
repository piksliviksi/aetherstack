# AetherStack

![AetherStack](./aetherstack.jpg)

**Multi-model LLM control plane in Docker** — local Ollama + cloud providers (Grok, OpenAI/Codex, Claude) behind one gateway, with a chat UI and Redis for shared working memory.

| | |
|---|---|
| **Repo** | [github.com/piksliviksi/aetherstack](https://github.com/piksliviksi/aetherstack) |
| **VS Code** | [Marketplace: AetherStack.aetherstack](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack) |
| **Who it’s for** | Anyone who wants a small, shareable stack without installing a full “AI distro” |
| **GPU note** | Prefer **host Ollama** for AMD GPUs; containers handle UI + gateway |

---

## What you get

| Service | Port | Role |
|---------|------|------|
| **Open WebUI** | [http://localhost:3000](http://localhost:3000) | Chat UI |
| **LiteLLM** | [http://localhost:4000](http://localhost:4000) | One OpenAI-compatible API for local + cloud models |
| **Redis** | `6379` | Short-term / shared working memory for agents & tools |
| **Ollama** (optional container) | `11434` | Local models — better as a **native** install on AMD |

```
  Browser / IDE
        │
        ▼
  ┌─────────────┐     ┌──────────────┐
  │ Open WebUI  │────►│ Host Ollama  │  (GPU / Vulkan / ROCm)
  └─────────────┘     └──────────────┘
        │
        ▼
  ┌─────────────┐     ┌──────────────┐
  │  LiteLLM    │────►│ Grok / GPT / │  (API keys)
  │  :4000      │     │ Claude / …   │
  └─────────────┘     └──────────────┘
        │
        ▼
      Redis
```

---

## Quick start (click to run)

### Windows 11

1. Install [Docker Desktop](https://docs.docker.com/desktop/) + (optional) [Ollama](https://ollama.com).  
2. Clone this repo.  
3. **Double-click `start.bat`**  
4. Stop later with **`stop.bat`**

Full walkthrough: [docs/TUTORIAL-WINDOWS.md](./docs/TUTORIAL-WINDOWS.md)

### Ubuntu (native)

```bash
git clone https://github.com/piksliviksi/aetherstack.git
cd aetherstack
chmod +x start.sh stop.sh
./start.sh          # starts Docker services + opens browser
./stop.sh           # stop
```

Full walkthrough: [docs/TUTORIAL-UBUNTU.md](./docs/TUTORIAL-UBUNTU.md)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (Desktop on Windows, Engine on Ubuntu)  
- [Ollama](https://ollama.com) **on the host** (recommended for GPU)

```bash
ollama pull llama3.1:8b
```

```bash
cp .env.example .env
# Edit .env — OPENAI_API_KEY, XAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY
```

Manual start (any OS with Docker):

```bash
docker compose up -d
```

| Open | URL |
|------|-----|
| Chat | http://localhost:3000 |
| Gateway | http://localhost:4000 |

### 4. Optional: Ollama inside Docker

Only if you are not running host Ollama (CPU or NVIDIA-friendly setups):

```bash
docker compose --profile with-ollama-container up -d
```

### 5. AMD ROCm (Linux bare metal)

If you have `/dev/kfd` and `/dev/dri` (not typical on Windows/WSL):

```bash
docker compose -f docker-compose.yml -f docker-compose.amd.yml --profile with-ollama-container up -d
```

For many RDNA2 cards (e.g. RX 6600 XT) set in `.env`:

```env
HSA_OVERRIDE_GFX_VERSION=10.3.0
```

---

## LiteLLM models (defaults)

Configured in [`litellm_config.yaml`](./litellm_config.yaml). Aliases map to **current** provider IDs (Grok 4.x, GPT-4.1 / o-series, Claude 4, Gemini 2.5, local Ollama). Edit the YAML to add more; LiteLLM also accepts `xai/<any-xai-model>` style names if you extend the list.

| Alias | Backend |
|-------|---------|
| `local-default` / `local-llama` | Host Ollama (`llama3.1:8b`) |
| `local-tiny` | Host Ollama (`tinyllama`) |
| `grok` / `grok-4.5` | xAI Grok 4.5 |
| `grok-4.3` / `grok-4` / `grok-4-fast` / `grok-code` | xAI Grok 4.x family |
| `grok-3` | xAI Grok 3 (legacy alias) |
| `gpt-4.1` / `gpt-4.1-mini` / `gpt-4o` / `o3` / `o4-mini` | OpenAI |
| `codex` / `openai-default` | OpenAI GPT-4.1 |
| `claude` / `claude-sonnet-4` / `claude-opus-4` / `claude-haiku` | Anthropic |
| `gemini` / `gemini-2.5-pro` / `gemini-2.5-flash` | Google Gemini |

Keys in `.env`: `XAI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` (only for providers you use).

Point any OpenAI-compatible client at:

```text
Base URL: http://localhost:4000/v1
API key:  only if LITELLM_MASTER_KEY is set in .env
```

### LiteLLM 401 “No api key passed in”

**Expected.** LiteLLM always wants an API key on `/v1/*`. A normal browser tab does **not** send one.

```bash
# Windows
powershell -File scripts/list-models.ps1

# Linux / macOS
./scripts/list-models.sh

# or:
curl http://localhost:4000/v1/models -H "Authorization: Bearer sk-aether-local"
```

Default key: `sk-aether-local` (from `.env` → `LITELLM_MASTER_KEY`).  
Use **Open WebUI** at http://localhost:3000 for a UI without hand-rolling headers.

---

## GPU support

| Vendor | How |
|--------|-----|
| **NVIDIA** | Host Ollama or `docker-compose.nvidia.yml` — [docs/GPU-NVIDIA.md](./docs/GPU-NVIDIA.md) |
| **AMD** | Host/WSL Ollama or `docker-compose.amd.yml` — [docs/WSL-AMD-GPU.md](./docs/WSL-AMD-GPU.md) |
| **Intel** | Host Ollama / OpenVINO / IPEX — [docs/GPU-INTEL.md](./docs/GPU-INTEL.md) |

## Docker Desktop Extension

Optional UI inside Docker Desktop — scaffold in [`extension/`](./extension/), guide: [docs/DOCKER-EXTENSION.md](./docs/DOCKER-EXTENSION.md).

## VS Code projects

Open a folder, scan prior AI chats (Continue / Claude / Aider / WayLog / …), write `.aetherstack/project-overview.md`, and wire **Continue.dev** to AetherStack so you can keep building with every model on the gateway.

| Piece | Location |
|-------|----------|
| **Marketplace** | [AetherStack.aetherstack](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack) |
| **How to use (help)** | [docs/VSCODE-EXTENSION.md](./docs/VSCODE-EXTENSION.md) |
| Extension source | [`integrations/vscode/`](./integrations/vscode/) |
| GPU / architecture notes | [docs/VSCODE.md](./docs/VSCODE.md) |
| CLI scan | `scripts/scan-project-ai.ps1` / `scripts/scan-project-ai.sh` |

```bash
# From VS Code Marketplace (recommended)
code --install-extension AetherStack.aetherstack

# Or from this repo (dev)
code --install-extension integrations/vscode
# Command Palette → AetherStack: Scan Project AI History
# Command Palette → AetherStack: Wire Continue.dev to AetherStack
```

**Win11 + AMD:** VS Code does **not** drive the Radeon for LLMs — only Ollama (e.g. WSL ROCm) does. See [docs/VSCODE.md](./docs/VSCODE.md).

## Project Data Management Engine

Live **CPU / RAM / disk I/O / GPU**, per-project **disk impact**, **safe cleanup suggestions**, and system footprint (**WSL VHDX**, Docker, Python/torch, Ollama models, …).

```powershell
# Windows
.\project-engine\start-engine.ps1 -Project D:\code\myapp
# → http://127.0.0.1:8765
```

```bash
# Ubuntu
./project-engine/start-engine.sh /path/to/project
```

Details: [`project-engine/README.md`](./project-engine/README.md)

---

## Why host Ollama on AMD?

| Platform | Recommendation |
|----------|----------------|
| **NVIDIA** | Container GPU passthrough is mature |
| **AMD on Linux** | `ollama/ollama:rocm` *or* native Ollama |
| **Windows / WSL** | **Native Ollama** (or WSL binary); Docker GPU for AMD is often flaky |

AetherStack keeps the **reproducible control plane in Docker** and leaves **GPU inference** flexible.

---

## Project layout

```text
aetherstack/
├── docker-compose.yml      # Open WebUI, LiteLLM, Redis (+ optional Ollama)
├── docker-compose.amd.yml  # ROCm device mounts for Linux AMD
├── litellm_config.yaml     # Multi-provider model list
├── .env.example            # API keys template
├── LICENSE
└── README.md
```

---

## Security notes

- Default `WEBUI_AUTH=false` is for **local lab** use only. Enable auth before exposing ports.  
- Do not commit `.env`.  
- Change `LITELLM_MASTER_KEY` in production.  
- Bind to localhost or put a reverse proxy with TLS in front if remote.  
- Project Engine (`:8765`) only scans **cwd / home / repo / `--project`** (not whole drives). Optional: `AETHERSTACK_ENGINE_TOKEN` or `--token`.  
- Details: [docs/SECURITY-NOTES.md](./docs/SECURITY-NOTES.md).

---

## WSL + AMD GPU (optional host path)

On Windows + WSL2 with a Radeon GPU, run **Ollama inside WSL** (not in the compose profile) so ROCm can use DXCore (`/dev/dxg`).

```bash
# Debian WSL — after ROCm/librocdxg setup (see docs/WSL-AMD-GPU.md)
source /etc/profile.d/aether-rocm.sh
rocminfo | grep -A3 "Agent 2"    # expect your Radeon
sudo systemctl restart ollama
curl http://127.0.0.1:11434/
```

Scripts under `scripts/` install ROCm env and wire the Ollama systemd unit (`HSA_ENABLE_DXG_DETECTION=1`, `OLLAMA_HOST=0.0.0.0:11434`).

## Related ideas

- Capability / routing “sync matrix” between local and cloud models  
- Redis / vector DB as shared agent memory  
- Debian WSL workstation notes: [docs/WSL-AMD-GPU.md](./docs/WSL-AMD-GPU.md)

---

## License

MIT — see [LICENSE](./LICENSE).

## Credits

Built on [Ollama](https://ollama.com), [Open WebUI](https://github.com/open-webui/open-webui), [LiteLLM](https://github.com/BerriAI/litellm), and Redis.  
Not affiliated with those projects.
