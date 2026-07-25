# Operating model

Configure once. Operate from one client surface. Route work across models under a single gateway façade.

## Contract

| Outside | Inside |
|---------|--------|
| One chat window | LiteLLM + Hub routers + pipelines |
| One model id | Role-bound models (master, critic, worker, tester) |
| One API key | Provider keys held in `.env` / LiteLLM |
| Continuous conversation | Optional multi-stage graph: research → critique → build → test |

Policy lives in Aether (combos, pipelines, graphs, matrix). The IDE does not re-select providers per prompt.

---

## 1. Configure once

| Step | Action |
|------|--------|
| Stack | `start.bat` / `./start.sh` — Docker: WebUI, LiteLLM, Redis, Hub |
| Local GPU | Host Ollama (Metal / ROCm / CUDA). Not VS Code. |
| Secrets | `.env`: cloud keys + `LITELLM_MASTER_KEY` |
| Discover | Hub `GET /api/discover` or `scripts/scan-system.*` |
| Trees | Import combos, pipelines, or node graphs |
| Limits | Token saver; stage `max_cost` / `tier`; rotate default keys before exposure |
| IDE | OpenAI-compatible client → `http://127.0.0.1:4000/v1` + master key + one model alias |

---

## 2. Façade

```text
base_url = http://127.0.0.1:4000/v1
api_key  = <LITELLM_MASTER_KEY>
model    = <one alias>
```

| Surface | Role |
|---------|------|
| VS Code + Continue (or equivalent) | Primary coding surface |
| Open WebUI `:3000` | Browser surface on the same gateway |
| Aether Hub `:8766` | Operator console: discover, modes, graphs, slash, memory |

Client-facing model id remains the gateway alias. Multi-agent and pipeline execution are controlled via Hub APIs and imported trees.

---

## 3. Decision artifacts

| Artifact | Encodes |
|----------|---------|
| Combos | Role pins or single-tier packs (`.aether-combo.json`) |
| Pipelines | Ordered stages (`.aether-pipeline.yaml` / JSON) |
| Node graph | Visual graph at `/graph` (`aetherstack.graph.v1`) |
| Capability matrix | Per-model capabilities + live availability |
| Token saver | Cheap/local bias, token caps, prompt compression |

Catalogs: [combos/export](../combos/export), [pipelines/catalog](../pipelines/catalog).

---

## 4. Limits

| Control | Effect |
|---------|--------|
| `token_saver: true` | Prefer cheap/local; truncate long context |
| Stage / node `max_cost` | Cap role cost band (`low` … `very_high`) |
| `tier: local` | Bind stage to Ollama |
| Maker pins | Fixed provider per role |
| Pipeline `hw_weight` | Documented GPU weight for ranking |
| `/done` then `/clear` or `/compact` | Archive then reset working session |

Provider billing remains provider-side. Aether enforces routing policy only.

---

## 5. Daily loop

```text
Start stack
  → open project → chat via gateway alias
  → structured work: pipeline/graph plan when required
  → task complete: /done all
  → /compact or /clear
  → next unit of work (lean context; memory searchable)
```

---

## 6. Hard constraints

| Constraint | Fact |
|------------|------|
| GPU for weights | Host Ollama (or cloud). Not VS Code. Not LiteLLM container by default. |
| Façade quality | Bound by imported trees, live discover, and present keys |
| Multi-agent cost | Fan-out can exceed single-call tokens; token saver + slash hygiene apply |
| Node canvas | Native MIT graph only. No third-party node engine is vendored in this repo. |

---

## Related

| Doc | Topic |
|-----|--------|
| [README.md](./README.md) | Documentation index |
| [QUICKSTART.md](./QUICKSTART.md) | Install, ports, IDE |
| [GATEWAY.md](./GATEWAY.md) | LiteLLM aliases and keys |
| [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md) | Extension procedure |
| [PIPELINES.md](./PIPELINES.md) | Stage scripts |
| [NODE-GRAPH.md](./NODE-GRAPH.md) | Canvas |
| [SLASH-COMMANDS.md](./SLASH-COMMANDS.md) | Session hygiene |
| [CROSS-MEMORY.md](./CROSS-MEMORY.md) | Multi-project index |
| [AGENT-MODES.md](./AGENT-MODES.md) | Inline / multi-agent |
| [AMD-COMPUTE.md](./AMD-COMPUTE.md) | Radeon CUs |
