# Node-based pipeline canvas

Visual FX–style **node graph** for AetherStack agent/pipeline scripting: place **Master / Worker / Analyser (critic)** nodes, set tiers and makers, draw wires — or let Aether **auto-connect** using best practices.

| | |
|--|--|
| Canvas UI | http://127.0.0.1:8766/graph |
| Graph schema | `aetherstack.graph.v1` |
| API | `/api/graphs` |

---

## ActionForge license (why we did not vendor it)

[Actionforge](https://github.com/actionforge) is a polished node system for CI/CD. Its public repos use license **“Other” / Actionforge EULA** — free for solo/non-profit, **commercial use requires their permission**.  

AetherStack is **MIT**. **We do not embed or redistribute ActionForge code** in this repo. Optional future: users may run ActionForge side-by-side for GitHub Actions; Aether’s LLM graph remains native.

---

## Node types

| Type | Role in graph | Settings |
|------|----------------|----------|
| **goal** | Entry prompt / event | text |
| **master** | Orchestrator (mastermind) | tier, maker, model, max_cost, strategy |
| **worker** | Bulk implementer | same + parallel |
| **analyser** | Critic / ack / QA gate | same + `gate` |
| **tester** | Test stage | prefer cheap/local |
| **memory** | Save/search context | namespace |
| **slash** | Hygiene node | `/done`, `/clear`, `/compact` |
| **output** | Sink / export | — |

---

## Edges

- **Manual:** drag from output port → input port on canvas  
- **Auto:** `POST /api/graphs/auto-connect` or UI **Auto layout**  
  Best practices:
  1. `goal` → `master`  
  2. `master` → `analyser` (critique gate)  
  3. `analyser` → `worker` (only if ack path — modeled as sequential wire)  
  4. `worker` → `tester`  
  5. `tester` → `slash` (`/done all` + `/compact`) → `output`  
  6. Prefer **different makers** on master vs analyser when both cloud  

---

## Graph JSON (export/import)

```json
{
  "schema": "aetherstack.graph.v1",
  "id": "my-graph",
  "nodes": [
    {"id": "n1", "type": "goal", "x": 40, "y": 120, "data": {"text": "Add OAuth"}},
    {"id": "n2", "type": "master", "x": 220, "y": 100, "data": {"role": "mastermind", "tier": null, "maker": "anthropic", "model": "claude-sonnet-4", "max_cost": "high"}},
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

Convert to pipeline: `POST /api/graphs/to-pipeline`  
Load pipeline as graph: `POST /api/graphs/from-pipeline` `{ "pipeline_id": "research-code-test" }`

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

- Linear pipeline scripts: [PIPELINES.md](./PIPELINES.md)  
- Combos: [combos/README.md](../combos/README.md)  
- Slash hygiene: [SLASH-COMMANDS.md](./SLASH-COMMANDS.md)  
