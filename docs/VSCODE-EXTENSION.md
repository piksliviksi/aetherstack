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
| Native AetherStack combined chat with capability-matched service teams | Loading model weights or driving GPU inside VS Code |
| Project AI history scan, overview, service control, and active-model state | Replacing specialist third-party coding clients |
| Continue → LiteLLM `:4000` config | Installing privileged host GPU drivers silently |

Chat path after wiring:

1. AetherStack Chat → automatic stage selection or an explicit service preset, then a capability-resolved team in VS Code
2. Continue (or equivalent) → one base URL + key + model id
3. Simple Hub `:8766` → the same presets, setup, and update staging
4. Open WebUI `:3000` → optional separate browser client

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
# Marketplace:
code --install-extension AetherStack.aetherstack
# or the exact VSIX downloaded from the v0.3.12 GitHub Release:
code --install-extension aetherstack-0.3.12.vsix
# or unpacked folder (dev):
code --install-extension path/to/aetherstack/integrations/vscode
```

Then: **Developer: Reload Window** (`Ctrl+Shift+P`).

### Avoid duplicate installs

If you once installed a local build, you may have **two** extensions:

- `AetherStack.aetherstack` ← keep 

Duplicates can hide the Activity Bar icon or confuse settings.

---

## First-time setup

### 1. Start AetherStack from VS Code

1. Install Docker Desktop / Docker Engine. It may be stopped; AetherStack attempts to start it.
2. Open **AetherStack → Control & Services**.
3. Press **Start all services**. If no runtime is present, the extension takes the version-matched archive bundled inside the VSIX, verifies its SHA-256 checksum, validates every archive path, and installs it under VS Code extension storage without another prompt or download. It then runs the platform bootstrap, prefers accelerated host Ollama, or starts the bundled CPU fallback and provisions a tool-capable compact model when no host Ollama is reachable. **Choose Installation Folder** remains available for an existing checkout.
4. The extension waits for all endpoints and reports either `OK` or the concrete HTTP/connection/startup error.

Successful startup shows:

| Service | URL |
|---------|-----|
| Open WebUI | http://127.0.0.1:3000/ — OK |
| LiteLLM gateway | http://127.0.0.1:4000/ — OK |
| Aether Hub | http://127.0.0.1:8766/ — OK |

Docker Compose reads existing provider keys from the AetherStack root `.env`. The extension imports the existing `LITELLM_MASTER_KEY` into VS Code SecretStorage and syncs it to Continue's supported global `~/.continue/.env` as `AETHERSTACK_API_KEY`. Generated project config references `${{ secrets.AETHERSTACK_API_KEY }}`; it does not generate new provider keys or copy secrets into the project.

Open WebUI does not require a second local login. A loopback-only proxy reuses
the existing sole admin account, strips browser-supplied identity headers, and
keeps the authenticated backend off host ports. With multiple existing admins,
set `AETHER_LOCAL_WEBUI_EMAIL` in the same root `.env`.

Open WebUI connects to `http://aether-hub:8766/v1` inside Compose. Its Base
Model list therefore contains only models currently available in AetherStack's
capability matrix, including authenticated Codex, Claude, and Grok host CLIs
when the VS Code extension bridge is active. Direct raw Ollama discovery is
disabled; AetherStack aliases such as `local-default` remain available and
unsupported tool fields are removed for models such as TinyLlama.

### 2. Open a **folder** in VS Code

**File → Open Folder…** on your project.

Most commands need a workspace root. Opening a single file is not enough.

### 3. Find the extension UI

The extension does **not** add a giant chat panel. Look for:

**A. Secondary Side Bar — Chat**

- **View → Appearance → Secondary Side Bar**, then select the **AetherStack** tab.
- This is the persistent AetherStack webview chat. **AetherStack: Open Chat in Editor** opens an independent editor surface with its own restored context.
- In VS Code's built-in Chat, enter `@aetherstack` to use the native Chat participant. Its context and selected preset belong to that Chat thread.

**B. Activity Bar (left strip) — operations**

- Icon titled **AetherStack** (often near the bottom of the bar).
- Click it → **Control & Services**.

If missing:

- Right-click the Activity Bar → enable **AetherStack**.
- `Ctrl+Shift+P` → type `AetherStack` → try **View** / scan commands.
- **Developer: Reload Window**.

