# Agent modes, token saver, multi-LLM orchestration

Aether Hub supports two **execution modes** and an optional **token saver**. In multi-agent mode, a single event can use **different LLMs** for different roles.

| | |
|--|--|
| Config | [`aether-hub/agent_modes.yaml`](../aether-hub/agent_modes.yaml) |
| API base | http://127.0.0.1:8766 |

---

## Modes

| Mode | Behavior |
|------|----------|
| **`inline`** (default) | One model handles the whole event end-to-end |
| **`multi_agent`** | **Mastermind** plans → **workers** (possibly many models) → **supervisor** reviews → mastermind synthesizes |

Toggle:

```bash
# Multi-agent ON
curl -s -X POST http://127.0.0.1:8766/api/modes \
  -H "Content-Type: application/json" \
  -d '{"mode":"multi_agent"}'

# Back to single-model inline
curl -s -X POST http://127.0.0.1:8766/api/modes \
  -d '{"mode":"inline"}' -H "Content-Type: application/json"

curl -s http://127.0.0.1:8766/api/modes | jq .runtime
```

---

## Token saver

Default: off unless set. When **`token_saver: true`**:

- Prefer **local / cheap** models for bulk (workers, inline)
- **Cap** `max_tokens` per role
- **Compress** long prompts (head + tail)
- Bias routing toward `cheap` / `fast` capabilities
- Reduce memory snippets attached (when used with memory search)

```bash
# Enable
curl -s -X POST http://127.0.0.1:8766/api/modes \
  -H "Content-Type: application/json" \
  -d '{"token_saver":true}'

# Disable
curl -s -X POST http://127.0.0.1:8766/api/modes \
  -H "Content-Type: application/json" \
  -d '{"token_saver":false}'
```

Knobs live under `token_saver:` in `agent_modes.yaml`.

---

## Roles (multi-agent)

| Role | Job | Typical pick |
|------|-----|----------------|
| **mastermind** | Orchestrates the event, splits work, final synthesis | Strong reasoner (cloud or best local) |
| **supervisor** | Quality-gates worker outputs | Separate strong model (often different maker) |
| **worker** | Bulk work (drafts, code chunks, extraction) | Cheap / local / mini models |

Role selectors:

| Selector | Example |
|----------|---------|
| **model** (alias / version) | `"model": "grok-4.5"` |
| **maker** (provider) | `"maker": "anthropic"` → OpenAI, Anthropic, xAI, Google, Ollama |
| **tier** | `"tier": "local"` or `"cloud"` |
| **strategy** | `best_score` · `cheapest` · `by_maker` · `by_tier` |
| **max_cost** | `low` · `medium` · `high` · `very_high` |

```bash
# Mastermind = xAI, supervisor = Anthropic, workers = cheapest local
curl -s -X POST http://127.0.0.1:8766/api/modes \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "multi_agent",
    "token_saver": true,
    "role_overrides": {
      "mastermind": {"maker": "xai", "strategy": "best_score"},
      "supervisor": {"maker": "anthropic"},
      "worker": {"tier": "local", "strategy": "cheapest"}
    }
  }'
```

Pin exact models:

```bash
curl -s -X POST http://127.0.0.1:8766/api/modes \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "multi_agent",
    "role_overrides": {
      "mastermind": {"model": "grok-4.5"},
      "supervisor": {"model": "claude-sonnet-4"},
      "worker": {"model": "local-default"}
    }
  }'
```

---

## Plan one event (multi-LLM)

Does **not** bill providers by itself — returns a plan + `litellm_calls` you (or an executor) send to `:4000`.

```bash
curl -s -X POST http://127.0.0.1:8766/api/agents/plan \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Refactor auth module and write tests",
    "mode": "multi_agent",
    "token_saver": true,
    "workers": 3,
    "roles": {
      "mastermind": {"maker": "xai"},
      "supervisor": {"maker": "anthropic"},
      "worker": {"strategy": "cheapest", "tier": "local"}
    },
    "tasks": [
      {"id": "auth", "description": "Refactor login flow", "need": ["code"]},
      {"id": "tests", "description": "Add unit tests", "need": ["code"]},
      {"id": "docs", "description": "Update README section", "need": ["chat"], "maker": "openai"}
    ]
  }' | jq '{mode, models_in_event, makers_in_event, agents: [.agents[]|{role,model,provider}]}'
```

Per-task overrides: `model` / `maker` / `tier` / `need`. One event can fan out to several makers.

Execute a planned call:

```bash
# Example: take first litellm_calls entry from the plan
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"local-default","messages":[{"role":"user","content":"hi"}],"max_tokens":256}'
```

---

## Presets

| Preset | Effect |
|--------|--------|
| `thrifty` | multi_agent + token_saver + cheap roles |
| `quality` | multi_agent, xAI mastermind, Anthropic supervisor, OpenAI workers |
| `local_only` | all roles local tier |
| `single_inline` | classic one-model |

```bash
curl -s -X POST http://127.0.0.1:8766/api/modes -d '{"preset":"thrifty"}' -H "Content-Type: application/json"
```

---

## Status

```bash
curl -s http://127.0.0.1:8766/api/modes | jq '{runtime, resolved_now, presets}'
```

`resolved_now` shows which **live** model each role would get right now (uses discover + matrix availability).

---

## Flow

```
User toggles mode + token_saver + role pins
        │
        ▼
 POST /api/agents/plan  (one event)
        │
        ├─ mastermind  → LLM A (e.g. grok-4.5)
        ├─ worker×N    → LLM B/C/… (local-default, gpt-4.1-mini, …)
        └─ supervisor  → LLM D (e.g. claude-sonnet-4)
        │
        ▼
 litellm_calls[] → LiteLLM :4000  (actual inference)
```
