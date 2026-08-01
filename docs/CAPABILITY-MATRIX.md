# Capability matrix

Sync matrix of model capabilities, live availability, and route selection.

| Piece | Location |
|-------|----------|
| Definition | [`aether-hub/capability_matrix.yaml`](../aether-hub/capability_matrix.yaml) |
| Service | http://127.0.0.1:8766/ |
| LiteLLM aliases | [`litellm_config.yaml`](../litellm_config.yaml) |
| Redis snapshot | `aether:matrix:snapshot` |

---

## Function

Without the matrix, clients hold opaque aliases with no shared state for:

- offline Ollama vs missing API keys  
- capability tags (code, vision, private, …)  
- ordered fallbacks when preferred tier is down  

---

## Capability tags

| Tag | Meaning |
|-----|---------|
| `chat` | General conversation |
| `code` | Coding / patches |
| `reason` | Multi-step reasoning |
| `vision` | Images |
| `tools` | Tool / function calling |
| `embed` | Embeddings |
| `private` | Prefer no cloud egress |
| `fast` / `cheap` | Latency / cost bias |
| `long_context` | Large context windows |

---

## Discover then route

Do not assume models exist. Hub discovery runs first.

```bash
curl -s http://127.0.0.1:8766/api/discover | jq .
# Host deep scan:
#   .\scripts\scan-system.ps1
#   ./scripts/scan-system.sh
```

Recommendations appear on Hub UI and in `discover.recommendations`.

---

## Live sync

Interval: `AETHER_MATRIX_SYNC_SEC` (default 60).

1. Run discover (Ollama multi-endpoint, services, keys)  
2. Load `capability_matrix.yaml`  
3. Mark alias available only if backend model is pulled / key present  
4. Write snapshot to Redis; serve `/api/matrix`  

```bash
curl -s http://127.0.0.1:8766/api/discover | jq .summary
curl -s http://127.0.0.1:8766/api/sync | jq .summary
curl -s "http://127.0.0.1:8766/api/route?need=code&prefer=local" | jq .primary
```

---

## Routing policy

| `prefer` | Behavior |
|----------|----------|
| `local` | Bias Ollama |
| `cloud` | Bias API providers and authenticated host CLI seats |
| `subscription` | Bias available authenticated Codex, Claude, or Grok host CLI seats; falls back normally when none are available |
| `auto` | Local for `private`/`cheap`; authenticated host CLI first for code/tools/reasoning when available, then cloud/local candidates |

`subscription` refers to an already authenticated host CLI seat (`executor: host_cli`), not a browser session or an API subscription key.

YAML `routing.fallbacks` lists ordered aliases when scoring finds none.

---

## UI

http://127.0.0.1:8766/ — model × capability table (green = capability present; dim row = offline).

---

## Matrix ↔ LiteLLM alignment

| Change | Update |
|--------|--------|
| New LiteLLM alias | Add row under `models:` in `capability_matrix.yaml` |
| Removed model | Remove or mark unavailable in matrix |
| Capability change | Edit tags on the matrix row |

Keep alias strings identical across `litellm_config.yaml` and the matrix.
