# Critical review (AetherStack code & ops)

Snapshot after introducing **aether-hub** (matrix + memory). Severity is lab-context (localhost control plane).

## High

| Finding | Notes | Mitigation status |
|---------|--------|-------------------|
| Default secrets (`sk-aether-local`, `WEBUI_AUTH=false`) | Fine for solo lab; catastrophic if ports are LAN/WAN exposed | Documented; change keys before any share |
| Project Engine path scan | Caller-controlled paths over HTTP | Allowlist tightened (no whole drives); optional token |
| Hub memory API unauthenticated | Any local process can read/write vectors & sessions | Bind localhost / don’t publish 8766; token later |

## Medium

| Finding | Notes | Mitigation status |
|---------|--------|-------------------|
| Redis was idle | Compose shipped Redis with **zero consumers** | **Fixed:** LiteLLM cache + aether-hub memory/matrix snapshot |
| No model capability routing | Clients guessed aliases; no local/cloud policy | **Fixed:** `capability_matrix.yaml` + `/api/route` |
| Open WebUI ↔ LiteLLM weak coupling | UI often only saw Ollama | **Improved:** `OPENAI_API_BASE_URL` → litellm |
| Cloud “availability” = env key set | Does not prove provider quota/network | Acceptable for v1; optional ping later |
| Duplicate LiteLLM aliases | `grok`/`grok-4.5`, `claude`/`claude-sonnet-4` | Intentional ergonomics; matrix lists primary names |

## Low

| Finding | Notes | Mitigation status |
|---------|--------|-------------------|
| No compose healthchecks (legacy) | Restart storms hard to debug | Redis healthcheck added; extend to litellm/hub |
| Hash embeddings fallback | Semantic search weak without `nomic-embed-text` | Documented pull |
| Extension dual-install history | `piksliviksi.*` vs `AetherStack.*` | Docs; user uninstalls old |
| `litellm:main-latest` floating tag | Reproducibility | Pin digest in production |
| Matrix/LiteLLM dual maintenance | Two files can drift | Docs checklist; single source is YAML matrix for *capabilities*, LiteLLM for *wiring* |

## Design choices (intentional)

1. **Hub does not rewrite `litellm_config.yaml`** — gateway config stays explicit and reviewable.  
2. **Vectors in Redis hashes + app-side cosine** — enough for lab RAG; not a replacement for Qdrant at scale.  
3. **Project Engine stays separate** (`:8765`) from Hub (`:8766`) — disk/OS telemetry vs model/memory control plane.

## Suggested next hardening

1. Optional `AETHER_HUB_TOKEN` (mirror engine token).  
2. Open WebUI auth on non-lab installs.  
3. Pin image digests; CI `compose config` + hub unit tests.  
4. Matrix-driven generation of a *suggested* litellm fragment (PR bot / script).  
