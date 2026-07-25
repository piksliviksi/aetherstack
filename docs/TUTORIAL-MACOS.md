# AetherStack on macOS (OSX)

Works on **macOS 12+** (Intel or Apple Silicon) with Docker Desktop.

The control plane (Open WebUI, LiteLLM, Redis) runs in Docker. Local models run best via **host Ollama** (Metal acceleration on Apple Silicon / supported Intel Macs).

## Prerequisites

| Tool | Install |
|------|---------|
| **Docker Desktop for Mac** | [docs.docker.com/desktop/setup/install/mac-install](https://docs.docker.com/desktop/setup/install/mac-install/) |
| **Ollama** (recommended) | [ollama.com/download](https://ollama.com/download) → macOS |
| **Git** | Xcode CLT or [git-scm.com](https://git-scm.com) |
| **VS Code** (optional) | [code.visualstudio.com](https://code.visualstudio.com) + [AetherStack extension](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack) |

1. Install Docker Desktop and **start it** (whale icon in the menu bar).  
2. Wait until Docker reports **Running**.  
3. Install Ollama app and pull a model:

```bash
ollama pull llama3.1:8b
```

## Quick start

```bash
git clone https://github.com/piksliviksi/aetherstack.git
cd aetherstack
cp .env.example .env
# Optional: edit .env — OPENAI_API_KEY, XAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, LITELLM_MASTER_KEY

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

## Manual compose (same as Linux)

```bash
docker compose up -d
docker compose ps
docker compose down
```

## Apple Silicon notes

- Prefer **host Ollama** (Metal) over the optional Ollama Docker profile for speed and battery.  
- Docker Desktop runs Linux containers via a VM; that is expected.  
- If LiteLLM cannot reach host Ollama, ensure Ollama is listening and Docker can use `host.docker.internal` (set in `docker-compose.yml`).  
- AMD ROCm overlays (`docker-compose.amd.yml`) **do not apply** on Mac — use Metal Ollama or cloud models via LiteLLM.

## NVIDIA / Intel discrete GPU on Mac

- NVIDIA CUDA and AMD ROCm paths are **Linux/Windows**, not macOS.  
- On Mac, local inference = **Ollama + Metal** (or CPU).  
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
# ~/.zshrc (restart Terminal + VS Code after)
export AETHERSTACK_API_KEY=sk-aether-local
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
| LiteLLM 401 | Use Bearer `LITELLM_MASTER_KEY` (default lab: `sk-aether-local`) |
| Ollama not seen from containers | Run Ollama app; check `http://127.0.0.1:11434`; compose uses `host.docker.internal` |
| `./start.sh: Permission denied` | `chmod +x start.sh stop.sh` |
| Apple Silicon image pull slow | First pull is large; keep Docker running |

## Desktop “click to start” (optional)

Automator → **Application** → **Run Shell Script**:

```bash
cd /Users/YOU/aetherstack && ./start.sh
```

Save as **AetherStack.app** and keep it in Applications or the Dock.
