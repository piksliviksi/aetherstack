"""
Slash commands for conversation/context hygiene (Claude-style /clear, etc.).

Flow for /clear (and /compact):
  1. Check open tasks / agent events are done (unless force)
  2. Document full working context into durable memory (vectors + archive)
  3. Clear short-term session / working context so the next prompt is optimal
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Callable

from memory import MemoryStore

# In-process open tasks (also mirrored to Redis via MemoryStore sessions)
_open_tasks: dict[str, dict[str, Any]] = {}
_working: dict[str, dict[str, Any]] = {}  # session_id -> {summary, notes, last_clear, ...}

COMMANDS = {
    "/help": "List slash commands",
    "/status": "Open tasks + working-context size + memory backend",
    "/save": "Document current context into memory without clearing",
    "/clear": "When tasks done: archive to memory, then clear working context",
    "/compact": "Archive + keep a short summary in working context (soft clear)",
    "/done": "Mark a task or all tasks complete  |  /done [task_id|all]",
    "/task": "Register or list tasks  |  /task add <title>  |  /task list",
    "/context": "Show working context blob (truncated)",
}


def list_commands() -> dict[str, str]:
    return dict(COMMANDS)


def parse_slash(text: str) -> tuple[str | None, str]:
    """Return (command, args) if text is a slash command, else (None, original)."""
    if not text or not str(text).strip().startswith("/"):
        return None, text or ""
    line = str(text).strip()
    # only treat first token as command
    m = re.match(r"^(/[a-zA-Z0-9_-]+)\s*(.*)$", line, re.DOTALL)
    if not m:
        return None, text
    cmd = m.group(1).lower()
    args = (m.group(2) or "").strip()
    if cmd not in COMMANDS and cmd not in ("/clear", "/compact", "/save", "/status", "/help", "/done", "/task", "/context"):
        # unknown slash — still return so caller can 404
        return cmd, args
    return cmd, args


def register_task(
    title: str,
    *,
    session_id: str = "default",
    task_id: str | None = None,
    meta: dict | None = None,
) -> dict[str, Any]:
    tid = task_id or str(uuid.uuid4())[:8]
    t = {
        "id": tid,
        "title": title,
        "session_id": session_id,
        "status": "open",
        "created_at": time.time(),
        "meta": meta or {},
    }
    _open_tasks[tid] = t
    return t


def complete_task(task_id: str, *, note: str | None = None) -> dict[str, Any]:
    if task_id == "all":
        done = []
        for tid, t in list(_open_tasks.items()):
            if t.get("status") == "open":
                t["status"] = "done"
                t["completed_at"] = time.time()
                if note:
                    t["completion_note"] = note
                done.append(t)
        return {"completed": done, "count": len(done)}
    t = _open_tasks.get(task_id)
    if not t:
        raise ValueError(f"unknown task: {task_id}")
    t["status"] = "done"
    t["completed_at"] = time.time()
    if note:
        t["completion_note"] = note
    return t


def open_tasks(session_id: str | None = None) -> list[dict[str, Any]]:
    out = []
    for t in _open_tasks.values():
        if t.get("status") != "open":
            continue
        if session_id and t.get("session_id") != session_id:
            continue
        out.append(t)
    return out


def _working_key(session_id: str) -> str:
    return session_id or "default"


def get_working(session_id: str = "default") -> dict[str, Any]:
    return dict(_working.get(_working_key(session_id)) or {})


def set_working(session_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    k = _working_key(session_id)
    cur = _working.setdefault(k, {"session_id": k, "notes": [], "summary": ""})
    cur.update(patch)
    cur["updated_at"] = time.time()
    return dict(cur)


def append_working_note(session_id: str, note: str) -> None:
    k = _working_key(session_id)
    cur = _working.setdefault(k, {"session_id": k, "notes": [], "summary": ""})
    cur.setdefault("notes", []).append({"ts": time.time(), "text": note})
    cur["notes"] = cur["notes"][-100:]
    cur["updated_at"] = time.time()


def _build_archive_document(
    session_id: str,
    mem: MemoryStore,
    *,
    reason: str,
    extra: dict | None = None,
) -> str:
    messages = mem.get_session(session_id, limit=200)
    working = get_working(session_id)
    tasks = [t for t in _open_tasks.values() if t.get("session_id") == session_id]
    done = [t for t in tasks if t.get("status") == "done"]
    open_ = [t for t in tasks if t.get("status") == "open"]

    parts = [
        f"# Aether conversation archive",
        f"session: {session_id}",
        f"reason: {reason}",
        f"archived_at: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
        "## Working summary",
        working.get("summary") or "(none)",
        "",
        "## Notes",
    ]
    for n in working.get("notes") or []:
        parts.append(f"- {n.get('text')}")
    parts.append("")
    parts.append("## Tasks")
    for t in done:
        parts.append(f"- [done] {t.get('id')}: {t.get('title')}")
    for t in open_:
        parts.append(f"- [open] {t.get('id')}: {t.get('title')}")
    parts.append("")
    parts.append("## Messages")
    for m in messages:
        role = m.get("role") or "?"
        content = (m.get("content") or "")[:4000]
        parts.append(f"### {role}")
        parts.append(content)
        parts.append("")
    if extra:
        parts.append("## Extra")
        parts.append(json.dumps(extra, default=str, indent=2)[:3000])
    return "\n".join(parts)


def archive_to_memory(
    session_id: str,
    mem: MemoryStore,
    *,
    reason: str = "manual_save",
    namespace: str | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Persist full context into vector + session meta before clear."""
    ns = namespace or f"archive:{session_id}"
    doc = _build_archive_document(session_id, mem, reason=reason, extra=extra)
    # durable vector for later /search
    vec = mem.upsert_vector(
        text=doc[:12000],
        namespace=ns,
        meta={
            "kind": "conversation_archive",
            "session_id": session_id,
            "reason": reason,
            "ts": time.time(),
        },
    )
    # also a short sticky note in default memory for recall
    summary = get_working(session_id).get("summary") or ""
    if not summary and doc:
        # first 500 chars of archive as breadcrumb
        summary = f"Archive {reason} @ {time.strftime('%Y-%m-%d %H:%M')} session={session_id}"
    sticky = mem.upsert_vector(
        text=summary or f"Cleared session {session_id} ({reason})",
        namespace="conversation-index",
        meta={"session_id": session_id, "reason": reason, "archive_ns": ns, "archive_id": vec.get("id")},
    )
    # log event on session stream
    mem.append_message(
        session_id,
        "system",
        f"[archive] reason={reason} archive_id={vec.get('id')} chars={len(doc)}",
        meta={"kind": "archive", "archive_id": vec.get("id")},
    )
    return {
        "archive_id": vec.get("id"),
        "namespace": ns,
        "index_id": sticky.get("id"),
        "chars": len(doc),
        "backend": mem.backend,
    }


