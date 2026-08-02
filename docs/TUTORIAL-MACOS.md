# AetherStack on macOS (OSX)

Works on **macOS Sonoma 14+** (Intel or Apple Silicon) with Docker Desktop. AetherStack reuses a healthy host Ollama; when none is installed, Start can download the official signed macOS app into the current user's AetherStack tools directory and launch its CLI automatically.

The control plane (Open WebUI, LiteLLM, Redis, Postgres, Hub) runs in Docker. Local models run best via **host Ollama**: Metal acceleration on Apple M-series systems and CPU inference on Intel Macs.

See Ollama's current [macOS requirements](https://docs.ollama.com/macos) and [GPU support](https://docs.ollama.com/gpu).

## Prerequisites

| Tool | Install |
|------|---------|
| **Docker Desktop for Mac** | [docs.docker.com/desktop/setup/install/mac-install](https://docs.docker.com/desktop/setup/install/mac-install/) |
| **Ollama** (local GPU) | Optional manual install; otherwise AetherStack installs the signed user-space app on first Start |
| **Git** | Xcode CLT or [git-scm.com](https://git-scm.com) |
| **VS Code** | [code.visualstudio.com](https://code.visualstudio.com) + [AetherStack extension](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack) |

1. Install Docker Desktop and **start it** (whale icon in the menu bar).  
2. Wait until Docker reports **Running**.  
3. Optional: install Ollama yourself and pull a model. If omitted, AetherStack Start provisions the compact coding and embedding models with visible progress:

```bash
ollama pull llama3.1:8b
```

## Quick start

```bash
git clone https://github.com/piksliviksi/aetherstack.git
cd aetherstack
cp .env.example .env
# Edit .env — LITELLM_MASTER_KEY and provider keys in use

chmod +x start.sh stop.sh
./start.sh
```

Then open:

| Service | URL |
|---------|-----|
| Chat (Open WebUI) | http://localhost:3000 |
| Gateway (LiteLLM) | http://localhost:4000 |

Stop:

```bash
./stop.sh
```

`start.sh` detects macOS and opens the browser with `open` when available.

When host Ollama is missing, `start.sh` downloads
`https://ollama.com/download/Ollama-darwin.zip`, verifies the macOS code
signature, installs it under
`~/Library/Application Support/AetherStack/tools/Ollama.app`, and runs its CLI.
Set `AETHER_AUTO_INSTALL_OLLAMA=0` to opt out and use the Docker CPU fallback.
`stop.sh` stops that host process only when AetherStack started it; an Ollama
service that was already running remains user-owned and untouched.

## Manual compose (same as Linux)

```bash
docker compose up -d
docker compose ps
docker compose down
```

## Apple Silicon (ARM64) + Metal GPU

Local GPU on Mac ARM uses **Apple Metal** (not CUDA/ROCm).

| Layer | Local GPU for LLMs |
|-------|--------------------|
| Host Ollama (Apple Silicon) | Yes — Metal (`ollama ps` after a run) |
| Docker (LiteLLM, WebUI, Hub) | No — control plane only |
| VS Code extension | No — HTTP client only |
| ROCm / CUDA compose overlays | Not applicable on Mac |

### Procedure

```bash
# 1) Ollama for macOS (Apple Silicon build from ollama.com)
ollama pull llama3.1:8b   # or tinyllama for low RAM
# Run a prompt; then:
ollama ps                 # expect GPU / metal, not 100% CPU

# 2) Aether control plane
./start.sh

# 3) Use local combo
curl -s -X POST http://127.0.0.1:8766/api/combos/inline_fable/launch
# or private multi-agent:
curl -s -X POST http://127.0.0.1:8766/api/combos/private_local/launch
```

### Reproducible packaged-extension proof

On a dedicated physical Apple Silicon test Mac with Docker Desktop running and
VS Code installed, the repository gate installs the exact VSIX into an isolated
profile, presses Start through the extension command, provisions an empty
Ollama model store, restarts, performs real inference, requires nonzero
GPU-resident model memory, and stops the stack:

```bash
npm --prefix integrations/vscode run release:check
node scripts/verify-one-click.mjs \
  --restart \
  --require-accelerator \
  --evidence dist/macos-metal-evidence.json
```

The same contract is available as the manually dispatched
`Native macOS Metal one-click evidence` workflow. It intentionally targets a
dedicated self-hosted Apple Silicon runner: GitHub-hosted macOS machines cannot
run the Docker control plane because nested virtualization is unavailable.

### Tips

- Prefer **host Ollama + Metal** over `with-ollama-container` (Linux VM, usually no Metal).  
- Docker Desktop uses a Linux VM; that is expected for UI/gateway only.  
- LiteLLM reaches Ollama at `host.docker.internal:11434` (set in compose).  
- Unified memory: larger models (70B) need enough unified RAM; start with 7–8B or smaller.  
- Combos `fable_low`, `inline_fable`, `private_local` are tuned for Metal/local.

## NVIDIA / Intel discrete GPU on Mac

- NVIDIA CUDA and AMD ROCm paths are **Linux/Windows**, not macOS.  
- On Mac, local inference = **Ollama + Metal** (Apple Silicon) or **CPU** (Intel without usable GPU path).  
- Cloud models (Grok, OpenAI, Claude, Gemini) work the same as on other OSes once keys are in `.env`.

## VS Code on macOS

```bash
code --install-extension AetherStack.aetherstack
```

1. **File → Open Folder…** on your project.  
2. Command Palette (`Cmd+Shift+P`) → **AetherStack: Scan Project AI History**.  
3. **AetherStack: Wire Continue.dev to AetherStack**.  
4. Set env for Continue:

```bash
# ~/.zshrc (restart Terminal + VS Code after); use LITELLM_MASTER_KEY from .env
export AETHERSTACK_API_KEY='<generated-key>'
```

Full guide: [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md)

## Project Data Engine

```bash
chmod +x project-engine/start-engine.sh
./project-engine/start-engine.sh /path/to/your/project
# → http://127.0.0.1:8765
```

Uses Python 3 on the Mac; install `psutil` if prompted (`pip3 install --user psutil`).

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Cannot connect to Docker` | Start Docker Desktop; wait until engine is ready |
| Port 3000/4000 in use | Stop other apps or change ports in `docker-compose.yml` |
| LiteLLM 401 | Use the generated `LITELLM_MASTER_KEY` from `.env` as the Bearer token |
| Ollama not seen from containers | Run Ollama app; check `http://127.0.0.1:11434`; compose uses `host.docker.internal` |
| `./start.sh: Permission denied` | `chmod +x start.sh stop.sh` |
| Apple Silicon image pull slow | First pull is large; keep Docker running |

## Desktop “click to start” (optional)

Automator → **Application** → **Run Shell Script**:

```bash
cd /Users/YOU/aetherstack && ./start.sh
```

Save as **AetherStack.app** and keep it in Applications or the Dock.