**C. Command Palette (always works)**

`Ctrl+Shift+P` (macOS: `Cmd+Shift+P`) → type **AetherStack**.

### 4. Run the first commands

1. **AetherStack: Start All Services**
   - Starts Open WebUI, LiteLLM, Redis, and Aether Hub.
   - Monitors ports `3000`, `4000`, and `8766` continuously.
   - Reads live model availability from Hub `/api/matrix`.
   - If `.continue/config.yaml` does not exist, checks candidate aliases with LiteLLM provider health and wires up to eight models that actually respond. Existing configs are preserved.

2. **AetherStack: Scan Project AI History**
   - Detects `.continue`, `.claude`, Aider history, `.waylog`, `.aetherstack`, etc.  
   - Writes:
     - `.aetherstack/project-overview.md`
     - `.aetherstack/project-overview.json`
   - Fills the **Project AI Overview** tree.

3. **AetherStack: Wire Continue.dev to AetherStack**
   - Writes `.continue/config.yaml` pointing at LiteLLM.  
   - API key is **not** written as a real secret; uses `${{ secrets.AETHERSTACK_API_KEY }}` resolved from Continue's global `.env`.

4. (Optional fallback) If Continue was configured before startup, set the same existing gateway key manually:

```powershell
# Windows PowerShell (user or session)
$env:AETHERSTACK_API_KEY = "sk-aether-local"
```

```bash
# macOS / Linux (add to ~/.zshrc or ~/.bashrc, then restart VS Code)
export AETHERSTACK_API_KEY=sk-aether-local
```

For the AetherStack extension itself, run **AetherStack: Set API Key Securely**.
The value is kept in VS Code SecretStorage rather than settings JSON.

5. **AetherStack: List Models (API)** — confirms the gateway answers.
6. **AetherStack: Open Chat UI** — browser chat at `:3000`.

---

## Command reference

| Command | When to use |
|---------|-------------|
| **Show Chat View** | Focus AetherStack Chat in the Secondary Side Bar |
| **Open Chat in Editor** | Open an independent AetherStack Chat surface in an editor tab |
| **Open Hub UI** | Open the Simple service UI, setup helper, and update staging tool |
| **Open Control Center** | View services, containers, available models, technical errors, and lifecycle controls |
| **Start / Stop / Restart All Services** | Control the complete local Docker Compose backend |
| **Refresh Service State** | Re-run health and Compose state checks |
| **Refresh Authenticated Host CLIs** | Re-probe existing Codex, Claude, and Grok CLI sessions and refresh the Hub matrix; recreate only Hub if its protected bridge configuration is stale |
| **Install Verified Runtime** | Checksum, validate, and install the runtime bundled with the extension version |
| **Show Backend Logs** | Open the last 100 Compose log lines in the AetherStack output channel |
| **Choose Installation Folder** | Set the local AetherStack source/install path |
| **Scan Project AI History** | Start of a session; after adding chat tools |
| **Show Project Overview** | Re-open `.aetherstack/project-overview.md` |
| **Wire Continue.dev to AetherStack** | Point Continue at multi-model LiteLLM |
| **Write .vscode Settings for AetherStack** | Commit-safe URLs/model in `.vscode/settings.json`; never writes a key |
| **Set API Key Securely** | Store the gateway key in VS Code SecretStorage |
| **List Models (API)** | Debug 401 / stack down |
| **Open Chat UI (Open WebUI)** | Optional separate browser chat |
| **Open Project Data Engine** | Disk/CPU dashboard (`:8765`) with `?project=<workspace>` |
| **Save Chat Snapshot Note** | Manual session note under `.aetherstack/snapshots/` |

Sidebar refresh: open the AetherStack view and use the scan action in the view title (or re-run Scan).

---

## Settings

Open Settings → search **AetherStack**, or edit `settings.json`:

| Setting | Default | Notes |
|---------|---------|--------|
| `aetherstack.baseUrl` | `http://127.0.0.1:4000/v1` | LiteLLM OpenAI-compatible base |
| `aetherstack.chatUiUrl` | `http://127.0.0.1:3000` | Open WebUI |
| `aetherstack.defaultModel` | `local-default` | Alias from LiteLLM config |
| `aetherstack.stackPath` | empty / auto-detect | Folder containing the AetherStack Compose installation |
| `aetherstack.autoWireModels` | `true` | Create a missing Continue config from live available matrix models after startup |
| `aetherstack.showActiveModel` | `false` | Show live active model aliases in AetherStack Chat, the tree, and status bar |

