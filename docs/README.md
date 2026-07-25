# Documentation index

Product summary: root [README](../README.md).  
This tree holds procedures, APIs, and platform facts.

---

## Start

| Doc | Contents |
|-----|----------|
| [OPERATING-MODEL.md](./OPERATING-MODEL.md) | Configure once, façade, daily loop, constraints |
| [QUICKSTART.md](./QUICKSTART.md) | Prerequisites, start/stop, ports, IDE |
| [TUTORIAL-WINDOWS.md](./TUTORIAL-WINDOWS.md) | Windows 11 |
| [TUTORIAL-MACOS.md](./TUTORIAL-MACOS.md) | macOS + Metal |
| [TUTORIAL-UBUNTU.md](./TUTORIAL-UBUNTU.md) | Ubuntu / Linux |

---

## Surfaces

| Doc | Contents |
|-----|----------|
| [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md) | Extension install and commands |
| [VSCODE.md](./VSCODE.md) | IDE vs GPU architecture |
| [VSCODE-PUBLISH.md](./VSCODE-PUBLISH.md) | Marketplace publish procedure |
| [DOCKER-EXTENSION.md](./DOCKER-EXTENSION.md) | Docker Desktop extension scaffold |
| [GATEWAY.md](./GATEWAY.md) | LiteLLM aliases, keys, 401 |
| [MULTI-KEYS.md](./MULTI-KEYS.md) | Personal + enterprise keys per provider |

---

## Orchestration and memory

| Doc | Contents |
|-----|----------|
| [AGENT-MODES.md](./AGENT-MODES.md) | Inline / multi-agent, token saver |
| [AGENT-MEMORY.md](./AGENT-MEMORY.md) | Redis sessions + vectors |
| [CROSS-MEMORY.md](./CROSS-MEMORY.md) | Multi-project scan / pull |
| [PRIVATE-MODE.md](./PRIVATE-MODE.md) | Private project/model vault isolation |
| [SLASH-COMMANDS.md](./SLASH-COMMANDS.md) | `/done`, `/clear`, `/compact` |
| [PIPELINES.md](./PIPELINES.md) | Multi-stage scripts + votes |
| [NODE-GRAPH.md](./NODE-GRAPH.md) | Canvas `/graph` |
| [CAPABILITY-MATRIX.md](./CAPABILITY-MATRIX.md) | Routing matrix |
| [AUTO-INSTALL.md](./AUTO-INSTALL.md) | Bootstrap install (off by default) |
| [PROJECT-ENGINE.md](./PROJECT-ENGINE.md) | Project footprint engine |

In-repo catalogs:

| Path | Role |
|------|------|
| [combos/](../combos/) | Tier + situation packs |
| [pipelines/catalog/](../pipelines/catalog/) | Pipeline scripts |
| [aether-hub/](../aether-hub/) | Hub service |

---

## GPU and platforms

| Doc | Contents |
|-----|----------|
| [GPU-NVIDIA.md](./GPU-NVIDIA.md) | NVIDIA / CUDA |
| [GPU-INTEL.md](./GPU-INTEL.md) | Intel / OpenVINO |
| [AMD-COMPUTE.md](./AMD-COMPUTE.md) | Radeon CUs, adapter |
| [WSL-AMD-GPU.md](./WSL-AMD-GPU.md) | Windows + WSL ROCm |
| [TUTORIAL-MACOS.md](./TUTORIAL-MACOS.md) | Host Ollama + Metal |

Code: [aether-amd/](../aether-amd/), `scripts/scan-system.*`, `scripts/auto-install.*`.

---

## Security

| Doc | Contents |
|-----|----------|
| [SECURITY-NOTES.md](./SECURITY-NOTES.md) | Findings, mitigations, tokens |

---

## Roadmap

| Doc | Contents |
|-----|----------|
| [FUTURE.md](./FUTURE.md) | Planned work (enterprise shared account, silos, token pool) |

---

## Reading order

1. Root README  
2. OPERATING-MODEL  
3. QUICKSTART + platform tutorial  
4. VSCODE-EXTENSION (IDE operators)  
5. Combos / pipelines / node graph  
6. Memory + slash  
7. GPU doc for installed hardware  
