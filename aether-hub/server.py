#!/usr/bin/env python3
"""Aether Hub — capability matrix sync + shared agent memory API."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from matrix import annotate_availability, load_matrix, matrix_table, route  # noqa: E402
from memory import MemoryStore  # noqa: E402

try:
    import redis as redis_lib
except ImportError:
    redis_lib = None

HOST = os.environ.get("AETHER_HUB_HOST", "0.0.0.0")
PORT = int(os.environ.get("AETHER_HUB_PORT", "8766"))
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
SYNC_INTERVAL = int(os.environ.get("AETHER_MATRIX_SYNC_SEC", "60"))

_state_lock = threading.Lock()
_snapshot: dict = {}
_matrix_raw: dict = {}
_memory = MemoryStore(REDIS_URL)


def _redis_client():
    if redis_lib is None:
        return None
    try:
        r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def refresh_snapshot() -> dict:
    global _snapshot, _matrix_raw
    raw = load_matrix()
    snap = annotate_availability(raw)
    with _state_lock:
        _matrix_raw = raw
        _snapshot = snap
    # Persist to Redis for other agents / multi-process readers
    r = _redis_client()
    if r is not None:
        key = ((raw.get("routing") or {}).get("sync") or {}).get("redis_key") or "aether:matrix:snapshot"
        try:
            # Drop huge ollama list duplication is fine
            r.set(key, json.dumps(snap, default=str), ex=SYNC_INTERVAL * 5)
            r.set("aether:matrix:ts", str(snap.get("ts")), ex=SYNC_INTERVAL * 5)
        except Exception:
            pass
    return snap


def get_snapshot() -> dict:
    with _state_lock:
        if _snapshot:
            return _snapshot
    return refresh_snapshot()


def _bg_sync():
    while True:
        try:
            refresh_snapshot()
        except Exception as e:
            sys.stderr.write(f"[hub] sync error: {e}\n")
        time.sleep(max(15, SYNC_INTERVAL))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[hub] " + (fmt % args) + "\n")

    def _send(self, code: int, obj, content_type: str = "application/json; charset=utf-8") -> None:
        if isinstance(obj, (dict, list)):
            body = json.dumps(obj, default=str, indent=2).encode("utf-8")
        elif isinstance(obj, bytes):
            body = obj
        else:
            body = str(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        qs = parse_qs(u.query)

        if path in ("/", "/index.html"):
            self._send(200, _index_html(), "text/html; charset=utf-8")
            return
        if path == "/api/health":
            self._send(
                200,
                {
                    "ok": True,
                    "service": "aether-hub",
                    "memory": _memory.health(),
                    "matrix_ts": get_snapshot().get("ts"),
                },
            )
            return
        if path == "/api/matrix":
            self._send(200, get_snapshot())
            return
        if path == "/api/matrix/table":
            self._send(200, {"rows": matrix_table(get_snapshot())})
            return
        if path == "/api/route":
            need = []
            if qs.get("need"):
                need = [x.strip() for part in qs["need"] for x in part.split(",") if x.strip()]
            prefer = (qs.get("prefer") or ["auto"])[0]
            self._send(200, route(get_snapshot(), need=need or ["chat"], prefer=prefer))
            return
        if path == "/api/sync":
            self._send(200, refresh_snapshot())
            return
        if path.startswith("/api/memory/sessions/"):
            sid = path[len("/api/memory/sessions/") :].strip("/")
            if not sid:
                self._send(400, {"error": "session id required"})
                return
            limit = int((qs.get("limit") or ["50"])[0])
            self._send(200, {"session_id": sid, "messages": _memory.get_session(sid, limit=limit)})
            return
        if path == "/api/memory/stats":
            ns = (qs.get("namespace") or ["default"])[0]
            self._send(200, _memory.stats(ns))
            return
        self._send(404, {"error": "not found", "paths": _paths()})

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        body = self._read_json()

        if path == "/api/sync":
            self._send(200, refresh_snapshot())
            return
        if path == "/api/route":
            need = body.get("need") or ["chat"]
            if isinstance(need, str):
                need = [x.strip() for x in need.split(",") if x.strip()]
            self._send(200, route(get_snapshot(), need=need, prefer=body.get("prefer") or "auto"))
            return
        if path.startswith("/api/memory/sessions/") and path.endswith("/messages"):
            sid = path[len("/api/memory/sessions/") : -len("/messages")].strip("/")
            role = body.get("role") or "user"
            content = body.get("content") or ""
            if not content:
                self._send(400, {"error": "content required"})
                return
            msg = _memory.append_message(sid, role, content, body.get("meta"))
            # Optionally also index into vector memory
            if body.get("index", True):
                _memory.upsert_vector(
                    text=f"{role}: {content}",
                    namespace=body.get("namespace") or f"session:{sid}",
                    meta={"session_id": sid, "role": role, **(body.get("meta") or {})},
                )
            self._send(200, {"ok": True, "message": msg})
            return
        if path == "/api/memory/vectors":
            text = body.get("text") or ""
            if not text:
                self._send(400, {"error": "text required"})
                return
            res = _memory.upsert_vector(
                text=text,
                namespace=body.get("namespace") or "default",
                meta=body.get("meta"),
                id=body.get("id"),
                embedding=body.get("embedding"),
            )
            self._send(200, res)
            return
        if path == "/api/memory/search":
            q = body.get("query") or body.get("q") or ""
            if not q:
                self._send(400, {"error": "query required"})
                return
            res = _memory.search(
                query=q,
                namespace=body.get("namespace") or "default",
                top_k=int(body.get("top_k") or 5),
                embedding=body.get("embedding"),
            )
            self._send(200, res)
            return
        self._send(404, {"error": "not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        if path.startswith("/api/memory/sessions/"):
            sid = path[len("/api/memory/sessions/") :].strip("/")
            _memory.clear_session(sid)
            self._send(200, {"ok": True, "cleared": sid})
            return
        self._send(404, {"error": "not found"})


def _paths() -> list[str]:
    return [
        "/api/health",
        "/api/matrix",
        "/api/matrix/table",
        "/api/route?need=code&prefer=local",
        "/api/sync",
        "POST /api/memory/sessions/{id}/messages",
        "GET  /api/memory/sessions/{id}",
        "POST /api/memory/vectors",
        "POST /api/memory/search",
    ]


def _index_html() -> bytes:
    snap = get_snapshot()
    summary = snap.get("summary") or {}
    rows = matrix_table(snap)
    # compact HTML table
    caps = [c for c in (snap.get("capabilities") or {}).keys()]
    head = "".join(f"<th>{c}</th>" for c in caps)
    body_rows = []
    for r in rows:
        cells = "".join(
            f"<td class='{'y' if r.get(c) else 'n'}'>{'●' if r.get(c) else '·'}</td>" for c in caps
        )
        av = "ok" if r.get("available") else "off"
        body_rows.append(
            f"<tr class='{av}'><td><code>{r['model']}</code></td>"
            f"<td>{r.get('tier')}</td><td>{av}</td>{cells}</tr>"
        )
    table = "\n".join(body_rows)
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Aether Hub — matrix & memory</title>
<style>
 body{{font-family:ui-monospace,Consolas,monospace;background:#0b1020;color:#e8eefc;margin:1rem;font-size:13px}}
 h1{{font-size:1.1rem;color:#7dd3a7}} a{{color:#7aa2f7}}
 table{{border-collapse:collapse;width:100%;margin-top:.75rem}}
 th,td{{border:1px solid #243056;padding:.25rem .4rem;text-align:center}}
 th{{color:#9db0d0;font-weight:600}} td:first-child{{text-align:left}}
 tr.off{{opacity:.45}} .y{{color:#4ade80}} .n{{color:#334155}}
 .card{{background:#141b2f;border:1px solid #243056;border-radius:8px;padding:.75rem;margin:.5rem 0}}
 code{{color:#5ccfe6}}
</style></head><body>
<h1>Aether Hub · capability sync matrix</h1>
<div class="card">
 local online: <b>{summary.get('local_online')}</b> ·
 cloud ready: <b>{summary.get('cloud_ready')}</b> ·
 unavailable: <b>{summary.get('unavailable')}</b> ·
 memory: <b>{_memory.backend}</b>
 <div style="margin-top:.4rem">
  <a href="/api/matrix">/api/matrix</a> ·
  <a href="/api/route?need=code&prefer=local">/api/route?need=code</a> ·
  <a href="/api/sync">/api/sync</a> ·
  <a href="/api/health">/api/health</a>
 </div>
</div>
<table>
<thead><tr><th>model</th><th>tier</th><th>live</th>{head}</tr></thead>
<tbody>
{table}
</tbody>
</table>
<p style="color:#9db0d0;margin-top:1rem">Shared agent memory: POST /api/memory/vectors · POST /api/memory/search · sessions under /api/memory/sessions/&lt;id&gt;</p>
</body></html>"""
    return html.encode("utf-8")


def main() -> None:
    refresh_snapshot()
    t = threading.Thread(target=_bg_sync, daemon=True)
    t.start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Aether Hub → http://{HOST}:{PORT}/")
    print("  matrix:  GET /api/matrix  GET /api/route?need=code&prefer=local")
    print("  memory:  POST /api/memory/vectors  POST /api/memory/search")
    print(f"  redis:   {REDIS_URL}  backend={_memory.backend}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()


if __name__ == "__main__":
    main()