def cmd_clear(
    session_id: str,
    mem: MemoryStore,
    *,
    force: bool = False,
    keep_summary: bool = False,
) -> dict[str, Any]:
    """
    Claude-like /clear:
      - refuse if open tasks remain (unless force)
      - document everything into memory
      - clear session messages + working notes
      - optionally keep a one-line summary for optimal continuity
    """
    open_ = open_tasks(session_id)
    if open_ and not force:
        return {
            "ok": False,
            "command": "/clear",
            "error": "open_tasks",
            "message": "Finish or /done tasks before /clear (or use /clear force).",
            "open_tasks": open_,
            "hint": "POST /api/slash {\"text\":\"/done all\"} then /clear",
        }

    archive = archive_to_memory(session_id, mem, reason="clear" if not keep_summary else "compact")
    prev_summary = get_working(session_id).get("summary") or ""
    mem.clear_session(session_id)

    # reset working context
    new_working = {
        "session_id": session_id,
        "notes": [],
        "summary": (
            (prev_summary[:400] if keep_summary and prev_summary else "")
            or f"Context cleared; full history in memory archive {archive.get('archive_id')}"
        ),
        "last_clear_at": time.time(),
        "last_archive_id": archive.get("archive_id"),
        "last_archive_ns": archive.get("namespace"),
    }
    _working[_working_key(session_id)] = new_working

    # seed session with system marker for clients
    mem.append_message(
        session_id,
        "system",
        (
            "[/clear] Working context reset. Prior work is stored in agent memory "
            f"(archive={archive.get('archive_id')}, ns={archive.get('namespace')}). "
            "Recall via POST /api/memory/search namespace=conversation-index or archive ns."
        ),
        meta={"kind": "clear", "archive": archive},
    )

    return {
        "ok": True,
        "command": "/compact" if keep_summary else "/clear",
        "session_id": session_id,
        "archived": archive,
        "working": new_working,
        "context_optimal": True,
        "message": "Documented in memory and cleared working context.",
    }


def cmd_save(session_id: str, mem: MemoryStore, note: str = "") -> dict[str, Any]:
    if note:
        append_working_note(session_id, note)
    archive = archive_to_memory(session_id, mem, reason="save", extra={"note": note} if note else None)
    return {
        "ok": True,
        "command": "/save",
        "session_id": session_id,
        "archived": archive,
        "message": "Context documented in memory; working context kept.",
    }


