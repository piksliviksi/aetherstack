# VS Code extension

**Marketplace:** [AetherStack.aetherstack](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack)

| Related | Doc |
|---------|-----|
| Operating model | [OPERATING-MODEL.md](./OPERATING-MODEL.md) |
| Architecture / GPU boundary | [VSCODE.md](./VSCODE.md) |
| Project Data Engine `:8765` | [PROJECT-ENGINE.md](./PROJECT-ENGINE.md) |
| Security | [SECURITY-NOTES.md](./SECURITY-NOTES.md) |

---

## Scope

| In scope | Out of scope |
|----------|--------------|
| Wire VS Code clients to one OpenAI-compatible gateway | Per-message provider picker UI |
| Project AI history scan and overview | Full multi-agent graph UI (Hub `/graph` + pipelines) |
| Continue → LiteLLM `:4000` config | Loading model weights or driving GPU inside VS Code |

Chat path after wiring:

1. Continue (or equivalent) → one base URL + key + model id  
2. Open WebUI `:3000` — same gateway in browser  
3. Aether Hub `:8766` — pipelines, limits, slash hygiene  

---

## Install

### Marketplace

1. Open VS Code.
2. Extensions (`Ctrl+Shift+X`) → search **AetherStack**.
3. Install **AetherStack** (publisher **AetherStack**).

Or CLI:

```bash
code --install-extension AetherStack.aetherstack
```

### From this repo / VSIX

```bash
code --install-extension AetherStack.aetherstack
# or local VSIX:
code --install-extension packages/aetherstack-0.1.0.vsix
# or unpacked folder (dev):
code --install-extension path/to/aetherstack/integrations/vscode
```

Then: **Developer: Reload Window** (`Ctrl+Shift+P`).

### Avoid duplicate installs

If you once installed a local build, you may have **two** extensions:

- `AetherStack.aetherstack` ← keep this  
- `piksliviksi.aetherstack` ← uninstall/disable  

Duplicates can hide the Activity Bar icon or confuse settings.

---

## First-time setup (5 minutes)

### 1. Start AetherStack on the machine

