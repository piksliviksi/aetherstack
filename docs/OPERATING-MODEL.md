# Operating model

How AetherStack works, in one page. Read this before any other doc.

## The idea

You already pay for several coding models. Each one stops when its session,
daily, or weekly cap is reached, and each one forgets everything the others did.
Today you handle that by hand: open the next product, paste the old chat, re-state
the goal, re-pick the files, and hope the new model catches up.

AetherStack removes that step. You talk to **one** model at a time, directly. When
that model runs out of headroom, the next one in your chain picks up the same work
from the shared memory pool — without you re-briefing it. When no cloud model is
left, a local model on your own hardware continues the same way.

**Two principles carry everything else:**

1. **Pass-through.** In Auto mode AetherStack does not blend, summarise, or
   re-write the model's answer. Your prompt goes to the selected model, and that
   model's answer comes back verbatim. Working in AetherStack should feel exactly
   like working in Codex, Claude Code, or Grok directly.
2. **One memory pool.** Every turn is written to shared memory as it happens. Any
   model that takes over reads that pool and resumes from where the last one
   stopped.

Pass-through is what makes the product feel native. Shared memory is what makes
the handoff invisible. Neither works without the other.

---

## Two tiers

AetherStack runs work at exactly two levels. Everything in this repo is one or
the other.

| | **Tier 1 — Auto** | **Tier 2 — Model trees** |
|---|---|---|
| Shape | One model answers | Several models in a defined sequence |
| Feels like | Native Codex / Claude / Grok chat | A team working one task |
| Who picks the model | The failover chain | The graph you drew |
| Output | The model's answer, unmodified | A synthesised result |
| Memory | Shared pool | Same shared pool |
| Use it for | Everyday coding and chat | Work that genuinely needs a second opinion |

**Tier 1 is the default and the common case.** Tier 2 is opt-in.

### Tier 1 — Auto mode

One model. Direct. AetherStack sits between you and it only to supply memory and
to switch engines when one runs dry.

```text
you → [ memory pool ] → selected model → you
            ↑ every turn written back
```

When the active model reports a session, quota, or availability failure,
AetherStack moves to the next model in the chain and replays the same request
with the memory block attached. The new model reads what the previous one did and
continues. You are not asked to re-explain anything.

The chain ends at a local model, so work never hard-stops while your machine is
on.

Implementation: `execute_auto` in [`aether-hub/services.py`](../aether-hub/services.py).

### Tier 2 — Model trees

A tree (or *decision tree* — the node canvas at `/graph`) runs several models in
order on one task: one writes code, another reviews it, a local model does
research that shouldn't leave the machine. This is what agents are inside a single
product, except each node can be a **different** model from a **different**
vendor.

Every node reads and writes the same memory pool as Tier 1, so a tree can pick up
work an Auto-mode session started, and vice versa.

| Piece | Where |
|-------|-------|
| Canvas draws, saves, validates, compiles to a pipeline | `POST /api/graphs/plan`, `to-pipeline` |
| Graph **runs** — stages in topological order, each output threaded into its downstream stages | `POST /api/graphs/run` → `execute_graph`, [`graph_exec.py`](../aether-hub/graph_exec.py) |
| Memory nodes read (`search`) and write (`store`) the shared pool | `memory_ops`, executed by `_memory_reads` / `_memory_writes` |
| Every run appends to the session pool Auto mode reads | `MemoryStore.append_message` |
| Preset multi-agent services | `execute_service` → `_store_handoff_context`, [`services.py`](../aether-hub/services.py) |

A stage failure is recorded in `steps`. Independent branches may continue, while
dependent stages are skipped when they have no successful upstream output. If no
terminal stage feeding the Output node succeeds, the run fails with node-level
diagnostics instead of presenting an incomplete result as success.

Canvas and format: [NODE-GRAPH.md](./NODE-GRAPH.md). Scripted equivalents:
[PIPELINES.md](./PIPELINES.md), [combos/](../combos/).

---

## What must never happen in Auto mode

Auto mode is a pipe. These are the ways a pipe leaks, and each one is a bug:

| Failure | Why it breaks the product |
|---------|---------------------------|
| Multi-agent scaffolding reaching the model | The model sees an orchestration transcript instead of your question, and answers the scaffolding |
| Blending output from a second model | The answer stops being the model you chose |
| Instructions telling the model to conceal its process | Well-aligned coding models correctly refuse this, and say so instead of answering |

A model that answers a question about its own prompt instead of your task means
the pass-through was broken upstream — not that the model misbehaved.

---

## First run

On first launch AetherStack inspects the machine and finishes its own setup.
One endpoint drives the whole sequence: `GET|POST /api/first-run`.

| Step | What it does | Backed by |
|------|--------------|-----------|
| 1. Scan | Find installed model CLIs, API keys, Docker, Ollama, GPU and VRAM | `GET /api/discover` |
| 2. Install | Fetch the missing pieces — container runtime, images, a local model sized to the hardware | [AUTO-INSTALL.md](./AUTO-INSTALL.md) |
| 3. Connect | Register each model AetherStack can reach, by whichever access you already have — CLI subscription or API key | Host CLI bridge, [GATEWAY.md](./GATEWAY.md) |
| 4. Order | Your fallback priority, e.g. `codex → claude → grok → local` | `POST /api/auto/chain` |
| 5. Ready | Auto mode answers from the first model in that chain | — |

