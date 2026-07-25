# Capability / routing sync matrix

AetherStack keeps a **sync matrix** of what each local and cloud model is good for, whether it is **live**, and how to **route** a request.

| Piece | Location |
|-------|----------|
| Matrix definition | [`aether-hub/capability_matrix.yaml`](../aether-hub/capability_matrix.yaml) |
| Service | **aether-hub** → http://127.0.0.1:8766/ |
| LiteLLM aliases | [`litellm_config.yaml`](../litellm_config.yaml) (names must stay aligned) |
| Redis snapshot | key `aether:matrix:snapshot` |

## Why it exists

Without a matrix, clients pick opaque aliases (`local-default`, `grok-4.5`) with no shared notion of:

- offline Ollama models vs missing API keys  
- code vs vision vs private/local-only  
- fallbacks when the preferred tier is down  

## Capabilities

| Tag | Meaning |
|-----|---------|
| `chat` | General conversation |
| `code` | Coding / patches |
| `reason` | Hard multi-step reasoning |
| `vision` | Images |
| `tools` | Tool / function calling |
| `embed` | Embeddings for RAG / memory |
| `private` | Prefer no cloud egress |
| `fast` / `cheap` | Latency / cost |
| `long_context` | Large context windows |

## Scan first, then route

Do **not** assume models exist. Hub runs **system discovery** first:

```bash
# What is up? (Ollama endpoints, pulled models, LiteLLM, Redis, API keys)
curl -s http://127.0.0.1:8766/api/discover | jq .
# Host deep scan (Windows + WSL Radeon / dual Ollama):
#   .\scripts\scan-system.ps1
```

Recommendations (e.g. “pull tinyllama”, “ROCm libs missing”, “two Ollamas fighting”) appear on http://127.0.0.1:8766/ and in `discover.recommendations`.

## Live sync

Every `AETHER_MATRIX_SYNC_SEC` (default 60s) the hub:

1. Runs `/api/discover` (Ollama multi-endpoint probe + services + keys)  
2. Loads `capability_matrix.yaml`  
3. Marks each alias available only if the **backend model is actually pulled** / key present  
4. Writes annotated snapshot to Redis + serves `/api/matrix`  

```bash
curl -s http://127.0.0.1:8766/api/discover | jq .summary
curl -s http://127.0.0.1:8766/api/sync | jq .summary
curl -s "http://127.0.0.1:8766/api/route?need=code&prefer=local" | jq .primary
```

## Routing policy

`prefer`:

- `local` — bias Ollama  
- `cloud` — bias API providers  
- `auto` — local for `private`/`cheap`; cloud for `vision`/`reason`/`long_context`  

YAML `routing.fallbacks` lists ordered aliases if scoring finds nothing.

## UI

Open http://127.0.0.1:8766/ for a compact model × capability table (green = has capability, dim row = offline).

## Keeping matrix ↔ LiteLLM in sync

| Change | Update |
|--------|--------|
| New LiteLLM alias | Add row under `models:` in `capability_matrix.yaml` |
| New capability tag | Add under `capabilities:` + tags on models |
| Change fallback order | Edit `routing.fallbacks` |

Hub mounts the YAML read-only; edit on the host and call `POST /api/sync` (or wait for interval).

## Flaws this does **not** fully solve

- Does not auto-edit `litellm_config.yaml` (by design — keep gateway config reviewable).  
- Availability for cloud is “key present”, not a live provider health ping.  
- Ollama model tags must match `backend: ollama/...` strings.  
