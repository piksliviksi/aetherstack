"""
Cross-project memory: scan LLM-native folders across projects, index session/chat
history, enable multi-project mode to pull concepts/code/research into the active work.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from memory import MemoryStore
from privacy import is_project_private

# Known LLM-native / agent artifact locations (relative to project root)
LLM_NATIVE_DIRS = [
    (".continue", "continue", "chat"),
    (".claude", "claude", "session"),
    (".cursor", "cursor", "session"),
    (".aider", "aider", "chat"),
    (".waylog", "waylog", "chat"),
    (".aetherstack", "aetherstack", "research"),
    (".codex", "codex", "session"),
    (".windsurf", "windsurf", "session"),
    (".gemini", "gemini", "session"),
    (".grok", "grok", "session"),
    ("docs", "docs", "research"),
]

LLM_NATIVE_FILES = [
    ("aider.chat.history.md", "aider", "chat"),
    (".aider.chat.history.md", "aider", "chat"),
    ("CHAT.md", "chatmd", "chat"),
    ("AGENTS.md", "agents", "research"),
]

KIND_TAGS = ("chat", "session", "code", "research", "concept", "test")

XREF_NS = "xref"  # global cross-project vector namespace
XREF_INDEX = "xref-index"  # project registry meta

_state: dict[str, Any] = {
    "multi_project": False,
    "auto_pull": True,
    "max_pull": 8,
    "projects": {},  # id -> {path, name, last_scan, source_counts}
    "updated_at": None,
}


def get_xref_state() -> dict[str, Any]:
    return {
        **_state,
        "project_count": len(_state.get("projects") or {}),
        "multi_project": bool(_state.get("multi_project")),
        "auto_pull": bool(_state.get("auto_pull", True)),
    }


def set_xref_state(patch: dict[str, Any]) -> dict[str, Any]:
    if "multi_project" in patch and patch["multi_project"] is not None:
        _state["multi_project"] = bool(patch["multi_project"])
    if "auto_pull" in patch and patch["auto_pull"] is not None:
        _state["auto_pull"] = bool(patch["auto_pull"])
    if "max_pull" in patch and patch["max_pull"] is not None:
        _state["max_pull"] = max(1, min(30, int(patch["max_pull"])))
    if "register_project" in patch and isinstance(patch["register_project"], dict):
        reg = patch["register_project"]
        pid = reg.get("id") or _project_id(reg.get("path") or reg.get("name") or str(uuid.uuid4()))
        _state.setdefault("projects", {})[pid] = {
            **(_state.get("projects") or {}).get(pid, {}),
            **reg,
            "id": pid,
        }
    if patch.get("unregister_project"):
        _state.setdefault("projects", {}).pop(str(patch["unregister_project"]), None)
    _state["updated_at"] = time.time()
    return get_xref_state()


def _project_id(path_or_name: str) -> str:
    h = hashlib.sha256(path_or_name.encode("utf-8", errors="replace")).hexdigest()[:12]
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(path_or_name).name or "proj")[:24]
    return f"{base}-{h}"


def _classify_text(text: str, hint_kind: str) -> str:
    t = (text or "").lower()
    if hint_kind in KIND_TAGS and hint_kind != "session":
        # refine
        pass
    if re.search(r"\b(test|pytest|spec|assert|coverage)\b", t):
        return "test"
    if re.search(r"```|def |class |function |import |export |const |fn ", t):
        return "code"
    if re.search(r"\b(research|rfc|design|architecture|findings|survey)\b", t):
        return "research"
    if re.search(r"\b(concept|pattern|approach|we decided|decision)\b", t):
        return "concept"
    if hint_kind in ("chat", "session"):
        return "chat" if "user" in t or "assistant" in t else hint_kind
    return hint_kind if hint_kind in KIND_TAGS else "session"


def _read_text_file(path: Path, max_bytes: int = 80_000) -> str:
    try:
        data = path.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def scan_project_tree(
    root: str | Path,
    *,
    max_files: int = 80,
    max_file_bytes: int = 60_000,
) -> dict[str, Any]:
    """
    Walk one project for LLM-native folders/files and extract readable chunks.
    Safe for host-side use; hub may receive results via API if paths aren't mounted.
    """
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        return {"error": f"not a directory: {root}", "path": str(root)}

    pid = _project_id(str(root))
    if is_project_private(project_id=pid, path=str(root)):
        return {
            "error": "project_private",
            "message": "Project is in private state; excluded from cross-project index.",
            "path": str(root),
            "project_id": pid,
            "chunk_count": 0,
            "chunks": [],
            "sources": [],
            "private": True,
        }
    chunks: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    file_count = 0

    for rel, tool, kind in LLM_NATIVE_DIRS:
        p = root / rel
        if not p.exists():
            continue
        files: list[Path] = []
        if p.is_file():
            files = [p]
        else:
            try:
                for fp in p.rglob("*"):
                    if not fp.is_file():
                        continue
                    if fp.suffix.lower() in (
                        ".md",
                        ".json",
                        ".jsonl",
                        ".txt",
                        ".yml",
                        ".yaml",
                        ".log",
                    ) or fp.name.endswith(".md"):
                        files.append(fp)
                    if len(files) >= 40:
                        break
            except OSError:
                continue
        sources.append({"tool": tool, "path": str(p), "files": len(files), "kind": kind})
        for fp in files[:40]:
            if file_count >= max_files:
                break
            text = _read_text_file(fp, max_file_bytes)
            if len(text.strip()) < 40:
                continue
            file_count += 1
            kind2 = _classify_text(text, kind)
            # split large files into windows
            window = 3500
            for i in range(0, min(len(text), max_file_bytes), window):
                piece = text[i : i + window]
                if len(piece.strip()) < 40:
                    continue
                chunks.append(
                    {
                        "project_id": pid,
                        "project_path": str(root),
                        "project_name": root.name,
                        "tool": tool,
                        "kind": kind2,
                        "rel_path": str(fp.relative_to(root)).replace("\\", "/"),
                        "mtime": fp.stat().st_mtime if fp.exists() else None,
                        "text": piece,
                        "offset": i,
                    }
                )
                if len(chunks) >= max_files * 2:
                    break

    for name, tool, kind in LLM_NATIVE_FILES:
        fp = root / name
        if not fp.is_file():
            continue
        text = _read_text_file(fp, max_file_bytes)
        if len(text.strip()) < 40:
            continue
        sources.append({"tool": tool, "path": str(fp), "files": 1, "kind": kind})
        kind2 = _classify_text(text, kind)
        chunks.append(
            {
                "project_id": pid,
                "project_path": str(root),
                "project_name": root.name,
                "tool": tool,
                "kind": kind2,
                "rel_path": name,
                "mtime": fp.stat().st_mtime,
                "text": text[:max_file_bytes],
                "offset": 0,
            }
        )

    # Also pull aetherstack overview if present
    ov = root / ".aetherstack" / "project-overview.md"
    if ov.is_file():
        text = _read_text_file(ov, 40_000)
        chunks.append(
            {
                "project_id": pid,
                "project_path": str(root),
                "project_name": root.name,
                "tool": "aetherstack",
                "kind": "research",
                "rel_path": ".aetherstack/project-overview.md",
                "mtime": ov.stat().st_mtime,
                "text": text,
                "offset": 0,
            }
        )

    return {
        "project_id": pid,
        "path": str(root),
        "name": root.name,
        "sources": sources,
        "chunk_count": len(chunks),
        "chunks": chunks,
        "scanned_at": time.time(),
    }


def index_scan(
    mem: MemoryStore,
    scan: dict[str, Any],
    *,
    replace_project: bool = True,
) -> dict[str, Any]:
    """Index scan chunks into xref vector memory."""
    pid = scan.get("project_id") or _project_id(scan.get("path") or "unknown")
    if is_project_private(project_id=pid, path=scan.get("path")):
        return {
            "ok": False,
            "error": "project_private",
            "message": "Private projects are never written to the common xref pool.",
            "project_id": pid,
            "indexed": 0,
            "private": True,
        }
    chunks = scan.get("chunks") or []
    indexed = 0
    kinds: dict[str, int] = {}

    # registry
    set_xref_state(
        {
            "register_project": {
                "id": pid,
                "path": scan.get("path"),
                "name": scan.get("name") or Path(scan.get("path") or pid).name,
                "last_scan": time.time(),
                "chunk_count": len(chunks),
                "sources": scan.get("sources") or [],
            }
        }
    )

    for ch in chunks:
        kind = ch.get("kind") or "session"
        kinds[kind] = kinds.get(kind, 0) + 1
        header = (
            f"[project={ch.get('project_name')} tool={ch.get('tool')} kind={kind} "
            f"file={ch.get('rel_path')}]\n"
        )
        text = header + (ch.get("text") or "")
        vid = hashlib.sha256(
            f"{pid}:{ch.get('rel_path')}:{ch.get('offset')}".encode()
        ).hexdigest()[:24]
        mem.upsert_vector(
            text=text[:8000],
            namespace=XREF_NS,
            id=vid,
            meta={
                "project_id": pid,
                "project_name": ch.get("project_name"),
                "project_path": ch.get("project_path"),
                "tool": ch.get("tool"),
                "kind": kind,
                "rel_path": ch.get("rel_path"),
                "mtime": ch.get("mtime"),
            },
        )
        # also per-project namespace for scoped search
        mem.upsert_vector(
            text=text[:8000],
            namespace=f"{XREF_NS}:proj:{pid}",
            id=vid,
            meta={
                "project_id": pid,
                "kind": kind,
                "tool": ch.get("tool"),
                "rel_path": ch.get("rel_path"),
            },
        )
        indexed += 1

    # index card
    mem.upsert_vector(
        text=(
            f"Project {scan.get('name')} at {scan.get('path')} "
            f"indexed {indexed} chunks kinds={kinds} tools="
            f"{sorted({s.get('tool') for s in (scan.get('sources') or [])})}"
        ),
        namespace=XREF_INDEX,
        id=f"projcard-{pid}",
        meta={"project_id": pid, "kinds": kinds, "path": scan.get("path")},
    )

    return {
        "ok": True,
        "project_id": pid,
        "indexed": indexed,
        "kinds": kinds,
        "multi_project": _state.get("multi_project"),
    }


def cross_search(
    mem: MemoryStore,
    query: str,
    *,
    kinds: list[str] | None = None,
    project_ids: list[str] | None = None,
    top_k: int = 10,
    require_multi: bool = True,
) -> dict[str, Any]:
    """Search across projects when multi_project mode is on (or force)."""
    if require_multi and not _state.get("multi_project"):
        return {
            "ok": False,
            "error": "multi_project_off",
            "message": "Enable multi-project mode: POST /api/xref {\"multi_project\": true}",
            "hits": [],
        }

    res = mem.search(query, namespace=XREF_NS, top_k=max(top_k * 3, 15))
    hits = []
    kind_set = set(kinds) if kinds else None
    proj_set = set(project_ids) if project_ids else None

    for h in res.get("hits") or []:
        # meta may be nested — search returns text; re-load not available, parse header
        meta = h.get("meta") or {}
        # if meta empty, try parse from text header
        text = h.get("text") or ""
        if not meta and text.startswith("[project="):
            m = re.match(
                r"\[project=(.*?) tool=(.*?) kind=(.*?) file=(.*?)\]",
                text.split("\n", 1)[0],
            )
            if m:
                meta = {
                    "project_name": m.group(1),
                    "tool": m.group(2),
                    "kind": m.group(3),
                    "rel_path": m.group(4),
                }
        kind = meta.get("kind")
        pid = meta.get("project_id")
        if kind_set and kind not in kind_set:
            continue
        if proj_set and pid not in proj_set:
            continue
        hits.append(
            {
                "score": h.get("score"),
                "kind": kind,
                "project_id": pid,
                "project_name": meta.get("project_name"),
                "project_path": meta.get("project_path"),
                "tool": meta.get("tool"),
                "rel_path": meta.get("rel_path"),
                "excerpt": (h.get("text") or "")[:1200],
                "id": h.get("id"),
            }
        )
        if len(hits) >= top_k:
            break

    return {
        "ok": True,
        "query": query,
        "multi_project": True,
        "hits": hits,
        "scanned_namespace": XREF_NS,
        "projects_registered": list((_state.get("projects") or {}).keys()),
    }


def pull_context(
    mem: MemoryStore,
    query: str,
    *,
    kinds: list[str] | None = None,
    top_k: int | None = None,
    as_prompt_block: bool = True,
) -> dict[str, Any]:
    """
    Pull cross-project concepts/code/research for injection into the active session.
    """
    k = top_k or int(_state.get("max_pull") or 8)
    kinds = kinds or ["concept", "code", "research", "test", "chat"]
    sr = cross_search(mem, query, kinds=kinds, top_k=k, require_multi=True)
    if not sr.get("ok"):
        return sr

    hits = sr.get("hits") or []
    if not hits:
        return {
            "ok": True,
            "query": query,
            "hits": [],
            "prompt_block": "",
            "message": "No cross-project hits (index projects first, enable multi_project).",
        }

    lines = [
        "### Cross-project memory (auto-pulled)",
        f"Query: {query}",
        "Use only if relevant; prefer already tested concepts from other projects.",
        "",
    ]
    for i, h in enumerate(hits, 1):
        lines.append(
            f"#### [{i}] {h.get('project_name')} · {h.get('kind')} · {h.get('tool')} · `{h.get('rel_path')}`"
        )
        lines.append(f"score={h.get('score')}")
        # strip header line from excerpt for cleanliness
        ex = h.get("excerpt") or ""
        if ex.startswith("[project="):
            ex = ex.split("\n", 1)[-1]
        lines.append(ex[:900])
        lines.append("")

    block = "\n".join(lines) if as_prompt_block else ""
    return {
        "ok": True,
        "query": query,
        "hit_count": len(hits),
        "hits": hits,
        "prompt_block": block,
        "message": f"Pulled {len(hits)} cross-project snippets.",
    }


def scan_and_index_paths(
    mem: MemoryStore,
    paths: list[str],
    **scan_kw: Any,
) -> dict[str, Any]:
    results = []
    for p in paths:
        scan = scan_project_tree(p, **scan_kw)
        if scan.get("error"):
            results.append(scan)
            continue
        idx = index_scan(mem, scan)
        results.append({**idx, "path": p, "name": scan.get("name")})
    return {
        "ok": True,
        "multi_project": _state.get("multi_project"),
        "results": results,
        "state": get_xref_state(),
    }
