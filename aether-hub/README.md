# Aether Hub

Capability / routing **sync matrix** (local ↔ cloud) and **shared agent memory** on Redis.

| | |
|--|--|
| Port | **8766** |
| UI | http://127.0.0.1:8766/ |
| Redis | same stack Redis (`6379`) |

## Scan first

Hub **discovers** the system before routing:

```bash
curl -s http://127.0.0.1:8766/api/discover | jq .summary
curl -s http://127.0.0.1:8766/api/discover/text
# Host-side deep scan (WSL / Radeon / dual-Ollama):
# Windows:  .\scripts\scan-system.ps1
# Linux/mac: ./scripts/scan-system.sh
```

Writes `.aetherstack/system-scan.json` and feeds recommendations into the hub UI.

## APIs

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/discover` | **System scan** — Ollama endpoints, models, LiteLLM, Redis, keys, recommendations |
| GET | `/api/discover/text` | Human-readable scan |
| POST | `/api/discover` | Merge host_scan from `scan-system.ps1` |
| GET | `/api/matrix` | Full matrix + live availability |
| GET | `/api/matrix/table` | Flat capability table |
| GET | `/api/route?need=code,tools&prefer=local` | Pick best model |
| POST | `/api/sync` | Re-discover + rewrite Redis snapshot |
| POST | `/api/memory/sessions/{id}/messages` | Append working-memory message |
| GET | `/api/memory/sessions/{id}` | Read session |
| POST | `/api/memory/vectors` | Upsert text (+ embedding) |
| POST | `/api/memory/search` | Vector similarity search |

### Route example

```bash
curl -s "http://127.0.0.1:8766/api/route?need=code&prefer=local" | jq .
# → primary.model e.g. local-default → use with LiteLLM
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-aether-local" \
  -H "Content-Type: application/json" \
  -d '{"model":"local-default","messages":[{"role":"user","content":"hi"}]}'
```

### Agent modes (inline / multi-agent + token saver)

```bash
curl -s http://127.0.0.1:8766/api/modes | jq .runtime
curl -s -X POST http://127.0.0.1:8766/api/modes \
  -H "Content-Type: application/json" \
  -d '{"mode":"multi_agent","token_saver":true,"role_overrides":{"mastermind":{"maker":"xai"},"worker":{"strategy":"cheapest"}}}'
curl -s -X POST http://127.0.0.1:8766/api/agents/plan \
  -H "Content-Type: application/json" \
  -d '{"goal":"Ship a patch","workers":2}'
```

Full guide: [docs/AGENT-MODES.md](../docs/AGENT-MODES.md)

### Memory example

```bash
# Store
curl -s -X POST http://127.0.0.1:8766/api/memory/vectors \
  -H "Content-Type: application/json" \
  -d '{"text":"Project uses LiteLLM on :4000","namespace":"lab","meta":{"source":"note"}}'

# Search
curl -s -X POST http://127.0.0.1:8766/api/memory/search \
  -H "Content-Type: application/json" \
  -d '{"query":"where is the gateway","namespace":"lab","top_k":3}'
```

Embeddings prefer Ollama `nomic-embed-text` (`ollama pull nomic-embed-text`).  
If missing, hub uses a deterministic hash embedding (weaker, always works).

## Local run (no Docker)

```bash
pip install -r requirements.txt
set REDIS_URL=redis://127.0.0.1:6379/0
set OLLAMA_BASE_URL=http://127.0.0.1:11434
python server.py
```

## Matrix file

Edit [`capability_matrix.yaml`](./capability_matrix.yaml) — keep `model` aliases aligned with `litellm_config.yaml`.
