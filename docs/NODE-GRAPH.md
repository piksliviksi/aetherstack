# Node graph canvas

Visual node graph for agent/pipeline scripting. Place **Master / Worker / Analyser / Tester** nodes, set tier and maker, connect edges. Auto-connect applies a fixed best-practice layout.

| | |
|--|--|
| Canvas UI | http://127.0.0.1:8766/graph |
| Schema | `aetherstack.graph.v1` |
| API | `/api/graphs` |
| License | Native implementation, PolyForm Noncommercial 1.0.0 with this repo |

**Not in tree:** third-party node engines (e.g. ActionForge). This canvas is independent.

---

## Node types

| Type | Role | Settings |
|------|------|----------|
| `goal` | Entry prompt / event | text |
| `master` | Orchestrator | tier, maker, model, max_cost, strategy |
| `worker` | Implementation | same + parallel |
| `analyser` | Critic / QA gate | same + `gate` |
| `tester` | Tests | prefer cheap/local |
| `private` | **Local GPU private** branch | `input_folder`, `input_globs` (PDF/text), forced `tier: local`, vault on |
| `memory` | Three-tier context pool | `scope` (tree · project · global), `action` (search · store), optional `project_id` / `namespace` |
| `slash` | Hygiene | `/done`, `/clear`, `/compact` |
| `output` | Sink | — |

### Private node (local GPU + folder corpus)

Drop **Private** from the palette into the decision tree.

| Setting | Meaning |
|---------|---------|
| `input_folder` | Host/mount path with source documents |
| `input_globs` | Default `*.pdf, *.txt, *.md, …` |
| `gpu_only` | Prefer GPU-resident local models |
| `private_vault` | Keep session/vector writes in private vault namespaces |
| `model` | Local alias (default `local-default`) — **not** cloud makers |

Pipeline export sets `role: private_local`, `select.tier: local`, `private: true`, and attaches folder + globs. See [PRIVATE-MODE.md](./PRIVATE-MODE.md) for vault rules.

### Memory node tiers

| `scope` | Namespace | Visibility |
|---------|-----------|------------|
| `tree` (default) | `tree:{graph_id}` | Other nodes in **this** decision-tree / canvas sequence |
| `project` | `project:{project_id}` | Other node graphs in the same project |
| `global` | `global` | Pan-project pool — research that spans projects |

