# Cross-project memory

Index LLM-native folders across registered projects. With **multi-project mode on**, search and pull code, concepts, research, and session history into the active work.

**Default:** multi-project **off**. Search and pull refuse until enabled.

---

## Scan targets

| Location | Tools | Content class |
|----------|--------|---------------|
| `.continue/` | Continue | chat / sessions |
| `.claude/` | Claude Code | sessions, plans |
| `.cursor/` | Cursor | project AI config / history |
| `.aider*` / `aider.chat.history.md` | Aider | chat history |
| `.waylog/` | WayLog | archives |
| `.aetherstack/` | AetherStack | overviews, snapshots, notes |
| `.codex/`, `.windsurf/`, `.gemini/`, `.grok/` | other agents | sessions |
| `docs/` | docs | research (sampled) |

Chunk kinds: `chat` · `session` · `code` · `research` · `concept` · `test`.

---

## Enable

```bash
curl -s -X POST http://127.0.0.1:8766/api/xref \
  -H "Content-Type: application/json" \
  -d '{"multi_project":true,"auto_pull":true,"max_pull":8}'
```

| Flag | Effect |
|------|--------|
| `multi_project: false` | Cross search/pull disabled |
| `auto_pull: true` | `POST /api/agents/plan` attaches `xref_pull` for the goal |
| `max_pull` | Cap on pulled snippets (1–30) |

---

## Index

Hub in Docker cannot read arbitrary Windows host paths. Index from the host; POST chunks to the Hub.

```powershell
.\scripts\scan-cross-projects.ps1 -Paths D:\code\myapp -EnableMultiProject
.\scripts\scan-cross-projects.ps1 -Paths D:\code -FromParent -EnableMultiProject
```

Hub-readable paths (native Linux / mounted volumes):

```bash
curl -s -X POST http://127.0.0.1:8766/api/xref/scan \
  -H "Content-Type: application/json" \
  -d '{"paths":["/home/you/code/app1","/home/you/code/app2"]}'
```

Host-built payload:

```bash
curl -s -X POST http://127.0.0.1:8766/api/xref/index \
  -H "Content-Type: application/json" \
  -d @scan-payload.json
```

---

## Search and pull

```bash
curl -s -X POST http://127.0.0.1:8766/api/xref/search \
  -H "Content-Type: application/json" \
  -d '{"query":"OAuth middleware tested","kinds":["code","concept","test"],"top_k":10}'

curl -s -X POST http://127.0.0.1:8766/api/xref/pull \
  -H "Content-Type: application/json" \
  -d '{"query":"payment webhook","kinds":["code","research","concept"]}'
```

`pull` returns `prompt_block` for injection into chat, pipeline plan, or agent plan.

---

## Data flow

```text
Project A, B, C (LLM-native folders)
  → scan → index → Redis namespace "xref"
  → multi_project ON
  → search / pull → prompt_block → agent/pipeline
  → /done → /clear (session lean; xref index retained)
```

---

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/api/xref` | State: multi_project, project registry |
| POST | `/api/xref/scan` | Scan readable paths + index |
| POST | `/api/xref/index` | Index pre-built scan payload |
| POST | `/api/xref/search` | Cross-project search |
| POST | `/api/xref/pull` | Search + `prompt_block` |

---

## Privacy constraints

| Rule | Fact |
|------|------|
| Default | multi_project off |
| Scope | Only scanned/registered projects |
| Secrets | Do not index secret-bearing sessions onto shared hosts |
