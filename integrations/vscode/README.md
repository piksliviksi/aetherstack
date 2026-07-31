# AetherStack for VS Code

**One chat window. Many models underneath.**

After AetherStack is set up once, you use its permanent **Chat** view in VS Code like a normal coding assistant. AetherStack analyzes each request, activates the matching service preset, and resolves the smallest useful team from models and authenticated host CLIs available on this system. Continue and Open WebUI remain optional clients.

How the system operates (full story):  
**[What you get](https://github.com/piksliviksi/aetherstack/blob/main/README.md)** · **[Operating model](https://github.com/piksliviksi/aetherstack/blob/main/docs/OPERATING-MODEL.md)** · **[Docs index](https://github.com/piksliviksi/aetherstack/blob/main/docs/README.md)**

Install from the [Marketplace](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack):

```bash
code --install-extension AetherStack.aetherstack
```

## How to use

Full help guide (install, find the UI, commands, Continue, troubleshooting):

**[How to use the VS Code extension](https://github.com/piksliviksi/aetherstack/blob/main/docs/VSCODE-EXTENSION.md)**

1. Install Docker Desktop / Docker Engine, open AetherStack **Control & Services**, and press **Start all services**. The extension installs the checksum-verified runtime bundled in the VSIX automatically, starts the platform bootstrap, prefers an existing accelerated host Ollama, and falls back to its container runtime when Ollama is absent. On macOS it can download the official signed Ollama app into the user's AetherStack tools directory and launch its host CLI so Apple Silicon inference stays on Metal.
2. The extension checks `:3000`, `:4000`, and `:8766`, verifies capability-matrix candidates through LiteLLM provider health, then wires only responding models into a new Continue config.
3. Open **AetherStack → Chat** from the Secondary Side Bar, open it in an editor, or use `@aetherstack` in VS Code's built-in Chat. Leave routing on **Auto** and ask naturally; intent analysis activates Research, Planning, Design, Build, Test, Bug-fix, Security, Polish, or Writing. Use `/help`, `/presets`, `/research`, `/plan`, `/code`, `/test`, `/bugfix`, or `/preset <name>` when you want explicit control.
4. In Hub, expand the complete **Advanced active-preset node graph** below the presets to edit the selected capability-resolved tree, or open `/graph` full-page. Use the separate **Advanced setup** button for technical configuration and the local multilingual inference-activity wording database. Open WebUI (`:3000`) only when you want that separate client.
5. Scan project AI history when you want repo context recovery.

Open a project folder, scan prior AI chat artifacts, and continue building through the gateway — not by juggling separate vendor apps.

## Features

| Command | What it does |
|---------|----------------|
| **AetherStack: Show Chat View** | Focuses persistent Chat in the Secondary Side Bar |
| **AetherStack: Open Chat in Editor** | Opens an independent restored Chat surface in an editor tab |
| **AetherStack: Open Hub UI** | Opens the Simple Hub with service presets, setup, update staging, and links to advanced tools |
| **AetherStack: Open Control Center** | Service state, backend details, models, lifecycle controls, and optional active-model display |
| **AetherStack: Start All Services** | Runs the complete Docker Compose stack and waits for all three HTTP services |
| **AetherStack: Stop / Restart All Services** | Controls the local Compose stack from VS Code |
| **AetherStack: Refresh Service State** | Rechecks every URL and displays a concrete error for failures |
| **AetherStack: Refresh Authenticated Host CLIs** | Re-probes existing Codex/Claude/Grok logins and refreshes Hub without a restart when possible |
| **AetherStack: Install Verified Runtime** | Reinstalls the checksum-verified runtime bundled with this extension version under VS Code extension storage |
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

1. Install Docker Desktop / Docker Engine and keep its daemon running. The extension starts the AetherStack services itself. Docker installation is intentionally not automated because it has a separate vendor license and may require administrator approval; “one click” begins after this OS prerequisite is accepted.
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
| `aetherstack.showActiveModel` | `true` (live answering model in Chat and status bar) |
| `aetherstack.showThoughtProcess` | `false` (show lead/worker/review notes under answers) |
| `aetherstack.showTokens` | `true` (token count after each reply) |
| `aetherstack.memoryContextKb` | `512` (Auto unified memory budget: 256 / 512 / 1024 / 2048 KiB) |

Provider API keys are read by Docker Compose from the selected AetherStack runtime root `.env`. The extension also detects already authenticated Codex, Claude, and Grok host CLIs through a Docker-reachable bridge protected by a random bearer token stored in VS Code SecretStorage, so their existing login sessions work in AetherStack Chat without copying or generating provider keys. Views and commands register before CLI probes run. Refresh normally updates Hub in place; only stale bridge environment requires recreating `aether-hub`. The bridge exposes only its fixed CLI allowlist and does not enable browser CORS. Continue receives only models exposed through LiteLLM. The extension intentionally does not scan unrelated project `.env` files.

Open WebUI is signed in automatically through a proxy published only on
`127.0.0.1:3000`; its authenticated backend has no host port. The sole existing
admin is reused, so chats and settings remain intact and no new password is
needed.

## License

Source-available under the [PolyForm Noncommercial License 1.0.0](./LICENSE).
Commercial use, including resale, is not permitted. Redistributions must retain
the license and the required notice crediting the original author.
