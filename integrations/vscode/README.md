# AetherStack for VS Code

Open a project folder, scan for prior AI chat artifacts, see which tools/models were used, and **continue building** through AetherStack’s multi-model gateway.

## Features

| Command | What it does |
|---------|----------------|
| **AetherStack: Scan Project AI History** | Finds `.continue`, `.claude`, Aider history, `.waylog`, `.aetherstack`, … |
| **AetherStack: Show Project Overview** | Opens `.aetherstack/project-overview.md` |
| **AetherStack: Wire Continue.dev** | Writes `.continue/config.yaml` → LiteLLM (`localhost:4000/v1`) |
| **AetherStack: Write .vscode Settings** | Workspace settings + recommended extensions |
| **AetherStack: List Models** | Live list from AetherStack gateway |
| **AetherStack: Open Chat UI** | Opens Open WebUI |
| **AetherStack: Save Chat Snapshot Note** | Appends a markdown snapshot under `.aetherstack/snapshots/` |

Sidebar: **AetherStack → Project AI Overview**.

## Install (local / development)

```bash
# From this repo
code --install-extension integrations/vscode
# or symlink into extensions dir:
# Windows: %USERPROFILE%\.vscode\extensions\piksliviksi.aetherstack-0.1.0
```

Pack as VSIX (optional):

```bash
cd integrations/vscode
npx @vscode/vsce package --allow-missing-repository
code --install-extension aetherstack-0.1.0.vsix
```

## Prerequisites

1. **AetherStack running** (`start.bat` / `./start.sh`) — LiteLLM `:4000`, Open WebUI `:3000`
2. Optional: [Continue](https://marketplace.visualstudio.com/items?itemName=Continue.continue) for in-editor chat/edit
3. Optional: host Ollama for `local-*` models

### Windows 11 + AMD GPU

**VS Code cannot run local LLMs on the Radeon GPU.** Extensions only call an HTTP API.

| Do | Don't |
|----|--------|
| Ollama in **WSL** with ROCm/DXG (or host Ollama if supported) | Expect VS Code / Continue to load ROCm |
| Point models at `http://127.0.0.1:4000/v1` | Look for “AMD GPU” inside VS Code for inference |
| Watch GPU while **Ollama** runs (`rocminfo` / Task Manager) | Blame VS Code if `local-*` is slow — check Ollama |

See [docs/VSCODE.md](../../docs/VSCODE.md) and [docs/WSL-AMD-GPU.md](../../docs/WSL-AMD-GPU.md).

## Settings

| Setting | Default |
|---------|---------|
| `aetherstack.baseUrl` | `http://127.0.0.1:4000/v1` |
| `aetherstack.apiKey` | `sk-aether-local` |
| `aetherstack.chatUiUrl` | `http://127.0.0.1:3000` |
| `aetherstack.defaultModel` | `local-default` |

## What history can we see?

| Source | Detected |
|--------|----------|
| Continue.dev (`.continue/`) | Yes |
| Claude Code (`.claude/`) | Yes |
| Aider (`aider.chat.history.md`) | Yes |
| WayLog (`.waylog/`) | Yes |
| AetherStack notes (`.aetherstack/`) | Yes |
| Cursor / Copilot internal DBs | **Not fully** (opaque SQLite); use export or WayLog |

We **do not** scrape proprietary DBs by default. Export chats into the project (or use WayLog) for best continuity.

## Flow

```
Open folder in VS Code
        │
        ▼
 Scan Project AI History ──► .aetherstack/project-overview.md
        │
        ▼
 Wire Continue.dev ──► all models via AetherStack LiteLLM
        │
        ▼
 Keep coding / chat with Grok, GPT, Claude, local, …
```

See also: [docs/VSCODE.md](../../docs/VSCODE.md)
