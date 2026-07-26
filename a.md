# Code Scan Report

The scan found six actionable issues. No source files were changed during the scan.

## 1. Critical — unauthenticated services exposed on all interfaces

Docker publishes Open WebUI, Redis, LiteLLM, and optional Ollama without loopback binding. Open WebUI authentication is disabled, Redis has no authentication, and the Docker Extension leaves LiteLLM's master key empty. This can expose model access and cloud API spending to the local network.

Relevant locations:

- `docker-compose.yml:27`
- `extension/docker-compose.yaml:27`

Recommended fix: bind ports to `127.0.0.1`, stop publishing Redis, and require strong authentication.

## 2. High — browser-accessible arbitrary directory inspection

The project engine accepts any filesystem path while sending `Access-Control-Allow-Origin: *`. Another permitted browser origin can retrieve directory names, dependency declarations, host details, and potentially credentials embedded in requirement URLs.

Relevant locations:

- `project-engine/server.py:33`
- `project-engine/server.py:52`
- `project-engine/collectors.py:316`

Recommended fix: restrict scans to an approved root and require a session token or same-origin requests.

## 3. High — dashboard XSS through filenames and system data

API values are interpolated directly into `innerHTML`. A crafted project filename can execute JavaScript in the dashboard's localhost origin, then access the filesystem-scanning APIs.

Relevant locations:

- `project-engine/static/index.html:121`
- `project-engine/static/index.html:169`

Recommended fix: construct DOM elements with `textContent` or escape every untrusted value.

## 4. High — extension persists API keys in project files

`cfg()` includes the API key in `project-overview.json`, `.continue/config.yaml`, and `.vscode/settings.json`. These files can be committed from repositories without matching ignore rules.

Relevant locations:

- `integrations/vscode/extension.js:157`
- `integrations/vscode/extension.js:174`
- `integrations/vscode/extension.js:480`

Recommended fix: use VS Code secret storage and omit credentials from generated metadata.

## 5. Medium — setup commands can destroy existing configuration

Continue's configuration is overwritten unconditionally. VS Code `settings.json` is parsed as strict JSON even though it commonly contains JSONC comments; a parse failure resets it to `{}` before overwriting.

Relevant locations:

- `integrations/vscode/extension.js:450`
- `integrations/vscode/extension.js:469`

Recommended fix: use a JSONC-aware editor and require confirmation or create a backup before replacing Continue configuration.

## 6. Low — flawed static-file containment check

String-prefix comparison permits access to sibling paths whose names begin with `static`, such as `static-private`.

Relevant location:

- `project-engine/server.py:60`

Recommended fix: use `Path.is_relative_to()` against the resolved static directory.

## Verification

- Python syntax passed.
- JavaScript syntax passed.
- JSON manifests parsed successfully.
- Shell scripts passed `bash -n`.
- PowerShell scripts passed parser validation.
- Docker Compose configuration passed validation.
- Both VSIX artifacts are identical and contain the current extension source.
- No unit-test suite was found.
- Several container images use mutable `main` or `latest` tags.
- `.env` is ignored, and no tracked live secrets were identified.
- The existing uncommitted `docker-compose.yml` edit was preserved; the networking exposure predates that edit.
