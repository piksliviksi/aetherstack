# Slash commands (context hygiene)

Claude-style commands for Aether Hub sessions. They run in the **correct order**:

1. Finish work (`/done`)  
2. **Document** into durable agent memory  
3. **Clear / compact** working context so the next prompt stays optimal  

| Command | Effect |
|---------|--------|
| `/help` | List commands |
| `/status` | Open tasks, message count, can_clear? |
| `/task add …` / `/task list` | Track work units |
| `/done <id\|all>` | Mark tasks complete; auto-archives when all done |
| `/save` | Archive to memory **without** clearing |
| `/clear` | Archive → clear session (blocked if open tasks) |
| `/clear force` | Archive → clear even with open tasks |
| `/compact` | Archive → clear but keep a short summary line |
| `/context` | Peek working summary + recent messages |

---

## Why this order

| Bad | Good |
|-----|------|
| Clear mid-task → lose decisions | `/done` → memory → `/clear` |
| Clear without save → amnesia | `/clear` always **archives first** |
| Huge chat forever → token waste | Clear after milestones; search memory later |

Archives go to:

- Vector namespace `archive:{session_id}` (full doc)  
- Index namespace `conversation-index` (breadcrumb for search)  

Recall:

```bash
curl -s -X POST http://127.0.0.1:8766/api/memory/search \
  -H "Content-Type: application/json" \
  -d '{"query":"auth decision","namespace":"conversation-index","top_k":5}'
```

---

## API

```bash
# Any slash string
curl -s -X POST http://127.0.0.1:8766/api/slash \
  -H "Content-Type: application/json" \
  -d '{"session_id":"my-project","text":"/status"}'

# Explicit clear after tasks
curl -s -X POST http://127.0.0.1:8766/api/slash \
  -d '{"session_id":"my-project","text":"/task add wire ROCm"}' \
  -H "Content-Type: application/json"

curl -s -X POST http://127.0.0.1:8766/api/slash \
  -d '{"session_id":"my-project","text":"/done all"}' \
  -H "Content-Type: application/json"

curl -s -X POST http://127.0.0.1:8766/api/slash \
  -d '{"session_id":"my-project","text":"/clear"}' \
  -H "Content-Type: application/json"
```

Also:

| Method | Path |
|--------|------|
| GET | `/api/slash` — command list |
| POST | `/api/sessions/{id}/message` — user text; auto-detects slash |
| GET | `/api/sessions/{id}/status` — same as `/status` |

---

## Multi-agent events

When you `POST /api/agents/plan` / combo plan:

- Register a task for the event (optional `track_task: true`)  
- When agents finish, client should `/done <id>` then `/clear` or `/compact`  

Hub can auto-register:

```bash
curl -s -X POST http://127.0.0.1:8766/api/agents/plan \
  -H "Content-Type: application/json" \
  -d '{"goal":"Refactor auth","session_id":"my-project","track_task":true}'
```

---

## VS Code / Continue

Continue and Claude Code have their own `/clear`. For **Aether-managed** memory:

1. Run hub slash via HTTP (or future extension command **AetherStack: Session /clear**).  
2. Or call the API from a task runner after a multi-agent event completes.

Ideal loop:

```text
plan multi-agent event
  → workers + supervisor finish
  → /done all
  → /save or automatic archive on /done
  → /clear or /compact
  → next goal with lean context + memory search if needed
```