def cmd_status(session_id: str, mem: MemoryStore) -> dict[str, Any]:
    msgs = mem.get_session(session_id, limit=500)
    working = get_working(session_id)
    return {
        "ok": True,
        "command": "/status",
        "session_id": session_id,
        "open_tasks": open_tasks(session_id),
        "message_count": len(msgs),
        "working": working,
        "memory": mem.health(),
        "can_clear": len(open_tasks(session_id)) == 0,
    }


def execute_slash(
    text: str,
    mem: MemoryStore,
    *,
    session_id: str = "default",
) -> dict[str, Any]:
    """
    Execute a slash command string. Returns structured result.
    Non-slash text is not handled here (return not_a_command).
    """
    cmd, args = parse_slash(text)
    if not cmd:
        return {"ok": False, "not_a_command": True, "text": text}

    if cmd == "/help":
        return {"ok": True, "command": "/help", "commands": list_commands()}

    if cmd == "/status":
        return cmd_status(session_id, mem)

    if cmd == "/context":
        w = get_working(session_id)
        msgs = mem.get_session(session_id, limit=20)
        return {
            "ok": True,
            "command": "/context",
            "working": w,
            "recent_messages": [
                {"role": m.get("role"), "content": (m.get("content") or "")[:500]} for m in msgs[-10:]
            ],
        }

    if cmd == "/save":
        return cmd_save(session_id, mem, note=args)

    if cmd == "/clear":
        force = args.lower() in ("force", "--force", "-f", "now")
        return cmd_clear(session_id, mem, force=force, keep_summary=False)

    if cmd == "/compact":
        force = "force" in args.lower()
        # always keep summary line
        r = cmd_clear(session_id, mem, force=force, keep_summary=True)
        r["command"] = "/compact"
        return r

    if cmd == "/done":
        tid = args.split()[0] if args else ""
        if not tid:
            return {
                "ok": False,
                "command": "/done",
                "error": "usage: /done <task_id|all>",
                "open_tasks": open_tasks(session_id),
            }
        note = " ".join(args.split()[1:]) if len(args.split()) > 1 else None
        try:
            result = complete_task(tid if tid != "all" else "all", note=note)
        except ValueError as e:
            return {"ok": False, "command": "/done", "error": str(e)}
        # auto-archive progress when all session tasks done
        remaining = open_tasks(session_id)
        auto = None
        if not remaining:
            auto = archive_to_memory(
                session_id,
                mem,
                reason="tasks_complete",
                extra={"completed": result},
            )
            append_working_note(session_id, "All tasks marked done; progress archived to memory.")
        return {
            "ok": True,
            "command": "/done",
            "result": result,
            "remaining_open": remaining,
            "auto_archived": auto,
            "ready_for_clear": len(remaining) == 0,
            "hint": "/clear" if not remaining else "finish remaining tasks then /clear",
        }

    if cmd == "/task":
        parts = args.split(maxsplit=1)
        sub = (parts[0] if parts else "list").lower()
        if sub in ("list", "ls", ""):
            return {
                "ok": True,
                "command": "/task",
                "open": open_tasks(session_id),
                "all": [t for t in _open_tasks.values() if t.get("session_id") == session_id][-20:],
            }
        if sub == "add":
            title = parts[1] if len(parts) > 1 else "untitled"
            t = register_task(title, session_id=session_id)
            mem.append_message(session_id, "system", f"[task] opened {t['id']}: {title}", meta={"task": t})
            return {"ok": True, "command": "/task", "added": t}
        return {"ok": False, "command": "/task", "error": "usage: /task list | /task add <title>"}

    return {
        "ok": False,
        "command": cmd,
        "error": "unknown_command",
        "commands": list_commands(),
    }


def maybe_handle_message(
    text: str,
    mem: MemoryStore,
    *,
    session_id: str = "default",
    store_user: bool = True,
) -> dict[str, Any]:
    """
    If text is a slash command, execute it (optionally still log user line).
    If not, append as normal user message to session working memory.
    """
    cmd, _ = parse_slash(text)
    if cmd:
        if store_user:
            mem.append_message(session_id, "user", text, meta={"slash": True})
        result = execute_slash(text, mem, session_id=session_id)
        # log system reply for slash outcome
        mem.append_message(
            session_id,
            "system",
            json.dumps(
                {
                    "slash_result": result.get("command") or cmd,
                    "ok": result.get("ok"),
                    "message": result.get("message") or result.get("error"),
                },
                default=str,
            )[:2000],
            meta={"slash_result": True},
        )
        return result

    if store_user and text:
        mem.append_message(session_id, "user", text)
        append_working_note(session_id, text[:200])
    return {"ok": True, "not_a_command": True, "stored": bool(text)}
