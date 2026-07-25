# AetherStack documentation

Service overview and benefits live in the root [README](../README.md).  
This folder is the **technical depth** map.

---

## Start here

| Doc | Contents |
|-----|----------|
| [OPERATING-MODEL.md](./OPERATING-MODEL.md) | Modus operandi: one façade, decision trees, daily loop |
| [QUICKSTART.md](./QUICKSTART.md) | Prerequisites, `.env`, first start, IDE wire-up, ports |
| [TUTORIAL-WINDOWS.md](./TUTORIAL-WINDOWS.md) | Windows 11 walkthrough |
| [TUTORIAL-MACOS.md](./TUTORIAL-MACOS.md) | macOS + Metal / Apple Silicon |
| [TUTORIAL-UBUNTU.md](./TUTORIAL-UBUNTU.md) | Ubuntu / Linux walkthrough |

---

## Product surfaces

| Doc | Contents |
|-----|----------|
| [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md) | Marketplace extension: commands, Continue, help |
| [VSCODE.md](./VSCODE.md) | Architecture notes (GPU is not inside VS Code) |
| [VSCODE-PUBLISH.md](./VSCODE-PUBLISH.md) | Publishing the extension |
| [DOCKER-EXTENSION.md](./DOCKER-EXTENSION.md) | Optional Docker Desktop extension scaffold |
| [GATEWAY.md](./GATEWAY.md) | LiteLLM façade, model aliases, API keys, 401 notes |

---

## Orchestration & memory

| Doc | Contents |
|-----|----------|
| [AGENT-MODES.md](./AGENT-MODES.md) | Inline vs multi-agent, token saver, role pins |
| [AGENT-MEMORY.md](./AGENT-MEMORY.md) | Redis sessions + vector memory |
| [CROSS-MEMORY.md](./CROSS-MEMORY.md) | Multi-project scan / search / auto-pull |
| [SLASH-COMMANDS.md](./SLASH-COMMANDS.md) | `/done`, `/clear`, `/compact` hygiene |
| [PIPELINES.md](./PIPELINES.md) | Multi-stage scripts + voting |
| [NODE-GRAPH.md](./NODE-GRAPH.md) | Visual node canvas (`/graph`) |
| [CAPABILITY-MATRIX.md](./CAPABILITY-MATRIX.md) | Local ↔ cloud routing matrix |
| [AUTO-INSTALL.md](./AUTO-INSTALL.md) | Optional auto-install of missing packages |
| [PROJECT-ENGINE.md](./PROJECT-ENGINE.md) | Project footprint / cleanup engine (if present) |

Catalogs in-repo:

- [combos/](../combos/) — tier + situation packs  
- [pipelines/catalog/](../pipelines/catalog/) — shareable pipeline scripts  
- [aether-hub/](../aether-hub/) — hub service source + API notes  

---

## GPU & platforms

| Doc | Contents |
|-----|----------|
| [GPU-NVIDIA.md](./GPU-NVIDIA.md) | NVIDIA / CUDA path |
| [GPU-INTEL.md](./GPU-INTEL.md) | Intel / OpenVINO path |
| [AMD-COMPUTE.md](./AMD-COMPUTE.md) | Radeon CUs, userspace adapter |
| [WSL-AMD-GPU.md](./WSL-AMD-GPU.md) | Windows + WSL ROCm Ollama |
| [TUTORIAL-MACOS.md](./TUTORIAL-MACOS.md) | Host Ollama + Metal |

Related code: [aether-amd/](../aether-amd/), `scripts/scan-system.*`, `scripts/auto-install.*`.

---

## Security & ops

| Doc | Contents |
|-----|----------|
| [SECURITY-NOTES.md](./SECURITY-NOTES.md) | Auth, keys, bind addresses, engine token |

---

## Suggested reading order

1. Root README (what you get)  
2. [OPERATING-MODEL.md](./OPERATING-MODEL.md)  
3. [QUICKSTART.md](./QUICKSTART.md) + your platform tutorial  
4. [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md) if you live in the IDE  
5. Combos / pipelines / graph as you outgrow “one model alias”  
6. Memory + slash when sessions get long  
7. GPU docs for your hardware  
