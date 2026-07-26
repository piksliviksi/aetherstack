# AetherStack for VS Code

**One chat window. Many models underneath.**

After AetherStack is set up once (Docker + keys + imported pipelines/graphs + limits), you talk to a **single gateway model** in VS Code (via Continue or similar) — same habit as Grok or Claude. Routing, multi-agent roles, tier/cost limits, and memory hygiene run in the background.

How the system operates (full story):  
**[What you get](https://github.com/piksliviksi/aetherstack/blob/main/README.md)** · **[Operating model](https://github.com/piksliviksi/aetherstack/blob/main/docs/OPERATING-MODEL.md)** · **[Docs index](https://github.com/piksliviksi/aetherstack/blob/main/docs/README.md)**

Install from the [Marketplace](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack):

```bash
code --install-extension AetherStack.aetherstack
```

## How to use

Full help guide (install, find the UI, commands, Continue, troubleshooting):

**[How to use the VS Code extension](https://github.com/piksliviksi/aetherstack/blob/main/docs/VSCODE-EXTENSION.md)**

1. Open **AetherStack → Control & Services** and press **Start all services**.
2. The extension checks `:3000`, `:4000`, and `:8766`, verifies capability-matrix candidates through LiteLLM provider health, then wires only responding models into a new Continue config.
3. Open **AetherStack Chat** in the sidebar. Leave the service on **Auto** and describe the current stage: research, planning, UI/service design, frontend/backend, coding, testing, bug fixing, security review, polishing, or documentation. The matching tree activates automatically and its lead, workers, and reviewer are assigned from the live capability matrix.
4. Expand **Active preset node graph** beneath the team when you want to inspect the selected flow. Use the separate **Advanced setup** button for manual orchestration and for editing the local multilingual inference-activity wording database. Open WebUI (`:3000`) only when you want that separate client.
5. Scan project AI history when you want repo context recovery.

Open a project folder, scan prior AI chat artifacts, and continue building through the gateway — not by juggling separate vendor apps.

## Features

| Command | What it does |
|---------|----------------|
| **AetherStack: Open Combined Chat** | Opens the native VS Code chat with dynamic task services and lean/token controls |
| **AetherStack: Open Hub UI** | Opens the Simple Hub with service presets, setup, update staging, and links to advanced tools |
| **AetherStack: Open Control Center** | Service state, backend details, models, lifecycle controls, and optional active-model display |
| **AetherStack: Start All Services** | Runs the complete Docker Compose stack and waits for all three HTTP services |
| **AetherStack: Stop / Restart All Services** | Controls the local Compose stack from VS Code |
| **AetherStack: Refresh Service State** | Rechecks every URL and displays a concrete error for failures |
| **AetherStack: Scan Project AI History** | Finds `.continue`, `.claude`, Aider history, `.waylog`, `.aetherstack` |
| **AetherStack: Show Project Overview** | Opens `.aetherstack/project-overview.md` |
| **AetherStack: Wire Continue.dev** | Writes `.continue/config.yaml` → LiteLLM (`localhost:4000/v1`) |
| **AetherStack: Write .vscode Settings** | Workspace settings + recommended extensions |
| **AetherStack: List Models** | Live list from AetherStack gateway |
| **AetherStack: Open Chat UI** | Opens the optional Open WebUI client |
| **AetherStack: Open Project Data Engine** | Opens metrics dashboard (`:8765`) |
| **AetherStack: Save Chat Snapshot Note** | Saves a markdown snapshot under `.aetherstack/snapshots/` |

Sidebar: **AetherStack → Control & Services**.

## Prerequisites

1. Install Docker Desktop / Docker Engine and keep its daemon running. The extension starts the AetherStack services itself.
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
| API key | Command: **AetherStack: Set API Key Securely** (SecretStorage) |
| `aetherstack.chatUiUrl` | `http://127.0.0.1:3000` |
| `aetherstack.defaultModel` | `local-default` |
| `aetherstack.stackPath` | Auto-detected; choose the folder containing `docker-compose.yml` if needed |
| `aetherstack.autoWireModels` | `true` |
| `aetherstack.showActiveModel` | `false` (opt in from the Control Center; shows live model aliases in AetherStack Chat, the sidebar, and status bar) |

Provider API keys are read by Docker Compose from the AetherStack installation root `.env`. The extension reuses its existing `LITELLM_MASTER_KEY` through VS Code SecretStorage and Continue's supported global `~/.continue/.env` secret store; generated model config refers to `${{ secrets.AETHERSTACK_API_KEY }}`. It never displays or regenerates provider keys and intentionally does not scan unrelated project `.env` files.

Open WebUI is signed in automatically through a proxy published only on
`127.0.0.1:3000`; its authenticated backend has no host port. The sole existing
admin is reused, so chats and settings remain intact and no new password is
needed.

## License

MIT — see [LICENSE](./LICENSE).
