# Private mode

Isolate a **project** and/or **model** from the common session memory pool.  
Private state is **persistent until explicit release**. Release does **not** merge vault data into common memory.

---

## Guarantees

| Surface | Private behavior |
|---------|------------------|
| Session messages | Stored under `private:{project_id}:{session_id}` only |
| Vector upsert | Remapped to `private:{project_id}:…` vault namespaces |
| Common namespaces | Blocked: `default`, `conversation-index`, `xref`, `agent-events`, `session:*`, `session-context:*` |
| Cross-project index | Private projects excluded from scan/index |
| Xref auto-pull | Disabled for private sessions/models |
| Slash `/save` `/clear` | Vault archive only; no `conversation-index` sticky |
| Logs / system lines | Redacted (`[private] action=…`); no prompt/content |
| Working notes | Content redacted while private |

---

## Enable

### Project + session

```bash
curl -s -X POST http://127.0.0.1:8766/api/privacy \
  -H "Content-Type: application/json" \
  -d '{"private":true,"path":"D:/code/secret-app","session_id":"work","models":["local-default"]}'
```

### Model only

```bash
curl -s -X POST http://127.0.0.1:8766/api/privacy \
  -H "Content-Type: application/json" \
  -d '{"private":true,"model":"local-default"}'
```

### Slash

```text
/private on D:/code/secret-app
/private status
```

---

## Release

Required to leave private state. Vault purge default: **on**. No merge into common pool.

```bash
curl -s -X POST http://127.0.0.1:8766/api/privacy/release \
  -H "Content-Type: application/json" \
  -d '{"project_id":"<id from GET /api/privacy>","purge_vault":true}'
```

```text
/private release <project_id>
```

---

## API

| Method | Path | Body |
|--------|------|------|
| GET | `/api/privacy` | — state |
| POST | `/api/privacy` | `private`, `path`, `project_id`, `session_id`, `model`, `models` |
| POST | `/api/privacy/release` | `project_id`, `purge_vault` (default true) |

Request flags on other endpoints:

| Field | Effect |
|-------|--------|
| `private: true` | Force private context for that call |
| `session_id` | Bound private session |
| `project_id` / `path` | Project private lookup |
| `model` | Model private lookup |

---

## Persistence

| Store | Role |
|-------|------|
| Redis key `aether:private:state` | Authoritative when Redis up |
| `aether-hub/data/privacy_state.json` | Disk backup |

Survives hub restart until release.

---

## Operator rules

1. Mark private **before** sensitive research or local-only work.  
2. Do not pass private session content into common `namespace` fields.  
3. Release only when the project may leave isolation; assume vault wipe if `purge_vault: true`.  
4. Multi-project xref remains off for private projects even when multi_project is globally on.  

---

## Related

- [AGENT-MEMORY.md](./AGENT-MEMORY.md)  
- [CROSS-MEMORY.md](./CROSS-MEMORY.md)  
- [SLASH-COMMANDS.md](./SLASH-COMMANDS.md)  
- Enterprise multi-user silo (planned): [FUTURE.md](./FUTURE.md)  

