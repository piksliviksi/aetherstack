# Changelog

## 0.3.3

- Replace the separate monochrome Activity Bar glyph with the same flat blue/white AetherStack mark used by the packaged extension icon.
- Make AetherStack Chat a persistent sidebar conversation with transcript restoration, safe fenced-code rendering, automatic intent analysis, immediate active-preset feedback, and direct `/preset`, `/research`, `/plan`, `/code`, `/test`, `/bugfix`, `/auto`, and `/help` commands.
- Give final service responses a direct conversational-copilot contract instead of returning orchestration facts as the answer.
- Reuse authenticated Codex, Claude, and Grok host CLI sessions through a Docker-reachable, random-token-protected host bridge; no provider key is copied or generated.
- Persist embedded/full-page graph positions and camera state, add blank-canvas panning and centering, and support per-agent Markdown behavior profiles.
- Keep service teams adaptive and small by default, expanding only for assurance or genuinely parallel work.

## 0.3.2

- Carry the same mark through the Hub, advanced dashboard, node graph, project engine, Docker Desktop extension, VS Code Activity Bar, browser favicons, and GitHub README branding.
- Auto-detect the task stage in AetherStack Chat and activate a catalog-driven Research, Planning, Design, Build, Test, Bug-fix, Security, Polish, or Writing tree whose agents still resolve from the live capability matrix.
- Show a collapsed active-preset node graph below the dynamic agent lineup and keep the full editor behind a separate Advanced setup button.
- Replace the Hub's simplified preset-flow sketch with the complete editable advanced canvas; `/graph` and the embedded canvas now load the selected or active capability-resolved service tree with parallel workers and real model assignments.
- Show live active model aliases in Chat when enabled and rotate editable English, Estonian, and Ukrainian inference activity wording from a local JSON database managed in Advanced Hub.
- Avoid Windows startup crashes from non-UTF-8 console logging.

## 0.3.1

- Replace the Marketplace extension icon with the flat, front-facing white AetherStack mark on a blue background.

## 0.3.0

- Add the native **AetherStack Chat** editor with capability-resolved service presets, multi-agent execution, lean delivery, and token-saver controls.
- Add the Simple Hub UI while retaining the Advanced dashboard and node graph.
- Add Research, Planning, Service design, UI design, Frontend, Backend, Coding, Testing, Bug fixing, White-hat pentesting, Polishing, and Technical writing blueprints without hardwired model/provider IDs.
- Add safe update checking and checksummed archive staging from the Hub; browser code never overwrites the checkout.
- Link the independent lean-delivery policy to Ponytail while retaining validation, security, accessibility, tests, and observability safeguards.

## 0.2.1

- Open the local Chat UI at its root and fail clearly when it is not healthy, instead of opening a stale `/error` route.
- Use a loopback-only trusted session proxy so an existing Open WebUI admin database opens locally without a login screen or data deletion.
- Verify capability-matrix candidates against LiteLLM provider health before wiring Continue; a configured but invalid API key is no longer presented as working.
- Make Restart rebuild and recreate Compose services, serialize lifecycle buttons, apply first-run `.env` keys after startup, and reduce background polling.

## 0.2.0

- Add one-click **Start All Services** with concrete health checks for Open WebUI (`:3000`), LiteLLM (`:4000`), and Aether Hub (`:8766`).
- Add an in-editor Control Center with Start, Stop, Restart, Refresh, Compose details, logs, and explicit per-service errors.
- Monitor service state continuously in the AetherStack sidebar and VS Code status bar.
- Discover working models from the live Hub capability matrix and wire up to eight available chat/code models into a new Continue config.
- Reuse the existing `LITELLM_MASTER_KEY` from the AetherStack root `.env` through VS Code SecretStorage and Continue's global `.env`; no provider keys are generated.
- Add opt-in active-model display backed by privacy-minimal LiteLLM telemetry (model alias and timing only).

## 0.1.2

- Keep the Marketplace README user-facing and free of maintainer publishing procedures.
- Document **macOS / OSX** support (Metal Ollama, `./start.sh`, Apple Silicon)
- Keywords: `macos`, `osx`, `apple-silicon`; gateway error text mentions macOS/Linux

## 0.1.1

- **Security:** do not write API keys into workspace files (Continue config uses `${env:AETHERSTACK_API_KEY}`; `.vscode/settings.json` strips `aetherstack.apiKey`; keys go to User settings only)
- Overview JSON/Markdown omit secrets
- Recommend `AetherStack.aetherstack` (not old publisher id) in workspace `extensions.json`
- Activity bar icon uses monochrome `currentColor` so it shows in the VS Code Activity Bar
- README + package homepage link to the how-to guide: [VSCODE-EXTENSION.md](https://github.com/piksliviksi/aetherstack/blob/main/docs/VSCODE-EXTENSION.md)

## 0.1.0

- Initial release
- Scan project AI history (Continue, Claude, Aider, WayLog, AetherStack notes)
- Write `.aetherstack/project-overview.md`
- Wire Continue.dev to AetherStack LiteLLM gateway
- Write workspace `.vscode` settings
- Open Open WebUI and Project Data Engine
- List models from LiteLLM API
- Save chat snapshot notes
