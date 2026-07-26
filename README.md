# AetherStack

<img src="./aetherstack-icon.png" alt="AetherStack" width="128" height="128">

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
| One surface | AetherStack Chat in VS Code or the simple Hub for normal work; Open WebUI remains optional |
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

From VS Code, open **AetherStack → Control & Services** and press **Start all services**. The extension starts the same Compose stack, monitors `:3000`, `:4000`, and `:8766`, and reports each endpoint as `OK` or with its concrete error. The script alternatives remain available:

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
| Simple services UI | http://localhost:8766 |
| Optional Open WebUI | http://localhost:3000 |
| Gateway | http://localhost:4000/v1 |
| Advanced Hub | http://localhost:8766/advanced |
| Node graph | http://localhost:8766/graph |

The chat UI is local and does not ask for a separate password. A proxy bound
only to `127.0.0.1:3000` signs the browser into the existing sole Open WebUI
admin account; the authenticated backend is not exposed directly. If the
database has multiple admins, set `AETHER_LOCAL_WEBUI_EMAIL` in the root `.env`.

Procedure: [docs/QUICKSTART.md](./docs/QUICKSTART.md)

### Task-first services and lean delivery

The default Hub page offers Research, Planning, Service design, UI design,
Frontend, Backend, Coding, Testing, Bug fixing, White-hat pentesting,
Polishing, and Technical writing. These are capability blueprints, not fixed
model lists: Hub resolves every role from the models and provider keys that are
currently available, verifies the selected aliases through LiteLLM, and adapts
the team when a provider is offline.

The same combined chat opens as an **AetherStack Chat** editor tab in VS Code.
Its default **Auto** mode classifies the current coding stage from the task and
activates the matching service tree; the catalog, activities, and agent lineup
remain data-driven and every model is resolved from live capabilities. Expand
the collapsed full advanced canvas below the preset workspace; it loads the
selected service's live lead, parallel workers, reviewer, synthesis, and model
assignments. The same tree opens full-page at `/graph`, while the separate
Advanced setup button opens technical configuration. Each run uses a lead, parallel
workers, a reviewer, and final synthesis. Lean
Delivery and the token saver can reduce unnecessary context and output without
removing validation, security controls, accessibility, tests, or observability.
The lean policy is an independent implementation inspired by
[Ponytail](https://github.com/DietrichGebert/ponytail); no Ponytail source code
is copied. Ponytail is MIT-licensed, so a future direct code reuse must retain
its copyright and permission notice.

When active-model display is enabled, VS Code Chat shows the aliases currently
inferring alongside rotating English, Estonian, and Ukrainian activity text.
The tracked defaults live in `aether-hub/activity_words.json`; the running
container seeds a persistent `.aetherstack/activity_words.json`, which can be
added to or deleted from Advanced Hub.

The Simple Hub also includes **Update AetherStack**. It checks the official
repository and stages a checksummed archive under `.aetherstack/updates`; it
never overwrites a working checkout from the browser. Review local changes and
apply the staged update from a trusted host workflow.

---

## Services

| Service | Port | Role |
|---------|------|------|
| Open WebUI local proxy | 3000 | Passwordless loopback browser chat |
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
| Full index | [docs/README.md](./docs/README.md) |

---

## License

MIT — [LICENSE](./LICENSE).

Built on [Ollama](https://ollama.com), [Open WebUI](https://github.com/open-webui/open-webui), [LiteLLM](https://github.com/BerriAI/litellm), Redis. Not affiliated.
