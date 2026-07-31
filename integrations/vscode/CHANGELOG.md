# Changelog

## 0.3.15

- Add three-tier **Memory** nodes on the Hub graph canvas (`tree` / `project` / `global`) with search/store actions and resolved namespaces.
- Support multi-wire fan-in/fan-out edges, recursive feedback mode, and pipeline export of `memory_ops` plus stage `inputs_from` / `outputs_to`.
- Add **Private** local-GPU node (folder of PDF/text, vault isolation) and light node progress bars; pass-through nodes use a blinking activity dot.
- Stream Hub service stage status (planning, lead, workers, review, answering) so VS Code Chat shows live phase + model + elapsed time while a reply is running.
- Short English-only inference activity phrases; always surface the answering model during a run.
- Chat `/` menu toggles: **Show answering model**, **Show thought process**, **Show tokens** (settings `aetherstack.showActiveModel`, `showThoughtProcess`, `showTokens`).
- Ship matching Runtime 0.3.15 with the graph/memory hub changes used by node canvas and chat progress.

## 0.3.14

- Keep cold one-click deployment alive when multi-gigabyte Docker image pull output exceeds the extension's bounded diagnostic capture, and stream bootstrap activity into VS Code instead of appearing frozen.
- Detect an occupied but unresponsive Ollama port and automatically select and persist a free loopback port for the bundled CPU fallback on Windows, Linux, and macOS.
- Route Open WebUI embeddings to the provisioned Ollama `nomic-embed-text` model so a clean volume does not download SentenceTransformers during UI startup and miss its health window.
- Add an artifact-level Extension Host smoke test that activates the exact packaged extension, executes **Start all services**, and verifies its managed runtime plus all three HTTP surfaces.
- Show first-install image layers, extraction, model pulls, and health checks automatically in the AetherStack Output panel; retain the concise current step in VS Code's progress notification and allow a slow healthy cold install up to 60 minutes.
- Stop profile-gated fallback services with the rest of the stack, and make Restart rerun the full backend-selection and model-provisioning bootstrap.
- Package Linux/macOS shell entrypoints as executable files and fix the portable system scan's JSON-to-Python boolean conversion.
- Remove Chat's webview and VS Code title toolbars in favor of a searchable, compact monochrome composer menu containing dynamic slash presets, session/model controls, conversations, runtime/settings, and credential/CLI access actions; add small SVG edit/delete controls and show the answering or last-used model beside Send.
- Make the exact-VSIX Extension Host gate perform real `local-default` inference and retain model, token, platform, and loaded-memory evidence instead of treating three healthy HTTP ports as sufficient proof.
- Provision a signed user-space Ollama app automatically on macOS when host Ollama is absent, prefer that host process for Apple Metal, and stop only the host process that AetherStack itself started.
- Add a dedicated physical Apple Silicon workflow and cross-platform one-click verifier; the Metal gate rejects Intel, the Docker CPU fallback, zero GPU-resident model memory, missing inference, and incomplete lifecycle shutdown.
- Remove global Compose container names and reject occupied public ports before a clean verifier run, preventing stale or unrelated containers from being mistaken for the current isolated deployment.

## 0.3.13

- Make **Start all services** genuinely single-action on a Marketplace-only install: the VSIX now carries the checksum-verified matching runtime, installs it automatically, starts Docker Desktop when available, and invokes the same platform bootstrap used by source installs.
- Prefer an existing accelerated host Ollama, fall back to the bundled CPU container when none is reachable, and provision tool-capable `qwen2.5-coder:1.5b` plus embeddings so first-run chat can actually infer.
- Remove Chat's left history rail, move **New** and **History** beside **Refresh** and **Advanced**, and replace the small breathing bitmap with a full-chat rotating 3D ASCII AetherStack mark.
- Disable Open WebUI's independent update polling and add browser regression coverage for reload loops, redirects, empty-document replacement, and stacked full-viewport layers.

## 0.3.12
- Replace the MIT grant with the SPDX-listed PolyForm Noncommercial 1.0.0 terms and a required notice preserving original-author credit; AetherStack is now source-available, not OSI open source.
- Make the root `VERSION` the release source of truth and fail packaging when the extension, Compose runtime, or changelog disagrees.
- Add a verified runtime acquisition flow so a Marketplace-only installation can install and validate the matching AetherStack runtime before starting services.
- Isolate Chat context by conversation and VS Code thread, restore visible transcripts as inference context, and persist explicit preset selection truthfully.
- Put Chat and operations in clearly discoverable VS Code locations and align the extension's UI labels with those locations.
- Refresh authenticated host CLI providers during the extension lifecycle and include host CLI execution in privacy-minimal active-model telemetry.
- Keep generated project overviews free of absolute local paths and other machine-specific identity data.
- Package VSIX files outside the source tree, inspect their identity and contents, and publish the same checked artifact to Marketplace and GitHub Releases; build the runtime archive byte-deterministically.
- Keep multi-window host CLI discovery synchronized with the bridge that actually owns the port, locate the authenticated Codex CLI bundled with the official VS Code extension, and quarantine providers after terminal account or payment failures.
- Validate the full local runtime with a portable live smoke test and use hardware-adaptive local model installation on Windows, Linux, and macOS.
- Prefer the proven Windows Radeon Vulkan runtime, keep WSL ROCm opt-in, and honor a non-default `OLLAMA_BASE_URL` in startup, scanning, and auto-install scripts.
- Reduce same-backend duplicate inference calls, preserve reviewers for assurance-sensitive services, prevent internal orchestration language from leaking into final answers, and improve automatic bug-fixing intent selection.

