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
  -d '{"namespace":"project-alpha","text":"Auth uses sk-aether-local on localhost only","meta":{"kind":"security"}}'

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

## LiteLLM Redis cache

```yaml
litellm_settings:
  cache: true
  cache_params:
    type: redis
    host: redis
    port: 6379
    ttl: 600
```

Identical completions within TTL are served from Redis.

---

## Security constraints

| Rule | Fact |
|------|------|
| Default bind | Localhost lab trust model |
| Exposure | Do not publish `:8766` or `:6379` publicly |
| Content | Vectors store whatever text is upserted — treat as sensitive |
| Shared host | Put Hub behind authenticated reverse proxy |

---

## Related

- [CAPABILITY-MATRIX.md](./CAPABILITY-MATRIX.md)  
- [CROSS-MEMORY.md](./CROSS-MEMORY.md)  
- [aether-hub/](../aether-hub/)  
