# Changelog

## 0.1.2

- Marketplace README: remove packaging / `vsce publish` developer instructions (user-facing only)
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
