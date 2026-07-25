# Gateway (LiteLLM)

Single OpenAI-compatible endpoint for all model aliases.  
Policy, multi-agent, and graphs run on Hub `:8766` and do not replace this façade for IDE chat.

```text
Base URL: http://127.0.0.1:4000/v1
API key:  LITELLM_MASTER_KEY
Model:    one alias from litellm_config.yaml
```

Config file: [`litellm_config.yaml`](../litellm_config.yaml).

---

## Default aliases

| Alias | Backend |
|-------|---------|
| `local-default` / `local-llama` | Host Ollama (`llama3.1:8b`) |
| `local-tiny` | Host Ollama (`tinyllama`) |
| `grok` / `grok-4.5` | xAI Grok 4.5 |
| `grok-4.3` / `grok-4` / `grok-4-fast` / `grok-code` | xAI Grok 4.x |
| `grok-3` | xAI Grok 3 |
| `gpt-4.1` / `gpt-4.1-mini` / `gpt-4o` / `o3` / `o4-mini` | OpenAI |
| `codex` / `openai-default` | OpenAI GPT-4.1 |
| `claude` / `claude-sonnet-4` / `claude-opus-4` / `claude-haiku` | Anthropic |
| `gemini` / `gemini-2.5-pro` / `gemini-2.5-flash` | Google Gemini |

---

## Environment keys

| Variable | Provider |
|----------|----------|
| `XAI_API_KEY` | xAI |
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GOOGLE_API_KEY` | Gemini |
| `LITELLM_MASTER_KEY` | Gateway client auth |

Set only keys for providers in use. Local Ollama does not require a cloud key.

---

## List models

```bash
powershell -File scripts/list-models.ps1   # Windows
./scripts/list-models.sh                  # Linux / macOS
curl http://localhost:4000/v1/models \
  -H "Authorization: Bearer sk-aether-local"
```

### HTTP 401

Bare browser requests to `:4000` omit `Authorization`. That returns 401.  
Use Open WebUI `:3000`, an IDE client with the master key, or curl as above.

---

## Completion example

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-aether-local" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local-default",
    "messages": [{"role": "user", "content": "hi"}]
  }'
```

Route selection (Hub):

```bash
curl -s "http://127.0.0.1:8766/api/route?need=code&prefer=local"
```

Call LiteLLM with the returned model id.

---

## Related

- [QUICKSTART.md](./QUICKSTART.md)  
- [OPERATING-MODEL.md](./OPERATING-MODEL.md)  
- [AGENT-MODES.md](./AGENT-MODES.md)  
- [aether-hub/README.md](../aether-hub/README.md)  
