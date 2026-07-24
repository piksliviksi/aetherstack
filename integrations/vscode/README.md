# AetherStack for VS Code

**Marketplace:** [AetherStack.aetherstack](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack)

```bash
code --install-extension AetherStack.aetherstack
```

Open a project folder, scan prior AI chat artifacts, see which tools/models were used, and continue building through [AetherStack](https://github.com/piksliviksi/aetherstack) (LiteLLM multi-model gateway + Open WebUI + Ollama).

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

### Windows 11 + AMD GPU

VS Code does **not** run LLMs on the Radeon. Point Continue/Cline at `http://127.0.0.1:4000/v1` and run inference in **WSL Ollama** (ROCm/DXG) or host Ollama.

## Settings

| Setting | Default |
|---------|---------|
| `aetherstack.baseUrl` | `http://127.0.0.1:4000/v1` |
| `aetherstack.apiKey` | `sk-aether-local` |
| `aetherstack.chatUiUrl` | `http://127.0.0.1:3000` |
| `aetherstack.defaultModel` | `local-default` |

## Install from VSIX

```bash
code --install-extension aetherstack-0.1.0.vsix
```

Or in VS Code: Extensions view → `...` → **Install from VSIX...**

## Package this extension

```bash
cd integrations/vscode
npm install -g @vscode/vsce
vsce package
```

## Marketplace publish (optional)

1. Create a publisher at [marketplace.visualstudio.com/manage](https://marketplace.visualstudio.com/manage)
2. Create an Azure DevOps PAT with **Marketplace → Manage**
3. `vsce login AetherStack`
4. `vsce publish`

See [Publishing Extensions](https://code.visualstudio.com/api/working-with-extensions/publishing-extension).

## License

MIT — see [LICENSE](./LICENSE).
