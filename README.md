# AetherStack

![AetherStack](./aetherstack.jpg)

**One setup. One chat window. Many models underneath.**

AetherStack is a **multi-model LLM control plane**: you configure it once, import decision trees / pipelines / node graphs, set **token and tier limits**, then work in **VS Code or Open WebUI as if you were talking to a single model** (like Grok or Claude). Behind that façade, Aether routes research, critique, coding, and testing across local GPU models and cloud providers — with shared memory, slash hygiene, and optional spend controls.

| | |
|---|---|
| **Repo** | [github.com/piksliviksi/aetherstack](https://github.com/piksliviksi/aetherstack) |
| **VS Code** | [Marketplace: AetherStack.aetherstack](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack) |
| **Who it’s for** | Developers who want one IDE chat surface and a flexible multi-LLM engine underneath |
| **Platforms** | **Windows 11**, **macOS** (Intel / **Apple Silicon ARM + Metal**), **Ubuntu/Linux** |
| **GPU note** | Host Ollama must use **compute engines**: Metal (Mac ARM), **ROCm/HIP CUs** (AMD), CUDA (NVIDIA); Docker = UI/gateway only |

---

## How AetherStack operates (modus operandi)

### The idea

| Outside (what you feel) | Inside (what actually runs) |
|-------------------------|-----------------------------|
| **One** chat in VS Code / Continue / Open WebUI | LiteLLM gateway + hub routers + pipelines |
| **One** model name (e.g. `local-default` or a combo alias) | Mastermind, critic, workers, testers — different makers/tiers |
| Normal conversation | Optional multi-stage graph: research → critique → build → test |
| You don’t reconfigure providers every prompt | Decision trees, combos, and node graphs you imported once |

You set policy **once**. Day to day you only talk to **Aether**.

### One-time setup

1. **Install the stack** — Docker Compose (Open WebUI, LiteLLM, Redis, Aether Hub) + host Ollama for local GPU.  
2. **Put keys in `.env`** — only the cloud providers you use (`XAI_`, `OPENAI_`, `ANTHROPIC_`, `GOOGLE_`, master key).  
3. **Scan the machine** — `scripts/scan-system` / Hub `/api/discover` sees Ollama, GPU/CUs, missing packages.  
4. **Import decision trees** — combos, pipeline scripts, or a **node graph** from GitHub/email (`combos/export`, `pipelines/catalog`, canvas at `/graph`).  
5. **Set limits** — token saver on/off; per-role `max_cost` / tier pins; pipeline `hw_weight` / cost bias; LiteLLM master key as the single client secret.  
6. **Wire the IDE once** — VS Code extension + Continue (or any OpenAI-compatible client) → `http://127.0.0.1:4000/v1` with one Bearer key. Pick **one** gateway model (or “Aether” combo) and leave it.

After that you do **not** hop between Claude.app, Grok, and ChatGPT for normal work. You stay in **one window**.

### Daily use (single surface)

```text
  You  ──type in VS Code / Open WebUI──►  “one model” façade
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    ▼                                                   ▼
              LiteLLM :4000                                      Aether Hub :8766
           (OpenAI-compatible)                          (routes, graphs, memory, slash)
                    │                                                   │
        ┌───────────┼───────────┐                         pipelines / combos / nodes
        ▼           ▼           ▼                         master · analyser · workers
     Ollama      Grok/xAI    Claude/GPT/…                 token saver · /clear after /done
    (Metal/ROCm/CUDA)        (cloud keys)
                    │
                    └──────────────► Redis (cache + shared agent memory)
```

- **You** chat in one thread, same as with a single product model.  
- **Hub** (if multi-agent / pipeline is active) splits work: e.g. high-tier research, another maker for critique/ack, cheap/local for bulk code and tests.  
- **Memory** keeps decisions when you `/done` and `/clear` or `/compact`, so context stays lean without losing history.  
- **GPU** stays on the host (not inside VS Code). The IDE only speaks HTTP to the gateway.

### Policy you control (without changing the chat UI)

| Policy | Where |
|--------|--------|
| Which models exist | `litellm_config.yaml` + Ollama pulls |
| Who is master / critic / worker / tester | Combos, pipelines, **node canvas** (`/graph`) |
| Tier & cost caps | Node/pipeline `max_cost`, `tier`, token saver |
| Token spend discipline | Hub token saver; shorter prompts; `/clear` after tasks |
| Hardware vs cloud | Local combos (`fable`, `private_local`) vs cloud stages |
| Share setups | Export/import `.aether-combo.json` / `.aether-pipeline.json` / graphs |

### What “looks like one model” means in VS Code

Clients (Continue, Cline, Open WebUI custom OpenAI) only see:

- **Base URL:** `http://127.0.0.1:4000/v1`  
- **API key:** your `LITELLM_MASTER_KEY`  
- **Model id:** one alias (e.g. `local-default`, `claude-sonnet-4`, or whatever the active combo resolves to)

They do **not** need to know about multi-agent graphs. Aether Hub and LiteLLM apply your imported trees and limits under that single endpoint.

### Operating loop (recommended)

1. Start stack (`start.bat` / `./start.sh`) — leave it running.  
2. Open the project in VS Code; chat via Continue → Aether gateway.  
3. For structured jobs, run a **pipeline/graph plan** (or rely on default multi-agent mode).  
4. When a unit of work finishes: **`/done`** → **`/compact` or `/clear`** (archives to memory, resets context).  
5. Next message starts clean; search memory if you need old decisions.

Deeper detail: [docs/OPERATING-MODEL.md](./docs/OPERATING-MODEL.md).

---

## What you get

| Service | Port | Role |
|---------|------|------|
| **Open WebUI** | [http://localhost:3000](http://localhost:3000) | Chat UI — same “one window” surface in the browser |
| **LiteLLM** | [http://localhost:4000](http://localhost:4000) | **Single** OpenAI-compatible façade for all models |
| **Aether Hub** | [http://localhost:8766](http://localhost:8766) | Discover, routes, combos, pipelines, **node graph**, memory, slash |
| **Redis** | `6379` | Cache + shared agent memory |
| **Ollama** (host preferred) | `11434` | Local inference on real GPU compute |

```
  VS Code / Continue / browser     ←── you only live here
              │
              │  one base URL + one key + one model id
              ▼
         LiteLLM :4000  ──►  cloud providers (as allowed by policy)
              │
              ├──►  host Ollama (Metal / ROCm CUs / CUDA)
              │
              └──►  Aether Hub :8766
                      ├── decision trees / pipelines / node canvas
                      ├── multi-agent roles (master, critic, workers, testers)
                      ├── token saver & tier limits
                      └── memory + /clear after work is done
```

---

## Quick start (click to run)

### Windows 11

1. Install [Docker Desktop](https://docs.docker.com/desktop/) + (optional) [Ollama](https://ollama.com).  
2. Clone this repo.  
3. **Double-click `start.bat`**  
4. Stop later with **`stop.bat`**

Full walkthrough: [docs/TUTORIAL-WINDOWS.md](./docs/TUTORIAL-WINDOWS.md)

### macOS (OSX)

1. Install [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/) and start it.  
2. (Recommended) Install [Ollama for Mac](https://ollama.com/download) — **Metal** on Apple Silicon.  
3. Clone and start:

```bash
git clone https://github.com/piksliviksi/aetherstack.git
cd aetherstack
chmod +x start.sh stop.sh
./start.sh          # starts Docker; opens browser via `open`
./stop.sh
```

Full walkthrough: [docs/TUTORIAL-MACOS.md](./docs/TUTORIAL-MACOS.md)

### Ubuntu / Linux (native)

```bash
git clone https://github.com/piksliviksi/aetherstack.git
cd aetherstack
chmod +x start.sh stop.sh
./start.sh          # starts Docker services + opens browser
./stop.sh           # stop
```

Full walkthrough: [docs/TUTORIAL-UBUNTU.md](./docs/TUTORIAL-UBUNTU.md)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (Desktop on **Windows/macOS**, Engine on Ubuntu)  
- [Ollama](https://ollama.com) **on the host** (recommended for GPU / Metal)

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
| Hub (matrix + memory) | http://localhost:8766 |

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

**Win11 + AMD:** VS Code does **not** drive the Radeon for LLMs — only Ollama (e.g. WSL ROCm) does.  
**macOS:** VS Code does **not** use Metal for LLMs either — only host Ollama does. See [docs/VSCODE.md](./docs/VSCODE.md).

## Project Data Management Engine

Live **CPU / RAM / disk I/O / GPU**, per-project **disk impact**, **safe cleanup suggestions**, and system footprint (**WSL VHDX**, Docker, Python/torch, Ollama models, …).

```powershell
# Windows
.\project-engine\start-engine.ps1 -Project D:\code\myapp
# → http://127.0.0.1:8765
```

```bash
# macOS / Ubuntu / Linux
./project-engine/start-engine.sh /path/to/project
```

Details: [`project-engine/README.md`](./project-engine/README.md)

---

## Why host Ollama?

| Platform | Recommendation |
|----------|----------------|
| **macOS (Apple Silicon / Intel)** | **Host Ollama** (Metal) — not ROCm/CUDA containers |
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

## Capability matrix & agent memory

| Doc | Topic |
|-----|--------|
| [docs/CAPABILITY-MATRIX.md](./docs/CAPABILITY-MATRIX.md) | Local ↔ cloud routing / sync matrix |
| [docs/AGENT-MEMORY.md](./docs/AGENT-MEMORY.md) | Redis sessions + vector search |
| [docs/AGENT-MODES.md](./docs/AGENT-MODES.md) | Inline vs multi-agent, token saver, multi-LLM roles |
| [docs/AUTO-INSTALL.md](./docs/AUTO-INSTALL.md) | Optional auto-install of missing packages |
| [combos/](./combos/) | Shareable LLM tier + situation packs (export/import) |
| [docs/SLASH-COMMANDS.md](./docs/SLASH-COMMANDS.md) | `/clear` `/compact` — archive to memory then reset context |
| [docs/PIPELINES.md](./docs/PIPELINES.md) | Scriptable multi-stage LLM workflows + voting |
| [docs/NODE-GRAPH.md](./docs/NODE-GRAPH.md) | **Node canvas** (Master/Worker/Analyser, auto-connect) |
| [pipelines/catalog/](./pipelines/catalog/) | Shareable pipeline scripts |
| [`aether-hub/`](./aether-hub/) | Service source |

```bash
# 1) What is available? (always first)
curl -s http://127.0.0.1:8766/api/discover | jq .summary
# Windows deep scan (WSL/GPU/ports):  .\scripts\scan-system.ps1
# Linux/macOS:                        ./scripts/scan-system.sh

# 2) Optional: multi-agent + token saver, pin roles by maker/tier/model
curl -s -X POST http://127.0.0.1:8766/api/modes -H "Content-Type: application/json" \
  -d "{\"mode\":\"multi_agent\",\"token_saver\":true,\"role_overrides\":{\"mastermind\":{\"maker\":\"xai\"},\"worker\":{\"tier\":\"local\",\"strategy\":\"cheapest\"}}}"

# 3) Best model for coding, prefer local
curl -s "http://127.0.0.1:8766/api/route?need=code&prefer=local"

# 3) Shared memory search
curl -s -X POST http://127.0.0.1:8766/api/memory/search \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"gateway port\",\"namespace\":\"default\",\"top_k\":3}"
```

Optional embed model for better recall: `ollama pull nomic-embed-text`

### Optional auto-install (missing packages)

```powershell
# Dry-run: show what would be installed
.\scripts\auto-install.ps1

# Enable + install safe gaps (pip, ollama models, compose services)
.\scripts\auto-install.ps1 -Enable -Yes

# Also fix WSL ROCm Ollama / portproxy (elevated host steps)
.\scripts\auto-install.ps1 -Yes -IncludeElevated

# Or with start:
.\start.ps1 -AutoInstall
```

```bash
./scripts/auto-install.sh            # dry-run
./scripts/auto-install.sh --enable --yes
```

Off by default — see [docs/AUTO-INSTALL.md](./docs/AUTO-INSTALL.md).

### LLM combos (tiers + situations, export/import)

Presets: **Fable Low**, **Sonnet**, **Opus**, **GPT-4.1** (flagship track), **Grok**, plus packs for **coding / research / testing / review**.

```bash
# List tiers + situations
curl -s http://127.0.0.1:8766/api/combos | jq '.situations|keys'

# Launch "coding" multi-LLM combo
curl -s -X POST http://127.0.0.1:8766/api/combos/coding/launch

# Export to file (email / GitHub)
curl -s http://127.0.0.1:8766/api/combos/research/export -o research.aether-combo.json

# Import somewhere else
curl -s -X POST http://127.0.0.1:8766/api/combos/import \
  -H "Content-Type: application/json" -d @research.aether-combo.json
```

Ready-made JSON: [combos/export/](./combos/export/) · guide: [combos/README.md](./combos/README.md)

### Slash commands (context hygiene)

Like Claude’s `/clear`: **finish tasks → document in memory → clear working context**.

```bash
curl -s -X POST http://127.0.0.1:8766/api/slash -H "Content-Type: application/json" \
  -d '{"session_id":"proj","text":"/done all"}'
curl -s -X POST http://127.0.0.1:8766/api/slash -H "Content-Type: application/json" \
  -d '{"session_id":"proj","text":"/clear"}'
```

See [docs/SLASH-COMMANDS.md](./docs/SLASH-COMMANDS.md).

### Pipeline scripts (research → critique → build → test)

```bash
# List + community-style local ranking
curl -s http://127.0.0.1:8766/api/pipelines | jq '.ranking'

# Plan which models run each stage
curl -s -X POST http://127.0.0.1:8766/api/pipelines/research-code-test/plan \
  -H "Content-Type: application/json" -d '{"goal":"Add OAuth"}'

# Export / import / vote
curl -s http://127.0.0.1:8766/api/pipelines/fable-local-loop/export -o my.aether-pipeline.json
curl -s -X POST http://127.0.0.1:8766/api/pipelines/import -d @my.aether-pipeline.json
curl -s -X POST http://127.0.0.1:8766/api/pipelines/research-code-test/vote \
  -d '{"up":true,"hw_flag":"medium"}' -H "Content-Type: application/json"
```

Details: [docs/PIPELINES.md](./docs/PIPELINES.md).

### Node canvas (visual FX style)

```text
http://127.0.0.1:8766/graph
```

Drag **Master / Worker / Analyser / Tester** nodes, set tier/maker/model, draw wires — or **Auto-connect** / **Best-practice template**. Export to pipeline JSON for share/vote.

ActionForge was evaluated but **not bundled** (non-MIT EULA). See [docs/NODE-GRAPH.md](./docs/NODE-GRAPH.md).

### Mac ARM GPU

**Supported** via **host Ollama + Apple Metal** (not ROCm/CUDA). Use combos `inline_fable` / `private_local`. Details: [docs/TUTORIAL-MACOS.md](./docs/TUTORIAL-MACOS.md).

### AMD compute engines (Radeon CUs)

`rocminfo` seeing the card is not enough — Ollama must load the **ROCm** package so HIP runs on the GPU’s **compute units** (e.g. 32 CUs on RX 6600 XT). On WSL, stock install often skips ROCm (no `lspci` amdgpu).

Aether ships a **userspace AMD adapter** (not a kernel driver): device profiles, dids, probe, ensure-backend.

```powershell
# Preferred: adapter applies profile + ROCm Ollama
wsl -d Debian -- bash -lc "sudo bash /mnt/d/llm/stack/aether-amd/ensure-backend.sh"
wsl -d Debian -- bash -lc "python3 /mnt/d/llm/stack/aether-amd/probe.py"
```

Guide: [docs/AMD-COMPUTE.md](./docs/AMD-COMPUTE.md) · Adapter: [`aether-amd/`](./aether-amd/) · WSL: [docs/WSL-AMD-GPU.md](./docs/WSL-AMD-GPU.md)

## Related

- Debian WSL workstation notes: [docs/WSL-AMD-GPU.md](./docs/WSL-AMD-GPU.md)

---

## License

MIT — see [LICENSE](./LICENSE).

## Credits

Built on [Ollama](https://ollama.com), [Open WebUI](https://github.com/open-webui/open-webui), [LiteLLM](https://github.com/BerriAI/litellm), and Redis.  
Not affiliated with those projects.
