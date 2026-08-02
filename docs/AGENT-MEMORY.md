# Agent memory

Redis backs LiteLLM cache and Hub session + vector stores.

| Component | Role |
|-----------|------|
| Redis `:6379` | Persistence, hub data, LiteLLM cache |
| aether-hub `:8766` | Session and vector HTTP API |
| Embeddings | Ollama `nomic-embed-text` when present; hash fallback otherwise |

---

## Architecture

```text
Agents / IDE / scripts
        │
        ▼
  aether-hub :8766
     ├─ sessions
     └─ vectors (JSON + embedding[])
        │
        ▼
     Redis :6379
        ▲
        │ cache
     LiteLLM :4000
```

---

## Session memory

```bash
curl -s -X POST http://127.0.0.1:8766/api/memory/sessions/demo/messages \
  -H "Content-Type: application/json" \
  -d '{"role":"user","content":"LiteLLM listens on port 4000","index":true}'

curl -s "http://127.0.0.1:8766/api/memory/sessions/demo?limit=20"
```

Key: `aether:mem:session:{id}` (Redis list, default TTL 7 days).

---

## Vector memory

```bash
curl -s -X POST http://127.0.0.1:8766/api/memory/vectors \
  -H "Content-Type: application/json" \
  -d '{"namespace":"project-alpha","text":"Auth uses the generated local gateway key","meta":{"kind":"security"}}'

curl -s -X POST http://127.0.0.1:8766/api/memory/search \
  -H "Content-Type: application/json" \
  -d '{"namespace":"project-alpha","query":"API key policy","top_k":5}'
```

Cosine similarity runs in-process over Redis-stored vectors. Scale: lab (thousands of chunks).

### Embeddings

```bash
ollama pull nomic-embed-text
# AETHER_EMBED_MODEL=nomic-embed-text
# AETHER_HASH_EMBED=1  # force hash, no network
```

Without Ollama embeddings, hub uses deterministic hash vectors (weaker recall).

---

## Memory layers (node view)

The **Memory** node on the canvas (`/graph`) has **three tiers**. Pick a tier + `search` or `store` so context is scoped correctly across nodes, projects, and research.

### Three Memory-node tiers

| Tier (`scope`) | Who can see it | Resolved namespace | Use when |
|----------------|----------------|--------------------|----------|
| **1. Tree** | Other nodes in **this** decision-tree (same graph / node sequence) | `tree:{graph_id}` | Record outputs of the current sequence; hand facts between nodes on this canvas |
| **2. Project** | Other **node graphs** under the same project | `project:{project_id}` | Share decisions/artifacts across decision trees in one project |
| **3. Global** | **Pan-project** (all projects on this hub) | `global` | Research and concepts that span multiple projects |

```text
                    ┌─────────────────────────────────────┐
  Tier 3 Global     │  global  (pan-project research)     │
                    └─────────────────▲───────────────────┘
                                      │ promote when useful
                    ┌─────────────────┴───────────────────┐
  Tier 2 Project    │  project:{project_id}               │
                    │  all decision trees in the project  │
                    └─────────────────▲───────────────────┘
                                      │ promote when useful
                    ┌─────────────────┴───────────────────┐
  Tier 1 Tree       │  tree:{graph_id}                    │
                    │  this canvas / node sequence only   │
                    └─────────────────────────────────────┘
```

| Action | Effect |
|--------|--------|
| `search` | Load hits from that tier into the flow for downstream nodes |
| `store` | Write sequence output / notes into that tier’s pool |

Inspector fields on a Memory node:

| Field | Default | Meaning |
|-------|---------|---------|
| `scope` | `tree` | Tier: `tree` · `project` · `global` |
| `action` | `search` | `search` or `store` |
| `project_id` | graph `project_id` / `service_id` | Required for project tier when the graph is not already bound |
| `namespace` | _(resolved)_ | Optional override; leave empty to use the tier map above |

Wire Memory where context should enter or leave the flow. Auto-connect places it after agents and before slash hygiene:

```text
goal → master → analyser → worker → tester → memory → slash → output
```

