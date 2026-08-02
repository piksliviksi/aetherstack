# VS Code architecture

Day-to-day extension use: [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md).

## Runtime and UI boundaries

The Marketplace VSIX is the control client and carries its matching checksum-verified runtime bundle. Release `0.3.20` installs that runtime automatically into VS Code extension storage when **Start all services** is pressed, or it can operate an existing AetherStack checkout. Docker must be installed; AetherStack starts Docker Desktop when it is installed but stopped.

| Surface | Location | Responsibility |
|---|---|---|
| AetherStack Chat webview | VS Code Secondary Side Bar; optional editor tab | Compact action/slash menu, persistent conversations, automatic/service routing, streamed responses, optional active-model label |
| `@aetherstack` Chat participant | VS Code built-in Chat | Native thread context and slash-command preset routing |
| Control & Services | VS Code Activity Bar | Install/start/stop/restart, health, containers, models, logs, CLI refresh |
| Hub UI | `http://127.0.0.1:8766/` | Simple presets and the active graph; advanced configuration |
| Open WebUI | `http://127.0.0.1:3000/` | Optional local browser chat |
| LiteLLM | `http://127.0.0.1:4000/v1` | OpenAI-compatible gateway for API-backed/local models |

Each AetherStack webview surface and native Chat thread owns its own bounded context. A visible restored transcript is rehydrated as inference context; it is not shared with another surface.

## Inference boundary

VS Code does not load model weights or perform GPU inference.

```text
                                      ┌─► provider APIs
VS Code ─► Aether Hub :8766 ─► LiteLLM :4000 ─► host Ollama / GPU
                  │
                  └─► protected host CLI bridge :8767 ─► authenticated Codex/Claude/Grok CLI
```

The host CLI bridge uses already authenticated CLI sessions. Its random bearer token is stored in VS Code SecretStorage and supplied to Hub through Compose; credentials are not copied and provider API keys are not generated. A refresh re-probes CLI login/install changes in place. Hub recreation is a fallback only when the bridge environment is stale.

Optional active-model telemetry merges LiteLLM and host-CLI calls. It records model alias, source, call id, state, and timestamps only—never prompts, responses, headers, users, costs, or keys.

## Install and start

| Path | Command |
|---|---|
| Marketplace | `code --install-extension AetherStack.aetherstack` |
| GitHub Release VSIX | `code --install-extension aetherstack-0.3.20.vsix` |
| Development folder | `code --install-extension path/to/integrations/vscode` |

1. Install and start Docker Desktop or Docker Engine.
2. Install the extension and reload VS Code.
3. Open **AetherStack → Control & Services** in the Activity Bar.
4. Press **Start all services**. The bundled Runtime 0.3.20 is installed automatically on first use and the platform bootstrap starts every service. The AetherStack Output panel opens automatically and shows image/model download and health progress; slow healthy cold installs have a 60-minute window.
5. Wait for explicit `OK` state at ports `3000`, `4000`, and `8766`.
6. Open Chat from the Secondary Side Bar, an editor tab, or `@aetherstack` in VS Code Chat.

## Continue configuration

**AetherStack: Wire Continue.dev to AetherStack** writes only live LiteLLM-exposed models. It preserves an existing config unless the user explicitly chooses replacement and uses Continue's secret placeholder:

```yaml
name: AetherStack
version: 1.0.0
schema: v1
models:
  - name: AetherStack local-default
    provider: openai
    model: local-default
    apiBase: http://127.0.0.1:4000/v1
    apiKey: ${{ secrets.AETHERSTACK_API_KEY }}
    roles: [chat, edit, apply]
```

The existing `LITELLM_MASTER_KEY` is imported from the runtime `.env` into VS Code SecretStorage and synchronized to Continue's private global `.env`. Project files do not contain the key.

## Project overview privacy

Project scans write `.aetherstack/project-overview.md` and `.json`. Version `0.3.20` persists `workspace: "."` and repository-relative source paths, not absolute paths or usernames. It does not read provider keys from arbitrary project `.env` files.

## Release boundary

The `v0.3.20` workflow tests source, packages a VSIX and runtime archive, inspects identity/content/source-byte parity/privacy, publishes the exact VSIX to Marketplace, and attaches that same VSIX plus the runtime archive and SHA-256 manifests to the GitHub Release. Without a repository PAT, a matching version must first be published directly with short-lived Microsoft Entra authentication; otherwise the workflow stops. Any failed artifact check prevents publication.

## Limits

| Limit | Fact |
|---|---|
| Docker | Required; the extension does not install Docker or privileged GPU drivers |
| Copilot/Cursor private history | Not fully readable without an export |
| Optional Ollama profile | Not started by the default Compose profile; host Ollama is preferred |
| Project Data Engine `:8765` | Separate process, not one of the three Compose health endpoints |