### Active-model display

Enable **Show the currently running model** in the Control Center. Hub `/api/inference/status` merges LiteLLM callbacks with Hub-owned host-CLI call state, and Chat shows the active alias beside its rotating activity line. Telemetry contains only call id, model alias, execution source, state, and timestamps. It does not record prompts, responses, headers, users, costs, or API keys.

Chat defaults to **Auto — analyze my request**. Each natural-language message is classified before inference, the selected service is shown immediately, and its smallest useful lead/worker/reviewer team is resolved from currently available models. `/help`, `/presets`, `/auto <goal>`, `/preset <name> <goal>`, and shortcuts such as `/research`, `/plan`, `/code`, `/test`, and `/bugfix` provide explicit control. The transcript survives view restoration, fenced code renders safely, and editable English/Estonian/Ukrainian activity text rotates while inference is running.

Already authenticated Codex, Claude, and Grok host CLIs are discovered by the extension and exposed to the Hub through a Docker-reachable host bridge protected by a random bearer token stored in VS Code SecretStorage. The bridge reuses the CLI login session; it accepts only a fixed CLI alias allowlist and does not reveal the CLI path, copy credentials, create an API key, or enable browser CORS. Probing runs after commands and views are registered. Normal refresh re-probes the live Hub without a restart; only a stale or missing bridge environment causes `aether-hub` alone to be recreated. Continue configuration remains limited to LiteLLM-backed models.

Hub embeds the complete editable advanced canvas below its presets, and `/graph` opens the same selected or active tree full-page. Positions and camera state persist across both views, empty-canvas dragging pans the tree, and an agent node can carry a local Markdown behavior profile. **Advanced setup** contains technical configuration and the activity-word editor; runtime wording edits persist in `.aetherstack/activity_words.json`.

**Write .vscode Settings** stores base URL / chat UI / model in the workspace. It never writes an API key; legacy plaintext settings are migrated to SecretStorage.

---

## Files written

| Path | Commit | Purpose |
|------|--------|---------|
| `.aetherstack/project-overview.md` | Yes (no secrets or absolute host paths) | Human AI history overview |
| `.aetherstack/project-overview.json` | Yes (no API key or absolute host paths) | Machine scan using repository-relative paths |
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
3. The extension imports the existing gateway key from the runtime `.env` into VS Code SecretStorage and Continue's private global `.env`; use **AetherStack: Set API Key Securely** if you need to override it.
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
4. Remote/WSL: install the extension **on the remote** side if the workspace is remote (`Extensions: Show Local / Remote`).

### List Models → 401

- Stack not running, or wrong key.  
- Run **AetherStack: Set API Key Securely** and enter your `LITELLM_MASTER_KEY` (default lab: `sk-aether-local`).
- Confirm:  
  `curl http://127.0.0.1:4000/v1/models -H "Authorization: Bearer sk-aether-local"`

### Continue does not see models

- Config path: project `.continue/config.yaml` from **Wire Continue.dev**.  
- Re-run **Wire Continue.dev** after the stack is healthy. The generated config uses `${{ secrets.AETHERSTACK_API_KEY }}`, resolved from Continue's private global `~/.continue/.env`.
- If you maintain Continue configuration manually, set the same existing gateway key there; do not generate a provider key for AetherStack.

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
Find Chat:   Secondary Side Bar → AetherStack  OR  @aetherstack in VS Code Chat
Find ops:    Activity Bar → AetherStack → Control & Services
First run:   Install Docker → Start All Services (runtime installation is automatic)
Chat:        AetherStack Chat  OR  @aetherstack  OR  optional Open WebUI (:3000)
Gateway:     http://127.0.0.1:4000/v1
Engine:      http://127.0.0.1:8765
```

---

## Source & packaging

| Item | Location |
|------|----------|
| Extension source | [`integrations/vscode/`](../integrations/vscode/) |
| Marketplace | [AetherStack.aetherstack](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack) |
| Release artifacts | GitHub Release `v0.3.12`: verified VSIX, runtime archive, and SHA-256 files |
| Package / publish notes | [`integrations/vscode/README.md`](../integrations/vscode/README.md) |
