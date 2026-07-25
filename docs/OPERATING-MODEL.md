# How AetherStack operates

This is the **modus operandi**: set up once, work in one surface, let the stack orchestrate many models under a single façade.

## Promise

> **Outside:** one chat window, one model id, one API key — same feeling as talking to Grok or Claude.  
> **Inside:** flexible multi-LLM routing, graphs, budgets, GPU-local workers, and memory hygiene.

---

## 1. Configure once

| Step | Action |
|------|--------|
| Stack | `start.bat` / `./start.sh` (Docker: WebUI, LiteLLM, Redis, Hub) |
| Local GPU | Host Ollama (Metal / ROCm / CUDA) — not VS Code itself |
| Secrets | `.env` cloud keys + `LITELLM_MASTER_KEY` |
| Discover | Hub `/api/discover` or `scripts/scan-system.*` |
| Import trees | Combos, pipelines, or node graphs (GitHub / email / canvas export) |
| Limits | Token saver; stage `max_cost` / `tier`; avoid publishing default keys |
| IDE | Continue (or similar) → `http://127.0.0.1:4000/v1` + master key + **one** model alias |

You should not re-pick Anthropic vs OpenAI vs local in the IDE for every prompt. Policy lives in Aether.

---

## 2. Single façade

Any OpenAI-compatible client only needs:

```text
base_url = http://127.0.0.1:4000/v1
api_key  = <LITELLM_MASTER_KEY>
model    = <one alias, e.g. local-default or claude-sonnet-4>
```

| Surface | Role |
|---------|------|
| **VS Code + Continue** | Primary “one window” for coding |
| **Open WebUI** | Same gateway in the browser |
| **Aether Hub** | Operator console — not required for every keystroke |

Hub multi-agent / pipeline execution can be driven by operator actions or future automatic hooks; the **user-facing** model remains one gateway id.

---

## 3. Decision trees under the hood

| Artifact | What it encodes |
|----------|-----------------|
| **Combos** | Quick multi-agent role pins or single-tier picks |
| **Pipelines** | Ordered stages: research → critique/ack → build → test |
| **Node graph** (`/graph`) | Visual FX–style canvas: Master / Analyser / Worker / Tester + wires |
| **Capability matrix** | What each model is good for; live availability |
| **Token saver** | Prefer cheap/local; cap tokens; compress prompts |

Import from [combos/export](../combos/export), [pipelines/catalog](../pipelines/catalog), or draw on the canvas. Export and share the same files.

---

## 4. Limits (spend & tier)

| Control | Effect |
|---------|--------|
| `token_saver: true` | Bias bulk work to cheap/local; truncate long context |
| Stage / node `max_cost` | Cap how expensive a role may be (`low` … `very_high`) |
| `tier: local` | Keep stage on Ollama (Metal/ROCm/CUDA) |
| Maker pins | e.g. critic always Anthropic, workers local |
| Pipeline `hw_weight` | Document / rank GPU heaviness |
| `/clear` after `/done` | Stop unbounded context growth |

Exact dollar billing is still provider-side; Aether enforces **routing policy** so spend and hardware use follow your trees.

---

## 5. Daily loop

```text
Chat in VS Code (one model façade)
        │
        ▼
  Optional: run pipeline/graph for structured work
        │
        ▼
  Agents finish → /done all → /compact or /clear
        │
        ▼
  Memory holds archives; next messages stay short
```

---

## 6. What not to expect

- VS Code does **not** drive the GPU for weights; Ollama (or cloud) does.  
- The façade is only as good as your **imported trees** and **keys**.  
- Multi-agent fan-out may use more total tokens than a single call — use token saver and clear when done.  
- ActionForge is **not** bundled (EULA); Aether’s node canvas is native.

---

## Related docs

| Doc | Topic |
|-----|--------|
| [README.md](./README.md) | Full documentation index |
| [QUICKSTART.md](./QUICKSTART.md) | Install, ports, IDE wire-up |
| [GATEWAY.md](./GATEWAY.md) | LiteLLM aliases & keys |
| [VSCODE-EXTENSION.md](./VSCODE-EXTENSION.md) | IDE install & commands |
| [PIPELINES.md](./PIPELINES.md) | Stage scripts + voting |
| [NODE-GRAPH.md](./NODE-GRAPH.md) | Visual canvas |
| [SLASH-COMMANDS.md](./SLASH-COMMANDS.md) | `/clear` memory hygiene |
| [CROSS-MEMORY.md](./CROSS-MEMORY.md) | Multi-project session/code/research pull |
| [AGENT-MODES.md](./AGENT-MODES.md) | inline vs multi-agent |
| [AMD-COMPUTE.md](./AMD-COMPUTE.md) | Radeon CUs |
| [TUTORIAL-MACOS.md](./TUTORIAL-MACOS.md) | Metal on Apple Silicon |
