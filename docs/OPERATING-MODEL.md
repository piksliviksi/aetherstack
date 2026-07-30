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
| Local GPU | Host Ollama (Metal / Vulkan / ROCm / CUDA). Not VS Code. |
| Secrets | `.env`: per-provider primary / personal / enterprise keys + `LITELLM_MASTER_KEY` ([MULTI-KEYS.md](./MULTI-KEYS.md)) |
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

## 5. Continuity workflows

### 5.1 Session / daily / weekly limits without product hop

| Condition | Response |
|-----------|----------|
| Primary cloud maker unavailable, 429, or unpinned | Matrix + combo/pipeline fallbacks select next live model |
| Other cloud keys still valid | Work continues under the **same** façade URL and session hygiene |
| No cloud headroom | Prefer `tier: local` / `private` / cheapest local aliases via Ollama |
| Context bloated after hours of agents | `/done` → `/compact` or `/clear` (archive first; do not re-paste into a new vendor app) |

Client stays on:

```text
base_url = http://127.0.0.1:4000/v1
api_key  = <LITELLM_MASTER_KEY>
model    = <one alias or combo-resolved alias>
```

Provider subscription caps are enforced by the provider. Aether’s job is **not** to invent quota APIs; it is to keep the **work surface and memory continuous** while engines rotate by policy and live discover.

### 5.2 Multi-stage pipeline without re-briefing

| Stage role | Typical assignment |
|------------|-------------------|
| researcher | High reason / long context |
| critic | Different maker; gate/ack |
| builder | Code; may parallelize workers |
| tester | Cheap / local |

Encode once in pipeline YAML or `/graph`. Plan with Hub; execute via gateway. On complete: slash hygiene. Artifacts remain searchable in agent memory.

### 5.3 Private local research segment

| Requirement | Mechanism |
|-------------|-----------|
| No egress to cloud for a project slice | `POST /api/privacy` + local model pins |
| No leak into shared session/xref pools | Private vault namespaces; redacted logs |
| Finish offline when subscriptions empty | Host Ollama on Metal / ROCm CUs / CUDA |
| Leave isolation | Explicit `POST /api/privacy/release` only |

Same IDE window; different policy for the sensitive unit of work. See [PRIVATE-MODE.md](./PRIVATE-MODE.md).

---

## 6. Daily loop

```text
Start stack
  → open project → chat via gateway alias
  → multi-hour agents: failover cloud → cloud → local as needed
  → optional private local segment for sensitive research
  → structured pipeline/graph when the job is multi-stage
  → task complete: /done all
  → /compact or /clear
  → next unit (lean context; memory searchable)
```

---

## 7. Hard constraints

| Constraint | Fact |
|------------|------|
| GPU for weights | Host Ollama (or cloud). Not VS Code. Not LiteLLM container by default. |
| Façade quality | Bound by imported trees, live discover, and present keys |
| Multi-agent cost | Fan-out can exceed single-call tokens; token saver + slash hygiene apply |
| Provider caps | Daily/weekly/session limits are provider-side; Aether rotates engines by policy + availability |
| Multi-account keys | Personal + enterprise keys coexist; select via `*-personal` / `*-enterprise` aliases |
| Private vault | No auto-merge into common memory on release |
| Node canvas | Native graph under this repo's PolyForm Noncommercial 1.0.0 license. No third-party node engine is vendored in this repo. |

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
