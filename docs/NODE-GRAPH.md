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
| `memory` | Save/search context | namespace |
| `slash` | Hygiene | `/done`, `/clear`, `/compact` |
| `output` | Sink | — |

---

## Edges

| Method | How |
|--------|-----|
| Manual | Drag output port → input port |
| Auto | `POST /api/graphs/auto-connect` or UI **Auto layout** |

Auto-connect order:

1. `goal` → `master`  
2. `master` → `analyser`  
3. `analyser` → `worker`  
4. `worker` → `tester`  
5. `tester` → `slash` (`/done all` + `/compact`) → `output`  

When master and analyser both use cloud, assign different makers when both are available.

---

## Graph JSON

```json
{
  "schema": "aetherstack.graph.v1",
  "id": "my-graph",
  "nodes": [
    {"id": "n1", "type": "goal", "x": 40, "y": 120, "data": {"text": "Add OAuth"}},
    {"id": "n2", "type": "master", "x": 220, "y": 100, "data": {"role": "mastermind", "maker": "anthropic", "model": "claude-sonnet-4", "max_cost": "high"}},
    {"id": "n3", "type": "analyser", "x": 420, "y": 100, "data": {"role": "critic", "maker": "openai", "gate": true}},
    {"id": "n4", "type": "worker", "x": 620, "y": 80, "data": {"role": "builder", "strategy": "cheapest", "tier": "local", "parallel": 2}},
    {"id": "n5", "type": "tester", "x": 820, "y": 100, "data": {"role": "tester", "strategy": "cheapest"}},
    {"id": "n6", "type": "slash", "x": 1000, "y": 100, "data": {"commands": ["/done all", "/compact"]}},
    {"id": "n7", "type": "output", "x": 1180, "y": 120, "data": {}}
  ],
  "edges": [
    {"id": "e1", "from": "n1", "to": "n2"},
    {"id": "e2", "from": "n2", "to": "n3"},
    {"id": "e3", "from": "n3", "to": "n4"},
    {"id": "e4", "from": "n4", "to": "n5"},
    {"id": "e5", "from": "n5", "to": "n6"},
    {"id": "e6", "from": "n6", "to": "n7"}
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

---

## Related

- [PIPELINES.md](./PIPELINES.md)  
- [combos/README.md](../combos/README.md)  
- [SLASH-COMMANDS.md](./SLASH-COMMANDS.md)  