`action: search` loads from the tier; `action: store` records sequence output into it. Full detail: [AGENT-MEMORY.md](./AGENT-MEMORY.md#memory-layers-node-view).

---

## Edges (multi-wire)

| Method | How |
|--------|-----|
| Manual | Drag **out** port → **in** port on another node |
| Fan-out | One node → many targets (several out wires) |
| Fan-in | Many sources → one node (several in wires) |
| Auto | `POST /api/graphs/auto-connect` or UI **Auto-connect** |
| Delete | Click edge (highlight) then **Delete** / Backspace |

Every node type allows **unlimited** fan-in and fan-out (`ports_in` / `ports_out` = many).  
Canvas spreads multiple wires along the port side so branches stay readable. Node cards show `in N · out M`.

| Edge `kind` | Meaning | Stroke |
|-------------|---------|--------|
| `data` | Forward flow (default) | Solid grey |
| `feedback` | Recursive / back-edge (loop) | Dashed amber + ↻ |

Duplicate same-direction pairs (`A→B` twice) are rejected; different pairs always stack.

### Recursive mode

Toolbar: **Recursive mode** + **iters** (`max_iterations`, default 3).

| Off (default) | On |
|---------------|-----|
| Cycles blocked | Cycles allowed as `feedback` edges |
| Output has no out port | Output can wire **back** into earlier nodes (e.g. master, worker, goal) |
| Goal has no in port | Goal may receive feedback to re-enter the tree |

Examples:

```text
# Fan-out / fan-in (always)
master ──► worker-1 ──► analyser
       └─► worker-2 ─┘

# Recursive feedback (recursive mode on)
goal → master → worker → output
              ▲            │
              └──── feedback ──┘
```

Pipeline export:

- Stages ordered by **data** edges only (Kahn multi-parent topo)
- `feedback_edges[]` listed separately with `recursive` + `max_iterations`
- Each stage carries `inputs_from[]` / `outputs_to[]` for multi-wire topology

Auto-connect order (linear baseline; multi-wire and loops are manual):

1. `goal` → `master`  
2. `master` → `analyser`  
3. `analyser` → `worker`  
4. `worker` → `tester`  
5. `tester` → `private` (optional local GPU + PDF/text folder)  
6. `private` / `tester` → `memory` (tree / project / global)  
7. `memory` → `slash` (`/done all` + `/compact`) → `output`  

When master and analyser both use cloud, assign different makers when both are available.

---

## Graph JSON

```json
{
  "schema": "aetherstack.graph.v1",
  "id": "my-graph",
  "recursive": false,
  "max_iterations": 3,
  "nodes": [
    {"id": "n1", "type": "goal", "x": 40, "y": 120, "data": {"text": "Add OAuth"}},
    {"id": "n2", "type": "master", "x": 220, "y": 100, "data": {"role": "mastermind", "maker": "anthropic", "model": "claude-sonnet-4", "max_cost": "high"}},
    {"id": "n3", "type": "analyser", "x": 420, "y": 100, "data": {"role": "critic", "maker": "openai", "gate": true}},
    {"id": "n4", "type": "worker", "x": 620, "y": 80, "data": {"role": "builder", "strategy": "cheapest", "tier": "local", "parallel": 2}},
    {"id": "n5", "type": "tester", "x": 820, "y": 100, "data": {"role": "tester", "strategy": "cheapest"}},
    {"id": "n5b", "type": "memory", "x": 920, "y": 100, "data": {"scope": "tree", "action": "store"}},
    {"id": "n6", "type": "slash", "x": 1080, "y": 100, "data": {"commands": ["/done all", "/compact"]}},
    {"id": "n7", "type": "output", "x": 1260, "y": 120, "data": {}}
  ],
  "edges": [
    {"id": "e1", "from": "n1", "to": "n2"},
    {"id": "e2", "from": "n2", "to": "n3"},
    {"id": "e3", "from": "n3", "to": "n4"},
    {"id": "e4", "from": "n4", "to": "n5"},
    {"id": "e5", "from": "n5", "to": "n5b"},
    {"id": "e6", "from": "n5b", "to": "n6"},
    {"id": "e7", "from": "n6", "to": "n7"}
  ]
}
```

| Operation | Endpoint |
|-----------|----------|
| Graph → pipeline | `POST /api/graphs/to-pipeline` |
| Pipeline → graph | `POST /api/graphs/from-pipeline` `{"pipeline_id":"research-code-test"}` |

---

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/graph` | Canvas UI |
| GET | `/api/graphs` | List saved graphs |
| POST | `/api/graphs` | Save graph body |
| GET | `/api/graphs/{id}` | Load |
| POST | `/api/graphs/auto-connect` | Best-practice edges + layout |
| POST | `/api/graphs/to-pipeline` | Graph → pipeline script |
| POST | `/api/graphs/from-pipeline` | Pipeline → graph |
| POST | `/api/graphs/{id}/plan` | Resolve models for nodes |
| POST | `/api/graphs/run` | **Execute the tree** — stages in order, Memory nodes read/write the shared pool |

### Running a tree

```bash
curl -s -X POST http://127.0.0.1:8766/api/graphs/run \
  -H "Content-Type: application/json" \
  -d '{"graph_id":"my-tree","goal":"refactor the auth module","session_id":"sess-1"}'
```

Pass `graph` with a full graph body instead of `graph_id` to run an unsaved
canvas. Each stage's output is threaded into its downstream stages. A stage that
fails is recorded in `steps` with its error and the run continues, so one
rate-limited model does not cost the whole tree.

Because the run appends to `session_id` in the shared pool, Auto mode on that
same session resumes from where the tree stopped — and a tree can pick up work an
Auto session started.

---

## Related

- [AGENT-MEMORY.md](./AGENT-MEMORY.md) — Memory-node tiers (tree / project / global)  
- [PIPELINES.md](./PIPELINES.md)  
- [combos/README.md](../combos/README.md)  
- [SLASH-COMMANDS.md](./SLASH-COMMANDS.md)  
