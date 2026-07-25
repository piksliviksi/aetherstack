# Gateway (LiteLLM façade)

Clients talk to **one** OpenAI-compatible endpoint. LiteLLM routes aliases to local Ollama and cloud providers per [`litellm_config.yaml`](../litellm_config.yaml).

```text
Base URL: http://127.0.0.1:4000/v1
API key:  LITELLM_MASTER_KEY from .env
Model:    one alias from the table below (or your additions)
```

Hub / policy / multi-agent live on **:8766** and do not replace this façade for day-to-day IDE chat.

---

## Default model aliases

Edit [`litellm_config.yaml`](../litellm_config.yaml) to add more. LiteLLM can also accept provider-style names if you extend the list.

| Alias | Backend |
|-------|---------|
| `local-default` / `local-llama` | Host Ollama (`llama3.1:8b`) |
| `local-tiny` | Host Ollama (`tinyllama`) |
| `grok` / `grok-4.5` | xAI Grok 4.5 |
| `grok-4.3` / `grok-4` / `grok-4-fast` / `grok-code` | xAI Grok 4.x family |
| `grok-3` | xAI Grok 3 (legacy) |
| `gpt-4.1` / `gpt-4.1-mini` / `gpt-4o` / `o3` / `o4-mini` | OpenAI |
| `codex` / `openai-default` | OpenAI GPT-4.1 |
| `claude` / `claude-sonnet-4` / `claude-opus-4` / `claude-haiku` | Anthropic |
| `gemini` / `gemini-2.5-pro` / `gemini-2.5-flash` | Google Gemini |

### Environment keys

| Variable | Provider |
|----------|----------|
| `XAI_API_KEY` | xAI / Grok |
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GOOGLE_API_KEY` | Gemini |
| `LITELLM_MASTER_KEY` | Client auth for the gateway itself |

Only set keys for providers you use. Local Ollama does not need a cloud key.

---

## Listing models

```bash
# Windows
powershell -File scripts/list-models.ps1

# Linux / macOS
./scripts/list-models.sh

curl http://localhost:4000/v1/models \
  -H "Authorization: Bearer sk-aether-local"
```

Default lab key is often `sk-aether-local` — match whatever is in `.env`.

### “401 No api key passed in”

**Expected** when opening `http://localhost:4000` in a normal browser tab (no `Authorization` header). Use:

- Open WebUI at http://localhost:3000  
- An IDE client with the master key  
- `curl` / `list-models` scripts as above  

---

## Example completion

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-aether-local" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local-default",
    "messages": [{"role": "user", "content": "hi"}]
  }'
```

Routing preference from Hub (which model is good for a need):

```bash
curl -s "http://127.0.0.1:8766/api/route?need=code&prefer=local"
```

Then call LiteLLM with the model id returned.

---

## Related

- [QUICKSTART.md](./QUICKSTART.md) — first run  
- [OPERATING-MODEL.md](./OPERATING-MODEL.md) — one-façade philosophy  
- [AGENT-MODES.md](./AGENT-MODES.md) — multi-agent policy behind the façade  
- [aether-hub/README.md](../aether-hub/README.md) — hub APIs  
