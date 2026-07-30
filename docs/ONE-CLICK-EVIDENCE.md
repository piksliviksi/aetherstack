# One-click deployment evidence

This document defines what AetherStack must prove before a VS Code release is
described as one-click verified. It separates product evidence from platform
assumptions and prevents endpoint-only smoke tests from being reported as real
inference success.

## Acceptance contract

The reproducible verifier must:

1. Install the exact packaged VSIX into an isolated VS Code extensions folder.
2. Activate `AetherStack.aetherstack` from a clean VS Code user-data folder.
3. Execute `AetherStack: Start All Services` once.
4. Install and checksum-verify the matching bundled Runtime.
5. Reach HTTP success on `127.0.0.1:3000`, `:4000`, and `:8766`.
6. Submit a real `local-default` chat completion through LiteLLM and receive
   `AETHERSTACK_ONE_CLICK_OK`.
7. Inspect the model loaded by Ollama and retain its memory placement.
8. Restart through the extension when lifecycle coverage is requested.
9. Stop through the extension and clean only the isolated Compose project.

The verifier refuses to start when ports 3000, 4000, or 8766 are already in
use. Compose services have no global `container_name` values, so every evidence
run is owned by its unique project name and stale containers cannot impersonate
the current run.

For Apple Metal evidence, the verifier additionally requires native `darwin`
on `arm64`, host Ollama rather than the Docker fallback, and a loaded model with
nonzero `size_vram`. Packaging on macOS, an Intel macOS run, or three healthy
ports do not satisfy this requirement.

## Platform prerequisite boundary

VS Code and a working Docker Desktop / Docker Engine installation are operating
system prerequisites. Docker is not silently installed or its third-party
license accepted by the extension. Once that prerequisite is present, the VSIX
installs its verified Runtime and provisions a usable local model backend.

On macOS, Start reuses host Ollama or downloads the official signed application
to the user's AetherStack tools directory. This avoids administrator access and
keeps Apple Silicon inference on the host Metal path. The Docker CPU fallback
remains available when automatic host Ollama installation is disabled or fails.

## Evidence command

```bash
npm --prefix integrations/vscode run release:check
node scripts/verify-one-click.mjs --restart --evidence dist/one-click-evidence.json
```

On a dedicated physical Apple Silicon Mac:

```bash
node scripts/verify-one-click.mjs \
  --restart \
  --require-accelerator \
  --evidence dist/macos-metal-evidence.json
```

## Current evidence state for 0.3.14

| Platform | Exact VSIX | Runtime and services | Real inference | Accelerator evidence | Status |
|---|---:|---:|---:|---:|---|
| Windows 11 x64 | Yes | Yes | Yes | RX 6600 XT host Ollama/Vulkan; `qwen2.5-coder:1.5b` fully VRAM-resident | Passed |
| Debian Linux userland with native systemd Docker daemon under WSL2 | Yes | Yes | Yes | CPU fallback | Passed for this environment; not independent bare-metal Linux evidence |
| Native Apple Silicon macOS | Not yet | Not yet | Not yet | Not yet | Pending physical/self-hosted Mac run |

GitHub-hosted macOS jobs are useful for source, packaging, and shell checks, but
cannot prove the full runtime because Apple's hosted runner environment does not
provide the nested virtualization required by Docker Desktop or Colima. The
`macos-metal-e2e.yml` workflow therefore targets a dedicated physical runner
with labels `self-hosted`, `macOS`, `ARM64`, and `aetherstack-metal`.

The 2026-07-31 Windows run installed the VSIX into an empty extensions folder,
used an empty VS Code workspace and user-data directory, restarted the isolated
stack, returned the exact inference sentinel with 49 total tokens, reported
1,163,080,498 model bytes in VRAM, and stopped its own Compose project. The
final rebuilt artifacts are:

- VSIX SHA-256: `2405f23edf8fbf0f117266b3c21f57ca06be765d39348a8084a5f7dc998c8ebe`
- Runtime SHA-256: `a83ac144d406d676edf93c1ccd3b92120096f83dda9c200a01fb1261398c9ee7`
