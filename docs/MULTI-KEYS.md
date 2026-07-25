# Multi-account API keys

Run **personal / subscription** and **enterprise / work** credentials for the same provider **at the same time**.  
No overwriting a single `*_API_KEY` when switching hats.

---

## Problem

| Setup | Failure mode |
|-------|----------------|
| One `ANTHROPIC_API_KEY` | Personal sub and company API cannot coexist |
| Swap keys in `.env` | Restarts, broken sessions, wrong billing account |
| Separate apps | Re-import context; lose façade continuity |

## Scheme

For each cloud provider:

| Env var | Slot | Model alias form |
|---------|------|------------------|
| `{PROVIDER}_API_KEY` | **primary** (default) | `claude-sonnet-4`, `gpt-4.1`, … |
| `{PROVIDER}_API_KEY_PERSONAL` | **personal** / subscription | `claude-sonnet-4-personal`, … |
| `{PROVIDER}_API_KEY_ENTERPRISE` | **enterprise** / org API | `claude-sonnet-4-enterprise`, … |

Providers: `OPENAI`, `ANTHROPIC`, `XAI`, `GOOGLE`, `MISTRAL`.

---

## Example — Anthropic personal + enterprise

```env
# Personal / subscription console key
ANTHROPIC_API_KEY_PERSONAL=sk-ant-api03-personal-...

# Company API key
ANTHROPIC_API_KEY_ENTERPRISE=sk-ant-api03-work-...

# Optional: primary still used by unsuffixed aliases
# ANTHROPIC_API_KEY=...
```

```bash
# Personal quota
curl http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-aether-local" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-personal","messages":[{"role":"user","content":"hi"}]}'

# Enterprise billing — same stack, same moment
curl http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-aether-local" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-enterprise","messages":[{"role":"user","content":"hi"}]}'
```

IDE: set Continue / extension default model to `claude-sonnet-4-personal` for day-to-day sub work; pin enterprise aliases in combos/pipelines for work roles.

---

## Combos / pipelines

Pin roles to key slots via alias:

```yaml
roles:
  mastermind:
    model: claude-opus-4-enterprise   # company key
  worker:
    model: claude-haiku-personal      # personal headroom
```

Failover can cross slots (e.g. enterprise → personal → local) in ordered fallbacks.

---

## Discover

```bash
curl -s http://127.0.0.1:8766/api/discover | jq .cloud_keys
```

Shows `by_provider` and `multi_account_providers` when two or more slots are set for one maker.

---

## Regenerate LiteLLM aliases

```bash
python scripts/gen-multi-key-aliases.py
# merge litellm_multi_keys.fragment.yaml into litellm_config.yaml if needed
```

Hub capability matrix auto-expands `-personal` / `-enterprise` rows from each cloud model.

---

## Constraints

| Fact | |
|------|--|
| Provider still enforces its own auth | Wrong key type / revoked key fails at the provider |
| Claude.ai chat subscription ≠ API key | Personal slot is for a **console API key** from that account, not browser session cookies |
| Empty env for an alias | Alias listed but unavailable until key is set |
| Restart LiteLLM | After changing `.env` keys: `docker compose up -d litellm aether-hub` |

---

## Related

- [GATEWAY.md](./GATEWAY.md)  
- [OPERATING-MODEL.md](./OPERATING-MODEL.md) continuity workflows  
- [`.env.example`](../.env.example)  