- **Windows:** double-click `start.bat` in the [AetherStack repo](https://github.com/piksliviksi/aetherstack).  
- **macOS / Ubuntu / Linux:** `./start.sh` (Docker Desktop must be running on Mac).

You want at least:

| Service | URL |
|---------|-----|
| Open WebUI | http://127.0.0.1:3000 |
| LiteLLM gateway | http://127.0.0.1:4000 |

Default lab API key: `sk-aether-local` (from `.env` → `LITELLM_MASTER_KEY`).

### 2. Open a **folder** in VS Code

**File → Open Folder…** on your project.

Most commands need a workspace root. Opening a single file is not enough.

### 3. Find the extension UI

The extension does **not** add a giant chat panel. Look for:

**A. Activity Bar (left strip)**

- Icon titled **AetherStack** (often near the **bottom** of the bar).
- Click it → sidebar **Project AI Overview**.

If missing:

- Right-click the Activity Bar → enable **AetherStack**.
- `Ctrl+Shift+P` → type `AetherStack` → try **View** / scan commands.
- **Developer: Reload Window**.

**B. Command Palette (always works)**

`Ctrl+Shift+P` (macOS: `Cmd+Shift+P`) → type **AetherStack**.

### 4. Run the first commands

1. **AetherStack: Scan Project AI History**  
   - Detects `.continue`, `.claude`, Aider history, `.waylog`, `.aetherstack`, etc.  
   - Writes:
     - `.aetherstack/project-overview.md`
     - `.aetherstack/project-overview.json`
   - Fills the **Project AI Overview** tree.

2. **AetherStack: Wire Continue.dev to AetherStack**  
   - Writes `.continue/config.yaml` pointing at LiteLLM.  
   - API key is **not** written as a real secret; uses `${env:AETHERSTACK_API_KEY}`.

3. (Optional) Install **Continue**, then set the key:

```powershell
# Windows PowerShell (user or session)
$env:AETHERSTACK_API_KEY = "sk-aether-local"
```

```bash
# macOS / Linux (add to ~/.zshrc or ~/.bashrc, then restart VS Code)
export AETHERSTACK_API_KEY=sk-aether-local
```

Or VS Code **User** settings (not workspace — safer for git):

```json
{
  "aetherstack.apiKey": "sk-aether-local"
}
```

4. **AetherStack: List Models (API)** — confirms the gateway answers.  
5. **AetherStack: Open Chat UI** — browser chat at `:3000`.

---

## Command reference

| Command | When to use |
|---------|-------------|
| **Scan Project AI History** | Start of a session; after adding chat tools |
| **Show Project Overview** | Re-open `.aetherstack/project-overview.md` |
| **Wire Continue.dev to AetherStack** | Point Continue at multi-model LiteLLM |
| **Write .vscode Settings for AetherStack** | Commit-safe URLs/model in `.vscode/settings.json`; key goes to **User** settings only |
| **List Models (API)** | Debug 401 / stack down |
| **Open Chat UI (Open WebUI)** | Browser chat |
| **Open Project Data Engine** | Disk/CPU dashboard (`:8765`) with `?project=<workspace>` |
| **Save Chat Snapshot Note** | Manual session note under `.aetherstack/snapshots/` |

Sidebar refresh: open the AetherStack view and use the scan action in the view title (or re-run Scan).

---

## Settings

Open Settings → search **AetherStack**, or edit `settings.json`:

| Setting | Default | Notes |
|---------|---------|--------|
| `aetherstack.baseUrl` | `http://127.0.0.1:4000/v1` | LiteLLM OpenAI-compatible base |
| `aetherstack.apiKey` | `sk-aether-local` | Prefer **User** scope; do not commit |
| `aetherstack.chatUiUrl` | `http://127.0.0.1:3000` | Open WebUI |
| `aetherstack.defaultModel` | `local-default` | Alias from LiteLLM config |

**Write .vscode Settings** stores base URL / chat UI / model in the workspace and **strips** any `aetherstack.apiKey` from workspace `settings.json` so keys are less likely to land in git.

---

## Files written

| Path | Commit | Purpose |
|------|--------|---------|
| `.aetherstack/project-overview.md` | Yes (no secrets) | Human AI history overview |
| `.aetherstack/project-overview.json` | Yes (no API key) | Machine scan |
| `.aetherstack/snapshots/*.md` | Operator choice | Manual notes |
| `.continue/config.yaml` | Yes if key is env placeholder | Continue → gateway |
| `.vscode/settings.json` | Yes if no secrets | URLs / default model |
| `.vscode/extensions.json` | Yes | Extension recommendations |

---

## Procedures

### Scan AI history

1. Open the project folder.  
2. **Scan Project AI History**.  
3. Read `.aetherstack/project-overview.md` or the sidebar tree.  

### Wire gateway chat

1. Stack running (`start.bat` / `./start.sh`).  
2. **Wire Continue.dev**.  
3. Set `AETHERSTACK_API_KEY` or User `aetherstack.apiKey`.  
4. Select model alias in Continue (`local-default`, `grok-4.5`, …).  
5. Or **Open Chat UI** (`:3000`).

### Project engine

1. `.\project-engine\start-engine.ps1` or `./project-engine/start-engine.sh`.  
2. **Open Project Data Engine** or http://127.0.0.1:8765/  
3. Scans limited to allowed roots: cwd, home, repo, `--project`.

---

## Troubleshooting

### Extension installed but nothing visible

1. Reload window.  
2. Open a **folder**, not a single file.  
3. Command Palette → type `AetherStack` — if commands appear, the extension works; use the sidebar enable steps above.  
4. Uninstall duplicate `piksliviksi.aetherstack`.  
5. Remote/WSL: install the extension **on the remote** side if the workspace is remote (`Extensions: Show Local / Remote`).

### List Models → 401

- Stack not running, or wrong key.  
- Set `aetherstack.apiKey` to your `LITELLM_MASTER_KEY` (default lab: `sk-aether-local`).  
- Confirm:  
  `curl http://127.0.0.1:4000/v1/models -H "Authorization: Bearer sk-aether-local"`

### Continue does not see models

- Config path: project `.continue/config.yaml` from **Wire Continue.dev**.  
- Env `AETHERSTACK_API_KEY` must be set for the VS Code process (set user env and **fully restart** VS Code).  
- Or configure Continue’s key field manually for local lab only.

### Expectation: VS Code drives AMD GPU

False. Inference runs in Ollama (host or WSL ROCm). VS Code sends HTTP to LiteLLM. See [VSCODE.md](./VSCODE.md).

### Project Engine page empty / connection refused

Start `project-engine` separately; compose stack alone does not start `:8765`.

---

## Security quick rules

1. Never commit real API keys in `.vscode/settings.json` or `.continue/config.yaml`.  
2. Prefer `AETHERSTACK_API_KEY` in the environment for Continue.  
3. Change `LITELLM_MASTER_KEY` if anything is reachable beyond localhost.  
4. Project Engine path scans are limited to safe roots; optional `AETHERSTACK_ENGINE_TOKEN` for shared machines.

---

## Cheat sheet

```text
Install:     code --install-extension AetherStack.aetherstack
Reload:      Ctrl+Shift+P → Developer: Reload Window
Open folder: File → Open Folder
Find UI:     Activity Bar → AetherStack  OR  Ctrl+Shift+P → AetherStack:
First run:   Scan Project AI History → Wire Continue.dev
Chat:        Continue extension  OR  Open Chat UI (:3000)
Gateway:     http://127.0.0.1:4000/v1
Engine:      http://127.0.0.1:8765
```

---

## Source & packaging

| Item | Location |
|------|----------|
| Extension source | [`integrations/vscode/`](../integrations/vscode/) |
| Marketplace | [AetherStack.aetherstack](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack) |
| Package / publish notes | [`integrations/vscode/README.md`](../integrations/vscode/README.md) |
