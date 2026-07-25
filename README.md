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
| One façade | One base URL + one gateway master key; many models underneath |
| **Multi-key per provider** | **Subscription/personal + enterprise API keys simultaneously** for every cloud maker (Anthropic, OpenAI, xAI, Google, Mistral). Aliases: `*-personal` / `*-enterprise` — no key swap restarts. [docs/MULTI-KEYS.md](./docs/MULTI-KEYS.md) |
| Orchestration | Combos, pipelines, node canvas by role / tier / cost |
| Spend control | Token saver, tier caps, `/done` → `/clear` |
| Continuity | Fail over cloud → other key/slot → local GPU when limits hit |
| Memory | Archive on clear; multi-project pull when enabled |
| **Backup** | **Project or global** export of memory/research/sessions — **manual or scheduled** — to **local PC folders** and/or pre-configured **AWS S3 / Azure** buckets. [docs/BACKUP.md](./docs/BACKUP.md) |
| Private mode | Project/model flag → isolated vault; no common pool/logs until release |
| Hardware | Host Ollama on Metal / ROCm CUs / CUDA; Docker = control plane |
| Portability | Export/import combos, pipelines, graphs |

### Workflow delta

| Before | After |
|--------|-------|
| Product hop per task | One chat; policy selects models |
| Manual context re-paste | Shared memory + optional cross-project index |
| Model choice every prompt | Combos / pipelines / node graph |
| Hard stop at one vendor’s session/day cap | Continue via next model in the pool or local GPU |
| One API key per provider (personal vs work fight) | Personal/subscription + enterprise keys both live; pick via alias |
| Unbounded context growth | Unit complete → archive → clear |
| Sensitive work mixed into cloud chat | Private mode / local-only path |

**Loop:** start stack → open project → chat via gateway → `/done` → `/clear` or `/compact` → next unit.

---

## Workflows (why the pipeline exists)

### 1. Long coding day — no hard stop when one subscription hits a wall

**Scene:** You code in VS Code or a local CLI for hours. Continue / Claude Code / Codex / Grok-class agents run under **one** Aether gateway endpoint. You hold one or more cloud subscriptions (Claude, Codex/OpenAI, Grok/xAI, Mistral, …) plus **host Ollama** on Metal / ROCm / CUDA.

**Without Aether:** One provider hits a session, daily, or weekly limit → hard stop. You open another app, re-import chat, re-pick files, re-state goals, lose agent state.

**With Aether:**

| Step | What happens |
|------|----------------|
| Work surface | Stay in VS Code / CLI / Open WebUI. Same base URL, same master key, same façade model id. |
| Policy | Combos / pipelines / capability matrix define **ordered fallbacks** (e.g. Sonnet → GPT → Grok → Codestral → `local-default`). |
| Quota pressure | When a maker is unavailable, rate-limited, or pinned off, routing moves to the **next live** model — including the same maker on another **key slot** (`*-personal` vs `*-enterprise`) if that account still has headroom. |
| No cloud left | Pool falls through to **local inference** (slower, still completes the job). |
| Continuity | Hub memory + `/done` → `/compact` or `/clear` keeps decisions; you do not rebuild the brief from zero in a new vendor UI. |

You are not “switching products.” You stay in one window; the control plane switches engines under the façade.

Configure: [docs/OPERATING-MODEL.md](./docs/OPERATING-MODEL.md) · [docs/AGENT-MODES.md](./docs/AGENT-MODES.md) · [combos/](./combos/) · [docs/PIPELINES.md](./docs/PIPELINES.md)

### 2. Structured jobs — research → critique → build → test without re-briefing

**Scene:** A feature needs research, an adversarial pass, implementation, and tests. Different tiers/makers fit different stages.

| Stage | Typical bias |
|-------|----------------|
| Research | High-tier cloud (or local if private) |
| Critique / ack | Different maker than research |
| Build | Mid-tier or local workers |
| Test | Cheap / local |

Pipelines and the **node canvas** encode that tree once. Agents plan against live availability. After the unit finishes: `/done` → archive → `/clear`. Next job starts lean; search memory if old decisions matter.

### 3. Private / air-gapped segments — sensitive research stays off the provider

**Scene:** Part of the work must not leave the machine (security, NDA, unpublished research). Online agents must not see that material.

| Control | Effect |
|---------|--------|
| **Private mode** | Flag project and/or model. Session and vectors go to an isolated vault. No common memory pool, no xref index, no contentful system logs. |
| **Local-only combos** | e.g. `private_local` / `inline_fable` — stages pinned to Ollama on host GPU. |
| **Release** | Explicit only. Vault is not merged into the shared pool on release unless you choose to re-index later. |

Stay on the same IDE surface; switch policy (private + local tier) for the sensitive slice, then return to multi-cloud routing for the rest.

Procedure: [docs/PRIVATE-MODE.md](./docs/PRIVATE-MODE.md) · [docs/AMD-COMPUTE.md](./docs/AMD-COMPUTE.md) / platform GPU docs for local speed.

### 4. Operator loop (daily)

```text
Start stack (leave running)
  → IDE → gateway façade (one model id)
  → multi-hour work: cloud A → cloud B → local as limits/policy demand
  → optional private segment for sensitive research
  → /done → /compact or /clear
  → next unit (memory holds archives; chat stays short)
```

Deep detail: [docs/OPERATING-MODEL.md](./docs/OPERATING-MODEL.md)

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
| Multi-account keys | [docs/MULTI-KEYS.md](./docs/MULTI-KEYS.md) (personal + enterprise per provider) |
| Backup (local / AWS / Azure) | [docs/BACKUP.md](./docs/BACKUP.md) |
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
