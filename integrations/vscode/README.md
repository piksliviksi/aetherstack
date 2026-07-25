# AetherStack for VS Code

**One chat window. Many models underneath.**

After AetherStack is set up once (Docker + keys + imported pipelines/graphs + limits), you talk to a **single gateway model** in VS Code (via Continue or similar) — same habit as Grok or Claude. Routing, multi-agent roles, tier/cost limits, and memory hygiene run in the background.

How the system operates (full story):  
**[Operating model](https://github.com/piksliviksi/aetherstack/blob/main/docs/OPERATING-MODEL.md)** · **[README modus operandi](https://github.com/piksliviksi/aetherstack/blob/main/README.md#how-aetherstack-operates-modus-operandi)**

Install from the [Marketplace](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack):

```bash
code --install-extension AetherStack.aetherstack
```

## How to use

Full help guide (install, find the UI, commands, Continue, troubleshooting):

**[How to use the VS Code extension](https://github.com/piksliviksi/aetherstack/blob/main/docs/VSCODE-EXTENSION.md)**

1. Start AetherStack so LiteLLM (`:4000`) is up.  
2. Wire Continue → `http://127.0.0.1:4000/v1` + master key + **one** model alias.  
3. Work in that one chat; optionally open Hub (`:8766`) only to change trees or limits.  
4. Scan project AI history when you want repo context recovery.

Open a project folder, scan prior AI chat artifacts, and continue building through the gateway — not by juggling separate vendor apps.

## Features

| Command | What it does |
|---------|----------------|
| **AetherStack: Scan Project AI History** | Finds `.continue`, `.claude`, Aider history, `.waylog`, `.aetherstack` |
| **AetherStack: Show Project Overview** | Opens `.aetherstack/project-overview.md` |
| **AetherStack: Wire Continue.dev** | Writes `.continue/config.yaml` → LiteLLM (`localhost:4000/v1`) |
| **AetherStack: Write .vscode Settings** | Workspace settings + recommended extensions |
| **AetherStack: List Models** | Live list from AetherStack gateway |
| **AetherStack: Open Chat UI** | Opens Open WebUI |
| **AetherStack: Open Project Data Engine** | Opens metrics dashboard (`:8765`) |
| **AetherStack: Save Chat Snapshot Note** | Saves a markdown snapshot under `.aetherstack/snapshots/` |

Sidebar: **AetherStack → Project AI Overview**.

## Prerequisites

1. Run [AetherStack](https://github.com/piksliviksi/aetherstack) (`start.bat` / `./start.sh`) so LiteLLM (`:4000`) and Open WebUI (`:3000`) are up.
2. Optional: [Continue](https://marketplace.visualstudio.com/items?itemName=Continue.continue) for in-editor chat.
3. Optional: host or WSL Ollama for `local-*` models.

### Local GPU (all platforms)

VS Code does **not** run LLMs on the GPU itself. Point Continue/Cline at `http://127.0.0.1:4000/v1` and run inference in **host Ollama**:

| OS | Local inference |
|----|-----------------|
| **macOS** | Ollama + **Metal** (Apple Silicon / supported Intel) |
| **Windows + AMD** | WSL Ollama (ROCm/DXG) or host Ollama |
| **Linux** | Host Ollama (ROCm / CUDA as available) |

## Settings

| Setting | Default |
|---------|---------|
| `aetherstack.baseUrl` | `http://127.0.0.1:4000/v1` |
| `aetherstack.apiKey` | `sk-aether-local` |
| `aetherstack.chatUiUrl` | `http://127.0.0.1:3000` |
| `aetherstack.defaultModel` | `local-default` |

## License

MIT — see [LICENSE](./LICENSE).
