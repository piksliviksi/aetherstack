# AetherStack

![AetherStack](./aetherstack.jpg)

**One setup. One chat window. Many models underneath.**

Local multi-model control plane. Configure policy once. Operate from VS Code or Open WebUI against a single gateway. Research, critique, code, and test route across local GPU and cloud providers under that policy.

| | |
|---|---|
| **Repo** | [github.com/piksliviksi/aetherstack](https://github.com/piksliviksi/aetherstack) |
| **VS Code** | [Marketplace · AetherStack](https://marketplace.visualstudio.com/items?itemName=AetherStack.aetherstack) |
| **Platforms** | Windows 11 · macOS (Intel / Apple Silicon) · Ubuntu/Linux |

---

## Capabilities

| Capability | Fact |
|------------|------|
| One surface | VS Code or browser chat for normal work |
| One façade | One base URL, one API key, one model id |
| Orchestration | Combos, pipelines, node canvas by role / tier / cost |
| Spend control | Token saver, tier caps, `/done` → `/clear` |
| Memory | Archive on clear; multi-project pull when enabled |
| Private mode | Project/model flag → isolated vault; no common pool/logs until release |
| Hardware | Host Ollama on Metal / ROCm CUs / CUDA; Docker = control plane |
| Portability | Export/import combos, pipelines, graphs |

### Workflow delta

| Before | After |
|--------|-------|
| Product hop per task | One chat; policy selects models |
| Manual context re-paste | Shared memory + optional cross-project index |
| Model choice every prompt | Combos / pipelines / node graph |
| Unbounded context growth | Unit complete → archive → clear |
| Split IDE / cloud / local | One gateway for IDE, WebUI, scripts |

**Loop:** start stack → open project → chat via gateway → `/done` → `/clear` or `/compact` → next unit.

Operating model: [docs/OPERATING-MODEL.md](./docs/OPERATING-MODEL.md)

---

## Start

| OS | Start | Stop | Tutorial |
|----|--------|------|----------|
| **Windows** | `start.bat` | `stop.bat` | [TUTORIAL-WINDOWS](./docs/TUTORIAL-WINDOWS.md) |
| **macOS** | `./start.sh` | `./stop.sh` | [TUTORIAL-MACOS](./docs/TUTORIAL-MACOS.md) |
| **Ubuntu/Linux** | `./start.sh` | `./stop.sh` | [TUTORIAL-UBUNTU](./docs/TUTORIAL-UBUNTU.md) |

| Requirement | |
|-------------|-|
| Docker | Required |
| Host Ollama | Required for local GPU inference |
| `.env` | Copy from `.env.example`; set keys in use |

| Open | URL |
|------|-----|
| Chat | http://localhost:3000 |
| Gateway | http://localhost:4000/v1 |
| Hub | http://localhost:8766 |

Procedure: [docs/QUICKSTART.md](./docs/QUICKSTART.md)

---

## Services

| Service | Port | Role |
|---------|------|------|
| Open WebUI | 3000 | Browser chat |
| LiteLLM | 4000 | OpenAI-compatible gateway |
| Aether Hub | 8766 | Discover, routes, combos, pipelines, graph, memory, slash |
| Redis | 6379 | Cache + agent memory |
| Ollama (host) | 11434 | Local inference (Metal / ROCm / CUDA) |

---

## Documentation

| Topic | Location |
|-------|----------|
| Operating model | [docs/OPERATING-MODEL.md](./docs/OPERATING-MODEL.md) |
| Install / IDE | [docs/QUICKSTART.md](./docs/QUICKSTART.md) |
| VS Code extension | [docs/VSCODE-EXTENSION.md](./docs/VSCODE-EXTENSION.md) |
| Combos / pipelines / graph | [combos/](./combos/) · [docs/PIPELINES.md](./docs/PIPELINES.md) · [docs/NODE-GRAPH.md](./docs/NODE-GRAPH.md) |
| Agent modes | [docs/AGENT-MODES.md](./docs/AGENT-MODES.md) |
| Memory / multi-project | [docs/AGENT-MEMORY.md](./docs/AGENT-MEMORY.md) · [docs/CROSS-MEMORY.md](./docs/CROSS-MEMORY.md) |
| Private isolation | [docs/PRIVATE-MODE.md](./docs/PRIVATE-MODE.md) |
| Slash hygiene | [docs/SLASH-COMMANDS.md](./docs/SLASH-COMMANDS.md) |
| Gateway aliases | [docs/GATEWAY.md](./docs/GATEWAY.md) |
| GPU | [docs/GPU-NVIDIA.md](./docs/GPU-NVIDIA.md) · [docs/AMD-COMPUTE.md](./docs/AMD-COMPUTE.md) · [docs/WSL-AMD-GPU.md](./docs/WSL-AMD-GPU.md) · [docs/GPU-INTEL.md](./docs/GPU-INTEL.md) |
| Capability matrix | [docs/CAPABILITY-MATRIX.md](./docs/CAPABILITY-MATRIX.md) |
| Project engine | [project-engine/README.md](./project-engine/README.md) |
| Security | [docs/SECURITY-NOTES.md](./docs/SECURITY-NOTES.md) |
| Future / enterprise | [docs/FUTURE.md](./docs/FUTURE.md) |
| Full index | [docs/README.md](./docs/README.md) |

---

## License

MIT — [LICENSE](./LICENSE).

Built on [Ollama](https://ollama.com), [Open WebUI](https://github.com/open-webui/open-webui), [LiteLLM](https://github.com/BerriAI/litellm), Redis. Not affiliated.
