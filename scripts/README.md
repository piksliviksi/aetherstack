# scripts/

Helpers for one-click start, packaging, GPU/WSL install, and release gates.

## Wired into product paths

| Script | Used by |
|--------|---------|
| `select-cli-bridge-port.mjs` | `start.ps1`, `start.sh` — free host CLI bridge port (`DEFAULT_PORT` / `FALLBACK_PORTS` from `integrations/vscode/cli-bridge.js`) |
| `cli-bridge-daemon.js` | `start.ps1`, `start.sh` — host Codex/Claude/Grok bridge process |
| `scan-system.ps1` / `scan-system.sh` | Start scripts, Hub scan publish |
| `auto-install.ps1` / `auto-install.sh` | Optional post-start package install |
| `package-vscode.mjs`, `package-runtime.mjs` | `integrations/vscode` npm package scripts |
| `verify-release.mjs`, `verify-vsix.mjs`, `verify-runtime.mjs`, `verify-one-click.mjs` | `release:check` / release CI |
| `gen-multi-key-aliases.py` | Regenerates multi-account LiteLLM aliases (see `litellm_config.yaml` comment) |
| `progress-filter.py` | `start.sh` compose progress |
| `backup-aether.ps1` / `backup-aether.sh` | Backup docs |
| `ensure-wsl-ollama.ps1`, `install-ollama-rocm-wsl.sh`, `wire-ollama-wsl.sh`, … | AMD/WSL GPU docs |

## Manual / lab tools (kept, not imported by start)

These are operator utilities. They are not called from start scripts or npm; keep them only if docs or maintainers still use them.

| Script | Intent |
|--------|--------|
| `audit-service-presets.py` | One-off preset graph audit |
| `browser-smoke.mjs` | Browser smoke against a running stack |
| `e2e-radio-stone-graph-test.py` | Graph e2e lab |
| `runtime-smoke.py` | Runtime smoke against Hub |
| `scan-project-ai.ps1` / `scan-project-ai.sh` | Project AI file scan (optional local) |
| `scan-cross-projects.ps1` | Cross-project memory scan |
| `test-ollama-cpu-wsl.sh`, `test-ollama-gpu-wsl.sh`, `test-wsl-gpu.sh` | WSL GPU lab checks |
| `install-rocm72-wsl.sh` | ROCm install helper |
| `list-models.ps1` / `list-models.sh` | List gateway models |
| `amd-compute-status.sh` | AMD compute status |

If a script here has zero maintainers and zero docs links for a release cycle, delete it rather than leaving an orphan.
