# Slash commands

Hub session commands. Order of operations is fixed:

1. Complete work (`/done`)  
2. Archive into durable memory  
3. Clear or compact working context  

| Command | Effect |
|---------|--------|
| `/help` | List commands |
| `/status` | Open tasks, message count, clear eligibility |
| `/task add …` / `/task list` | Track work units |
| `/done <id\|all>` | Mark complete; archive when all done |
| `/save` | Archive without clear |
| `/clear` | Archive then clear session (blocked if open tasks) |
| `/clear force` | Archive then clear with open tasks |
| `/compact` | Archive then clear; keep short summary line |
| `/context` | Working summary + recent messages |

---

## Archive targets

| Namespace | Content |
|-----------|---------|
| `archive:{session_id}` | Full archive document |
| `conversation-index` | Search breadcrumb |

```bash
curl -s -X POST http://127.0.0.1:8766/api/memory/search \
  -H "Content-Type: application/json" \
  -d '{"query":"auth decision","namespace":"conversation-index","top_k":5}'
```

| Failure mode | Correct sequence |
|--------------|------------------|
| Clear mid-task | `/done` → archive → `/clear` |
| Clear without save | Use `/clear` (archives first) |
| Unbounded chat | Clear after milestones; search memory for recall |

---

## API

```bash
curl -s -X POST http://127.0.0.1:8766/api/slash \
  -H "Content-Type: application/json" \
  -d '{"session_id":"my-project","text":"/status"}'

curl -s -X POST http://127.0.0.1:8766/api/slash \
  -H "Content-Type: application/json" \
  -d '{"session_id":"my-project","text":"/task add wire ROCm"}'

curl -s -X POST http://127.0.0.1:8766/api/slash \
  -H "Content-Type: application/json" \
  -d '{"session_id":"my-project","text":"/done all"}'

curl -s -X POST http://127.0.0.1:8766/api/slash \
  -H "Content-Type: application/json" \
  -d '{"session_id":"my-project","text":"/clear"}'
```

| Method | Path |
|--------|------|
| GET | `/api/slash` — command list |
| POST | `/api/sessions/{id}/message` — user text; slash auto-detected |
| GET | `/api/sessions/{id}/status` — same as `/status` |

---

## Multi-agent events

`POST /api/agents/plan` with `track_task: true` (default) registers a task for the event.

Procedure after agents finish:

```text
/done <id> | /done all
  → /clear | /compact
```

```bash
curl -s -X POST http://127.0.0.1:8766/api/agents/plan \
  -H "Content-Type: application/json" \
  -d '{"goal":"Refactor auth","session_id":"my-project","track_task":true}'
```

---

## IDE clients

Continue and Claude Code implement their own `/clear`. Aether memory uses Hub slash only:

```text
POST /api/slash  {"session_id":"…","text":"/clear"}
```

Full loop:

```text
plan multi-agent event
  → workers + supervisor complete
  → /done all
  → /clear or /compact
  → next goal (lean context; memory search as needed)
```