**Pipeline export:** Memory nodes are not LLM stages. `POST /api/graphs/to-pipeline` emits them as `memory_ops[]` with resolved `scope`, `action`, and `namespace`. Agent stages come from master/worker/analyser/tester; slash commands land on `on_complete.slash`.

Typical placements:

| Placement | Tier + action |
|-----------|----------------|
| Early (after goal / before workers) | `tree` or `project` + `search` — load context for this run |
| Between workers | `tree` + `store` then later `search` — pass sequence output inside the graph |
| Late (after tester) | `project` + `store` — publish durable project knowledge |
| Research spanning repos | `global` + `store` / `search` |

### Supporting layers (not Memory-node tiers)

These still exist beside the three Memory tiers:

| Layer | Surface | Role |
|-------|---------|------|
| **Working session** | Implicit (Redis `aether:mem:session:{id}`) | Hot chat / agent turns for the active unit (TTL 7d) |
| **Conversation archive** | **Command** (slash) node: `/save`, `/clear`, `/compact` | Full history → `archive:{session}` + sticky `conversation-index` |
| **Cross-project xref** | `/api/xref` (not a palette node) | Scan LLM-native folders across projects; optional `prompt_block` pull — [CROSS-MEMORY.md](./CROSS-MEMORY.md) |
| **Private vault** | Private mode remaps namespaces | Tree/project/global writes leave the common pool — [PRIVATE-MODE.md](./PRIVATE-MODE.md) |

### Slash node vs Memory node

| Node | What it does |
|------|----------------|
| **Memory** | Tiered vector **search** / **store** (`tree` · `project` · `global`) |
| **Command** (slash) | Session hygiene: `/done` → archive → `/clear` or `/compact` |

Slash archives the **working session** (full transcript). Memory tiers hold **curated** sequence/project/global facts. Private sessions archive to vault-only namespaces and do not sticky into `conversation-index`.

### Layer flow on the canvas

```text
  Working session (hot turns)
        │
        ▼
  Memory (search) ──► tree / project / global pool  ──► context for later nodes
  Memory (store)  ◄── sequence output ──► same tier pool
        │
        ▼
  Slash  ──/save|/clear|/compact──► archive + conversation-index
        │
        ▼
  next unit: lean session; Memory search on the right tier if old work matters
```

### Namespace map

| Namespace pattern | Layer |
|-------------------|--------|
| `tree:{graph_id}` | Memory tier 1 — this decision tree |
| `project:{project_id}` | Memory tier 2 — project pool |
| `global` | Memory tier 3 — pan-project research |
| `archive:{session_id}` | Slash full conversation archive |
| `conversation-index` | Slash sticky recall breadcrumbs |
| `xref` | Cross-project folder index (separate from `global`) |
| `private:{project_id}:…` | Vault only (private mode) |

---

## LiteLLM Redis cache

LiteLLM response caching is disabled by default. Prompts and completions must not
be copied into Redis persistence without an explicit retention decision.

The same Redis instance still contains deliberate Aether Hub session/vector
memory. Treat its Docker volume and backups as user data, not disposable cache.

---

## Security constraints

| Rule | Fact |
|------|------|
| Default bind | Localhost lab trust model |
| Exposure | Do not publish `:8766` or `:6379` publicly |
| Content | Vectors store whatever text is upserted — treat as sensitive |
| LiteLLM cache | Disabled by default; opt-in requires a retention policy |
| Shared host | Put Hub behind authenticated reverse proxy |
| Private mode | Isolated vault; no common pool — [PRIVATE-MODE.md](./PRIVATE-MODE.md) |

---

## Related

- [NODE-GRAPH.md](./NODE-GRAPH.md) — canvas UI, Memory + slash node types  
- [SLASH-COMMANDS.md](./SLASH-COMMANDS.md) — archive then clear  
- [CROSS-MEMORY.md](./CROSS-MEMORY.md) — multi-project xref layer  
- [PRIVATE-MODE.md](./PRIVATE-MODE.md) — vault isolation  
- [CAPABILITY-MATRIX.md](./CAPABILITY-MATRIX.md)  
- [aether-hub/](../aether-hub/)  
