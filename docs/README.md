# Documentation index

Product summary: root [README](../README.md).  
This tree holds procedures, APIs, and platform facts.

---

## Start

| Doc | Contents |
|-----|----------|
| **[OPERATING-MODEL.md](./OPERATING-MODEL.md)** | **How AetherStack works: pass-through Auto mode, the shared memory pool, the two tiers, first run. Read this first.** |
| [QUICKSTART.md](./QUICKSTART.md) | Prerequisites, start/stop, ports, IDE |
| [TUTORIAL-WINDOWS.md](./TUTORIAL-WINDOWS.md) | Windows 11 |
| [TUTORIAL-MACOS.md](./TUTORIAL-MACOS.md) | macOS + Metal |
| [TUTORIAL-UBUNTU.md](./TUTORIAL-UBUNTU.md) | Ubuntu / Linux |
| [DEBIAN-DISTRO-BUILD.md](./DEBIAN-DISTRO-BUILD.md) | Design guide: Debian-based OS image with AetherStack built in |
| [ENTERPRISE-PLATFORM.md](./ENTERPRISE-PLATFORM.md) | Desktop / Team Server / Cloud SKUs, trust boundaries, multi-user enterprise |
| [ENTERPRISE-ROADMAP.md](./ENTERPRISE-ROADMAP.md) | E0–E5 milestones vs MULTI-USER M0–M4 |
| [MULTI-USER.md](./MULTI-USER.md) | Team multi-user feature roadmap |
| [schemas/](./schemas/) | Tenancy, audit, file-lease JSON contracts (v0) |

---

## Surfaces

| Doc | Contents |
|-----|----------|
| [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md) | Extension install and commands |
| [VSCODE.md](./VSCODE.md) | IDE vs GPU architecture |
| [DOCKER-EXTENSION.md](./DOCKER-EXTENSION.md) | Docker Desktop extension scaffold |
| [GATEWAY.md](./GATEWAY.md) | LiteLLM aliases, keys, 401 |
| [MULTI-KEYS.md](./MULTI-KEYS.md) | Personal + enterprise keys per provider |
| [BACKUP.md](./BACKUP.md) | Project/global backup to local PC, AWS, Azure |
| [ONE-CLICK-EVIDENCE.md](./ONE-CLICK-EVIDENCE.md) | What a release must prove before it is called one-click verified |

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

Code: [aether-amd/](../aether-amd/), `scripts/scan-system.ps1`, `scripts/auto-install.ps1` (GPU-aware); the `.sh` counterparts are generic host-scan/bootstrap only.

---

## Security

| Doc | Contents |
|-----|----------|
| [SECURITY-NOTES.md](./SECURITY-NOTES.md) | Findings, mitigations, tokens |

---

## Reading order

1. Root README — what the product is  
2. **OPERATING-MODEL — how it works: pass-through, memory pool, two tiers**  
3. QUICKSTART + platform tutorial  
4. VSCODE-EXTENSION (IDE operators)  
5. AGENT-MEMORY + SLASH-COMMANDS — Tier 1 continuity  
6. NODE-GRAPH / PIPELINES / combos — Tier 2 trees  
7. GPU doc for installed hardware  