`GET /api/first-run` reports each step as done or pending plus the next step to
take. `POST /api/first-run` runs the sequence.

Named service runs execute independent workers concurrently, then feed their
evidence into the reviewer and final answer in dependency order. The returned
`timings_ms` map reports lead, workers, review, answering, and total latency.
Partial worker/reviewer failures set `degraded` and `degraded_reasons`; HTTP and
stream failures carry stable `code` and `request_id` fields. `/api/health`
includes `background_sync` heartbeat and Redis publication state.

**The consent rule.** Scanning and planning always run — they change nothing.
Nothing is *installed* until you pass `confirm: true`:

```bash
# Safe: reports what is missing, installs nothing
curl -s -X POST http://127.0.0.1:8766/api/first-run -H "Content-Type: application/json" -d '{}'

# Installs the safe actions from that plan
curl -s -X POST http://127.0.0.1:8766/api/first-run \
  -H "Content-Type: application/json" -d '{"confirm":true}'
```

"Automatic setup" means you answer once and the rest happens — not that software
appears on your machine silently. `{"reset": true}` reopens the flow.

### Choosing the fallback order

```bash
curl -s -X POST http://127.0.0.1:8766/api/auto/chain \
  -H "Content-Type: application/json" \
  -d '{"order":["codex-cli","claude-cli","grok-cli","local-default"]}'
```

Aliases may name host CLIs or local models, so the whole chain down to local
hardware is one ordered list. Unavailable entries are skipped without disturbing
the rest of the order. An empty list restores the default. Read the active order
back from `GET /api/auto/chain` (`priority_order`, `priority_default`).

---

## Memory

One pool, written continuously, read by whichever model runs next.

| Holds | Detail |
|-------|--------|
| Session transcript | Every Auto and tree turn, as it happens |
| Vector recall | Older decisions retrieved by relevance |
| Handoff context | What the previous model was doing when it stopped |

The pool is trimmed to a byte budget before it is sent, newest first. Detail:
[AGENT-MEMORY.md](./AGENT-MEMORY.md), [CROSS-MEMORY.md](./CROSS-MEMORY.md).

Private work is excluded from the shared pool entirely — see
[PRIVATE-MODE.md](./PRIVATE-MODE.md).

---

## Surfaces

The same engine behind every window.

| Surface | Role |
|---------|------|
| VS Code — AetherStack Chat | Primary. Tier 1 and Tier 2. |
| Hub `:8766` | Operator console: discover, chain, graphs, memory |
| Gateway `:4000` | OpenAI-compatible endpoint for any other client |
| Open WebUI `:3000` | Optional browser surface |

Any OpenAI-compatible client points at one base URL, one key, one model id:

```text
base_url = http://127.0.0.1:4000/v1
api_key  = <LITELLM_MASTER_KEY>
model    = <one alias>
```

---

## Cost control

| Control | Effect |
|---------|--------|
| `token_saver: true` | Prefer cheap/local; compress long context |
| Node `max_cost` | Cap a role's cost band |
| `tier: local` | Pin a node to Ollama |
| Memory context budget | Cap KiB of memory sent per turn |
| `/done` → `/clear` | Archive the unit, reset the working session |

Provider billing stays provider-side. AetherStack enforces routing policy only —
it does not and cannot read your remaining quota from a vendor.

---

## Hard constraints

| Constraint | Fact |
|------------|------|
| GPU | Host Ollama owns the GPU. Not VS Code, not the LiteLLM container. |
| Provider caps | Enforced by the provider. AetherStack reacts to failures; it cannot predict them. |
| Tier 2 cost | A tree multiplies token spend by its node count. |
| Private vault | Never auto-merged into the shared pool. |
| Docker | An OS prerequisite. Not silently installed. |
| Node canvas | Native to this repo, PolyForm Noncommercial 1.0.0. No third-party node engine vendored. |

---

## Related

| Doc | Topic |
|-----|--------|
| [README.md](./README.md) | Documentation index |
| [QUICKSTART.md](./QUICKSTART.md) | Install, ports, IDE |
| [AUTO-INSTALL.md](./AUTO-INSTALL.md) | Scan and bootstrap |
| [NODE-GRAPH.md](./NODE-GRAPH.md) | Tier 2 canvas |
| [AGENT-MEMORY.md](./AGENT-MEMORY.md) | Memory pool |
| [AGENT-MODES.md](./AGENT-MODES.md) | Tier 2 execution modes |
| [GATEWAY.md](./GATEWAY.md) | Aliases and keys |
| [PRIVATE-MODE.md](./PRIVATE-MODE.md) | Local-only isolation |
| [SECURITY-NOTES.md](./SECURITY-NOTES.md) | Findings and mitigations |
