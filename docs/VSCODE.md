# AetherStack + VS Code projects

## Goal

Open a **project folder** in VS Code, recover context from **previous AI chats** (when stored in the repo or known folders), see **which models/tools were used**, and **continue** via AetherStack (multi-model LiteLLM + Open WebUI + optional Ollama).

## Quick start

1. Start AetherStack: `start.bat` (Windows) or `./start.sh` (Ubuntu).
2. Install the extension from this repo:

```bash
code --install-extension path/to/aetherstack/integrations/vscode
```

Or copy `integrations/vscode` to your VS Code extensions directory as `piksliviksi.aetherstack-0.1.0`.

3. **File → Open Folder** on your project.
4. Command Palette:
   - `AetherStack: Scan Project AI History`
   - `AetherStack: Wire Continue.dev to AetherStack`
5. Install [Continue](https://marketplace.visualstudio.com/items?itemName=Continue.continue) if you want in-editor chat.
6. Chat with models: `local-default`, `grok-4.5`, `gpt-4.1`, `claude-sonnet-4`, …

## Project files written

| Path | Purpose |
|------|---------|
| `.aetherstack/project-overview.md` | Human-readable history + how to continue |
| `.aetherstack/project-overview.json` | Machine-readable scan |
| `.aetherstack/snapshots/*.md` | Manual session notes |
| `.continue/config.yaml` | Continue → AetherStack gateway |
| `.vscode/settings.json` | Workspace AetherStack settings |
| `.vscode/extensions.json` | Recommends Continue + AetherStack |

## CLI scan (no extension)

```powershell
# Windows
powershell -File scripts/scan-project-ai.ps1 -Path C:\path\to\project
```

```bash
# Linux
./scripts/scan-project-ai.sh /path/to/project
```

## Continue.dev (manual)

`~/.continue/config.yaml` or project `.continue/config.yaml`:

```yaml
name: AetherStack
version: 1.0.0
schema: v1
models:
  - name: Aether local
    provider: openai
    model: local-default
    apiBase: http://127.0.0.1:4000/v1
    apiKey: sk-aether-local
    roles: [chat, edit, apply]
```

## Cline / other OpenAI-compatible agents

- Base URL: `http://127.0.0.1:4000/v1`
- API key: `sk-aether-local` (or your `LITELLM_MASTER_KEY`)
- Model: any alias from `litellm_config.yaml`

## Limits

- Copilot/Cursor **internal** history is not fully readable without their export tools.
- Prefer project-local folders (Continue, Claude Code, Aider, WayLog, AetherStack snapshots).
- Always start AetherStack before expecting the gateway/models list to work.
