# Shared agent memory (Redis + vectors)

Redis is no longer a silent dependency: **LiteLLM** can cache completions, and **aether-hub** stores **session working memory** and a **vector store** for multi-agent / multi-tool recall.

| Piece | Role |
|-------|------|
| `redis` service (`:6379`) | Persistence (AOF), hub data, LiteLLM cache |
| `aether-hub` (`:8766`) | HTTP API for sessions + vector upsert/search |
| Embeddings | Prefer Ollama `nomic-embed-text`; hash fallback if missing |

## Architecture

```
  Agents / IDE / scripts
           │
           ▼
     aether-hub :8766
           │
     ┌─────┴─────┐
     ▼           ▼
  sessions    vectors (JSON + embedding[])
     │           │
     └─────┬─────┘
           ▼
        Redis :6379
           ▲
           │ cache
        LiteLLM :4000
```

## Session memory (short-term)

```bash
# Append
curl -s -X POST http://127.0.0.1:8766/api/memory/sessions/demo/messages \
  -H "Content-Type: application/json" \
  -d '{"role":"user","content":"We use port 4000 for LiteLLM","index":true}'

# Read last N
curl -s "http://127.0.0.1:8766/api/memory/sessions/demo?limit=20"
```

Keys: `aether:mem:session:{id}` (Redis list, TTL default 7 days).

## Vector memory (shared long-ish term)

```bash
curl -s -X POST http://127.0.0.1:8766/api/memory/vectors \
  -H "Content-Type: application/json" \
  -d '{"namespace":"project-alpha","text":"Auth uses sk-aether-local on localhost only","meta":{"kind":"security"}}'

curl -s -X POST http://127.0.0.1:8766/api/memory/search \
  -H "Content-Type: application/json" \
  -d '{"namespace":"project-alpha","query":"API key policy","top_k":5}'
```

Cosine similarity is computed in the hub process over vectors stored in Redis hashes (lab scale: thousands of chunks). For multi-million scale, swap in Redis Stack / Qdrant later — API can stay stable.

### Better embeddings

```bash
ollama pull nomic-embed-text
# optional: AETHER_EMBED_MODEL=nomic-embed-text
```

Without that model, hub uses a **hash embedding** so demos still run (weaker semantic quality).

## LiteLLM Redis cache

`litellm_config.yaml` enables:

```yaml
litellm_settings:
  cache: true
  cache_params:
    type: redis
    host: redis
    port: 6379
    ttl: 600
```

Identical chat completions can be served from Redis within the TTL — useful for agents that retry.

## Security notes

- Memory API is open on localhost by default (same lab trust model as Project Engine).  
- Do **not** publish `:8766` / `:6379` to the internet.  
- Vector store may hold secrets if you put them in `text` — treat namespaces as sensitive.  
- For shared machines, put hub behind a reverse proxy with auth (future).

## Related

- Capability routing: [CAPABILITY-MATRIX.md](./CAPABILITY-MATRIX.md)  
- Hub package: [`aether-hub/`](../aether-hub/)  
