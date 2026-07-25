# Pipeline scripts — multi-stage LLM workflows

Script **which tier/cost models** run **research**, **critique/ack**, **implementation**, and **testing**.  
Share scripts via **upload/download** (GitHub, email). **Vote** on quality and hardware weight.

| | |
|--|--|
| Schema | `aetherstack.pipeline.v1` |
| Catalog | [`pipelines/catalog/`](../pipelines/catalog/) |
| User imports | `pipelines/user/` |
| Votes | `pipelines/votes.json` (local ranking) |
| API | http://127.0.0.1:8766/api/pipelines |

---

## Stage roles

| Stage role | Typical job | Cost bias |
|------------|-------------|-----------|
| `researcher` | Survey, plan, constraints | high / cloud |
| `critic` | Ack / adversarial review (gate) | high, **different maker** |
| `builder` | Write code / patches | medium |
| `tester` | Tests, smoke | low / local |

Each stage sets:

- `prefer_models` / `prefer_makers`  
- `select.strategy` (`best_score` | `cheapest`)  
- `select.max_cost`, `tier`, `maker`  
- `needs` capability tags  
- `parallel`, `gate`, `ack`  

---

## Example script (YAML)

See [`pipelines/catalog/research-code-test.aether-pipeline.yaml`](../pipelines/catalog/research-code-test.aether-pipeline.yaml).

```yaml
schema: aetherstack.pipeline.v1
id: my-loop
title: My research-code-test
hw_weight: medium
stages:
  - id: research
    role: researcher
    prefer_models: [claude-opus-4, grok-4.5]
    select: { max_cost: high }
  - id: critique
    role: critic
    prefer_makers: [openai]
    ack: true
    gate: true
  - id: implement
    role: builder
    prefer_models: [claude-sonnet-4]
    parallel: 2
  - id: test
    role: tester
    select: { strategy: cheapest, tier: local }
```

---

## API

```bash
# List + ranking
curl -s http://127.0.0.1:8766/api/pipelines | jq '.pipelines[]|{id,hw_weight,votes}'
curl -s http://127.0.0.1:8766/api/pipelines/ranking | jq .

# Plan stages (resolves live models)
curl -s -X POST http://127.0.0.1:8766/api/pipelines/research-code-test/plan \
  -H "Content-Type: application/json" \
  -d '{"goal":"Add OAuth to the API","session_id":"proj"}'

# Download for email / GitHub
curl -s http://127.0.0.1:8766/api/pipelines/research-code-test/export \
  -o research-code-test.aether-pipeline.json

# Upload elsewhere
curl -s -X POST http://127.0.0.1:8766/api/pipelines/import \
  -H "Content-Type: application/json" \
  -d @research-code-test.aether-pipeline.json

# Vote
curl -s -X POST http://127.0.0.1:8766/api/pipelines/research-code-test/vote \
  -H "Content-Type: application/json" \
  -d '{"up":true,"hw_flag":"medium","voter":"alice"}'
```

### Vote fields

| Field | Meaning |
|-------|---------|
| `up` / `down` | Quality vote (one per voter id) |
| `hw_flag` | `low` · `medium` · `high` · `extreme` — perceived GPU/RAM load |
| `voter` | Stable id (local username, etc.) |

Scores are **local** (`pipelines/votes.json`). A public registry can aggregate later; format stays the same.

---

## Bundled pipelines

| Id | Intent | HW |
|----|--------|-----|
| `research-code-test` | Full cloud+local loop | medium |
| `fable-local-loop` | All local (Metal/ROCm) | low |
| `premium-review` | Opus critique gate | low GPU / high $ |

---

## Flow with slash hygiene

```text
POST /api/pipelines/{id}/plan
  → stages bound to models
  → litellm_calls[] executed by client/runner
  → /done all
  → /compact or /clear   (memory first)
```

`on_complete.slash` in the script recommends which slash commands to run.

---

## Combos vs pipelines vs node graph

| | Combos | Pipelines | **Node canvas** |
|--|--------|-----------|-----------------|
| Focus | Role pins | Ordered stages | **Visual FX–style graph** |
| Format | `.aether-combo.json` | `.aether-pipeline.yaml` | `.aether-graph.json` |
| UI | Hub buttons | Hub plan | **http://127.0.0.1:8766/graph** |
| Voting | — | Yes | Export → pipeline → vote |

Use **combos** for quick packs; **pipelines** for YAML programs; **node canvas** to draw Master/Worker/Analyser and auto-wire best practices. See [NODE-GRAPH.md](./NODE-GRAPH.md).

**ActionForge:** not vendored (proprietary EULA). Aether canvas is MIT-native.