## 0.3.11

- Render markdown and syntax-highlighted, copyable code blocks in AetherStack Chat (headings, lists, tables, blockquotes, links, bold/inline code) instead of showing raw text.
- Add per-message hover actions: copy any message, edit-and-resend a prior prompt, or regenerate an assistant reply.
- Add multi-conversation history: a responsive rail (permanent column when wide, toggled drawer when narrow) to start, switch between, and delete conversations, each persisted independently.
- Support attaching images and PDFs to a chat prompt: PDFs are text-extracted into the prompt, images route the final answer to a vision-capable model automatically (with a clear error if none is configured), both bounded to 8MB.
- Stream the final answer token-by-token as it's generated, with automatic fallback to a normal blocking response if the streaming connection drops mid-reply.

## 0.3.10

- Reskin AetherStack Chat as a plain monospace terminal: full-width monospace type, an "AE" mark instead of any generic branding, a bordered composer with a native `<fieldset>/<legend>` label showing the active routing mode (like a labeled terminal pane), a `>` prompt marker, and a bottom status line (workspace path, last reply's token count).
- Show a subtle animated ASCII "AE" mark (built from a small dot-matrix bitmap, not hand-typed art) filling the message area before the first message is sent, replacing the blank empty state.
- When "Show active model" is on, the active-model badge now renders in front of the rotating activity phrase in the composer, not after it.
- Add 9 more playful English/Estonian/Ukrainian phrases to the local activity-words database (`aether-hub/activity_words.json` and the live copy in `.aetherstack/`).

## 0.3.9

- Split the AetherStack Chat webview and the Control & Services tree into separate view containers: Chat stays alone in the Secondary Side Bar tab (matching the single-webview look of Claude Code/Codex/Grok), and Control & Services moves to its own Activity Bar icon. Previously both were stacked in one container, so the chat tab always showed the services/health/commands tree underneath it.

## 0.3.8

- Move the AetherStack view container from the Activity Bar to the Secondary Side Bar (`secondarySidebar` in `viewsContainers`), so it shows up as its own tab next to Claude Code, Codex, and other agent sidebars instead of only in the primary Activity Bar.
- Remove the AetherStack brand bar (logo + Simple/Advanced/WebUI nav) from the Hub's Simple and Advanced pages.

## 0.3.7

- Fix the Activity Bar icon rendering as a blank filled square: VS Code masks view-container icons to a single color using the SVG's alpha channel, so the opaque background tile in `media/icon.svg` was swallowing the glyph. The icon is now the glyph alone on a transparent background.
- Strip the Routing/Lean-delivery/Token-saver toolbar and the Dynamic-team/agent-graph panel out of AetherStack Chat's visible UI; the chat is now a plain message list and composer like Claude Code/Codex. Auto-routing and default lean/token settings still apply under the hood, and `/preset`, `/research`, `/plan`, `/code`, `/test`, `/bugfix`, `/auto`, `/help` still work — the controls are just no longer shown.
- Drop the canned greeting message and verbose subtitle; the chat now opens blank like a normal chat client.

## 0.3.6

- (Version bumped for a build that was packaged but never installed; superseded by 0.3.7 above.)

## 0.3.5

- Route Open WebUI through AetherHub's authenticated OpenAI-compatible facade so its Base Model list follows the live capability matrix, including authenticated host CLIs, while raw Ollama model entries are hidden.
- Correct TinyLlama's capability metadata and remove unsupported tool-call fields before inference instead of failing with `does not support tools`.
- Repair the embedded graph layout so its Node library delete control is never clipped; add concise hover descriptions and replace raw internal Inspector fields with clear task-oriented controls.
- Add editable default Markdown behavior profiles for every built-in service and load them into each generated agent node.
- Explain how to recover a missing Host CLI bridge and standardize Hub navigation as **Simple · Advanced · WebUI** with the current view highlighted.
- Redesign the Hub as a low-clutter, sharp-cornered dark operations console.

## 0.3.4

- Fix the host-CLI lifecycle gap that left capability resolution with Ollama only when Hub was already running: activation now detects authenticated Codex, Claude, and Grok CLIs, safely recreates only `aether-hub` when its bridge environment is stale, and refreshes the live matrix.
- Show the Host CLI bridge state and concrete failure reason in Hub Runtime & setup instead of silently hiding unavailable subscription providers.
- Move **Delete selected node** from the graph toolbar to the bottom of the left Node library card.

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
