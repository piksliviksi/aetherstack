# AetherStack

**Multi-model LLM control plane in Docker** — local Ollama + cloud providers (Grok, OpenAI/Codex, Claude) behind one gateway, with a chat UI and Redis for shared working memory.

| | |
|---|---|
| **Repo** | [github.com/piksliviksi/aetherstack](https://github.com/piksliviksi/aetherstack) |
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

## Quick start

### 1. Prerequisites

- [Docker](https://docs.docker.com/get-docker/) / Docker Desktop  
- [Ollama](https://ollama.com) **on the host** (recommended for GPU)

```bash
# Install a small local model (example)
ollama pull llama3.1:8b
```

### 2. Clone & configure

```bash
git clone https://github.com/piksliviksi/aetherstack.git
cd aetherstack
cp .env.example .env
# Edit .env — add OPENAI_API_KEY, XAI_API_KEY, ANTHROPIC_API_KEY as needed
```

### 3. Start the control plane

```bash
docker compose up -d
```

This starts **Open WebUI**, **LiteLLM**, and **Redis**.  
They talk to host Ollama at `http://host.docker.internal:11434`.

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

Configured in [`litellm_config.yaml`](./litellm_config.yaml):

| Alias | Backend |
|-------|---------|
| `local-llama` | Host Ollama `llama3.1:8b` |
| `grok` | xAI (needs `XAI_API_KEY`) |
| `gpt-4o` | OpenAI (needs `OPENAI_API_KEY`) |
| `claude` | Anthropic (needs `ANTHROPIC_API_KEY`) |

Point any OpenAI-compatible client at:

```text
Base URL: http://localhost:4000/v1
API key:  value of LITELLM_MASTER_KEY (default sk-aether-local)
```

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

---

## Related ideas

- Capability / routing “sync matrix” between local and cloud models  
- Redis / vector DB as shared agent memory  
- Debian WSL workstation notes (optional host path, not required to use this repo)

---

## License

MIT — see [LICENSE](./LICENSE).

## Credits

Built on [Ollama](https://ollama.com), [Open WebUI](https://github.com/open-webui/open-webui), [LiteLLM](https://github.com/BerriAI/litellm), and Redis.  
Not affiliated with those projects.
