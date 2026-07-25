# Cross-project memory (multi-project mode)

Scan **all registered projects** for LLM-native folders (chat/session history, decisions, notes), index them into shared memory, and — when **multi-project mode** is on — **pull** already built/tested concepts, code, and research into the active session.

## What gets scanned

| Location | Tools | Typical content |
|----------|--------|-----------------|
| `.continue/` | Continue.dev | chat / sessions |
| `.claude/` | Claude Code | sessions, plans |
| `.cursor/` | Cursor | project AI config / history |
| `.aider*` / `aider.chat.history.md` | Aider | chat history |
| `.waylog/` | WayLog | archives |
| `.aetherstack/` | AetherStack | overviews, snapshots, research notes |
| `.codex/`, `.windsurf/`, `.gemini/`, … | other agents | sessions |
| `docs/` | human/AI docs | research (sampled) |

Each chunk is tagged: **`chat` · `session` · `code` · `research` · `concept` · `test`**.

---

## Enable multi-project mode

```bash
curl -s -X POST http://127.0.0.1:8766/api/xref \
  -H "Content-Type: application/json" \
  -d '{"multi_project":true,"auto_pull":true,"max_pull":8}'
```

When **off**, cross-project search/pull refuse (avoids leaking other repos by accident).

---

## Index projects (host scan → hub)

Hub usually runs in Docker and **cannot read arbitrary Windows paths**. Scan on the host and POST chunks:

```powershell
# One project
.\scripts\scan-cross-projects.ps1 -Paths D:\code\myapp -EnableMultiProject

# All sibling repos under a parent folder
.\scripts\scan-cross-projects.ps1 -Paths D:\code -FromParent -EnableMultiProject
```

```bash
# Linux/macOS (hub can often read local paths if not containerized)
python3 - <<'PY'
from cross_memory import scan_project_tree, index_scan
# or POST to hub /api/xref/index
PY
```

Or API:

```bash
# If hub can read the path (Linux host / mounted volume):
curl -s -X POST http://127.0.0.1:8766/api/xref/scan \
  -H "Content-Type: application/json" \
  -d '{"paths":["/home/you/code/app1","/home/you/code/app2"]}'
```

---

## Search & pull

```bash
# Search across all indexed projects
curl -s -X POST http://127.0.0.1:8766/api/xref/search \
  -H "Content-Type: application/json" \
  -d '{"query":"OAuth middleware tested","kinds":["code","concept","test"],"top_k":10}'

# Auto-build a prompt block to inject into the active chat / agent plan
curl -s -X POST http://127.0.0.1:8766/api/xref/pull \
  -H "Content-Type: application/json" \
  -d '{"query":"payment webhook","kinds":["code","research","concept"]}'
```

`pull` returns `prompt_block` — paste into Continue, or pass as `context` into pipeline/agent plan.

---

## Operating model

```text
Project A (.claude, .continue, …) ──┐
Project B (.cursor, aider, …)     ──┼──► index → Redis xref namespace
Project C (.aetherstack, docs)    ──┘
                                      │
         multi_project ON             ▼
         user asks in "one window" → pull related code/research/tests
                                      │
                                      ▼
                         agent/pipeline uses reused concepts
                         /done → /clear (session lean; xref remains)
```

Fits the façade: **one chat**, but memory can see **all enrolled projects**.

---

## API summary

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/api/xref` | State: multi_project, projects registry |
| POST | `/api/xref/scan` | Scan paths (if readable) + index |
| POST | `/api/xref/index` | Index a pre-built scan payload (host script) |
| POST | `/api/xref/search` | Cross-project search |
| POST | `/api/xref/pull` | Search + `prompt_block` for injection |

---

## Privacy

- Multi-project is **off by default**.  
- Only projects you scan/register are searchable.  
- Do not index secrets-bearing chats into shared machines without care.  
