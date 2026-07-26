# VS Code architecture

Day-to-day extension use: [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md).

## Role

Open a project folder. Scan stored AI history. Wire OpenAI-compatible clients to the Aether gateway. Continue work through LiteLLM + Hub policy.

## GPU boundary

VS Code does not run local LLM weights on GPU. This holds on Windows, macOS, and Linux.

| Layer | Process | Local GPU for LLMs |
|-------|---------|-------------------|
| VS Code UI | Desktop | No |
| Continue / Cline / similar | Extension host | No |
| LiteLLM `:4000` | Docker | Gateway only |
| Inference | Host Ollama (Metal / ROCm / CUDA / WSL) | Yes |

```text
VS Code  ──HTTP──►  LiteLLM :4000  ──HTTP──►  Ollama (host or WSL)
```

### Windows + Radeon procedure

1. Run inference in WSL Ollama (ROCm/DXG) or supported native Ollama — [WSL-AMD-GPU.md](./WSL-AMD-GPU.md).  
2. Start stack (`start.bat`).  
3. Point clients at `http://127.0.0.1:4000/v1` (or WebUI `:3000`).

---

## Install

| Path | Command |
|------|---------|
| Marketplace | `code --install-extension AetherStack.aetherstack` |
| Local VSIX | `code --install-extension packages/aetherstack-0.1.2.vsix` |
| Dev folder | `code --install-extension path/to/integrations/vscode` |

Listing: https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack

## Procedure

1. Start stack: `start.bat` or `./start.sh`.  
2. Install extension.  
3. **File → Open Folder** on the project.  
4. Command Palette:  
   - `AetherStack: Scan Project AI History`  
   - `AetherStack: Wire Continue.dev to AetherStack`  
5. Install Continue (or equivalent) for in-editor chat.  
6. Select gateway model alias (`local-default`, `grok-4.5`, …).

---

## Files written

| Path | Purpose |
|------|---------|
| `.aetherstack/project-overview.md` | Human scan report |
| `.aetherstack/project-overview.json` | Machine scan report |
| `.aetherstack/snapshots/*.md` | Manual session notes |
| `.continue/config.yaml` | Continue → gateway |
| `.vscode/settings.json` | Workspace URLs/model (no secret key) |
| `.vscode/extensions.json` | Extension recommendations |

---

## CLI scan

```powershell
powershell -File scripts/scan-project-ai.ps1 -Path C:\path\to\project
```

```bash
./scripts/scan-project-ai.sh /path/to/project
```

---

## Continue config

```yaml
name: AetherStack
version: 1.0.0
schema: v1
models:
  - name: Aether local
    provider: openai
    model: local-default
    apiBase: http://127.0.0.1:4000/v1
    apiKey: ${env:AETHERSTACK_API_KEY}
    roles: [chat, edit, apply]
```

## Other OpenAI-compatible clients

| Field | Value |
|-------|-------|
| Base URL | `http://127.0.0.1:4000/v1` |
| API key | `LITELLM_MASTER_KEY` |
| Model | Alias from `litellm_config.yaml` |

---

## Limits

| Limit | Fact |
|-------|------|
| Copilot / Cursor private history | Not fully readable without their export |
| Preferred sources | Project-local: Continue, Claude Code, Aider, WayLog, AetherStack |
| Gateway | Stack must be running for model list and chat |
