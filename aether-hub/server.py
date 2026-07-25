#!/usr/bin/env python3
"""Aether Hub — system discover, capability matrix, shared agent memory."""
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

from agents import (  # noqa: E402
    apply_runtime_update,
    get_runtime,
    init_runtime_from_config,
    load_modes_config,
    modes_status,
    plan_event,
)
from bootstrap import (  # noqa: E402
    apply_plan,
    build_install_plan,
    get_bootstrap_state,
    plan_and_maybe_apply,
    set_bootstrap_state,
)
from combos import (  # noqa: E402
    export_combo,
    get_combo,
    guide_table,
    import_combo,
    launch_combo,
    list_combos,
    plan_with_combo,
)
from discover import full_discover, print_report_text  # noqa: E402
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
_discover: dict = {}
_host_scan: dict = {}
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


def get_host_scan() -> dict:
    with _state_lock:
        return dict(_host_scan)


def set_host_scan(data: dict) -> None:
    global _host_scan
    with _state_lock:
        _host_scan = data or {}


def run_discover(host_scan: dict | None = None) -> dict:
    global _discover
    hs = host_scan if host_scan is not None else get_host_scan()
    # Flatten flags from host scan scripts into recommendation keys
    flat = dict(hs)
    if isinstance(hs.get("flags"), dict):
        flat.update(hs["flags"])
    # Also accept nested windows-style payload
    for k in (
        "windows_ollama_and_wsl_both",
        "ollama_missing_rocm_libs",
        "localhost_11434_broken",
        "wsl_ollama_ip",
        "radeon_visible_to_rocminfo",
    ):
        if k in hs:
            flat[k] = hs[k]
    report = full_discover(host_scan=flat)
    with _state_lock:
        _discover = report
    r = _redis_client()
    if r is not None:
        try:
            r.set("aether:discover:latest", json.dumps(report, default=str), ex=SYNC_INTERVAL * 10)
        except Exception:
            pass
    return report


def refresh_snapshot() -> dict:
    """Discover first, then annotate capability matrix against live Ollama models."""
    global _snapshot, _matrix_raw
    disc = run_discover()
    raw = load_matrix()
    # Prefer primary reachable Ollama from discover
    ollama_info = None
    primary = (disc.get("ollama") or {}).get("primary")
    if primary and primary.get("reachable"):
        names = set((disc.get("ollama") or {}).get("all_model_names") or [])
        ollama_info = {
            "base": primary.get("base"),
            "ok": True,
            "models": sorted(names),
            "inference_hint": primary.get("inference_hint"),
        }
    snap = annotate_availability(raw, ollama=ollama_info)
    snap["discover_summary"] = disc.get("summary")
    snap["recommendations"] = disc.get("recommendations")
    with _state_lock:
        _matrix_raw = raw
        _snapshot = snap
    r = _redis_client()
    if r is not None:
        key = ((raw.get("routing") or {}).get("sync") or {}).get("redis_key") or "aether:matrix:snapshot"
        try:
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


def get_discover() -> dict:
    with _state_lock:
        if _discover:
            return _discover
    return run_discover()


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
            d = get_discover()
            self._send(
                200,
                {
                    "ok": True,
                    "service": "aether-hub",
                    "memory": _memory.health(),
                    "matrix_ts": get_snapshot().get("ts"),
                    "discover": d.get("summary"),
                },
            )
            return
        if path in ("/api/discover", "/api/scan"):
            force = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
            if force:
                self._send(200, run_discover())
            else:
                self._send(200, get_discover())
            return
        if path == "/api/discover/text":
            self._send(200, print_report_text(get_discover()), "text/plain; charset=utf-8")
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
        if path in ("/api/modes", "/api/agent-modes"):
            self._send(200, modes_status(get_snapshot()))
            return
        if path in ("/api/bootstrap", "/api/auto-install"):
            if (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes"):
                run_discover()
            plan = build_install_plan(get_discover())
            self._send(
                200,
                {
                    "state": get_bootstrap_state(),
                    **plan,
                },
            )
            return
        if path in ("/api/combos", "/api/combo"):
            self._send(200, list_combos())
            return
        if path == "/api/combos/guide":
            self._send(200, guide_table())
            return
        if path.startswith("/api/combos/") and path.endswith("/export"):
            cid = path[len("/api/combos/") : -len("/export")].strip("/")
            try:
                write = (qs.get("write") or ["0"])[0] in ("1", "true", "yes")
                self._send(200, export_combo(cid, write_file=write))
            except ValueError as e:
                self._send(404, {"error": str(e)})
            return
        if path.startswith("/api/combos/") and not path.endswith("/launch") and not path.endswith("/plan"):
            cid = path[len("/api/combos/") :].strip("/")
            if cid and cid not in ("import", "guide"):
                c = get_combo(cid)
                if c:
                    self._send(200, c)
                else:
                    self._send(404, {"error": f"unknown combo: {cid}"})
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

        if path in ("/api/modes", "/api/agent-modes"):
            try:
                runtime = apply_runtime_update(body or {})
                # Persist runtime to Redis for multi-replica readers
                r = _redis_client()
                if r is not None:
                    try:
                        r.set("aether:modes:runtime", json.dumps(runtime), ex=86400 * 7)
                    except Exception:
                        pass
                self._send(200, modes_status(get_snapshot()))
            except ValueError as e:
                self._send(400, {"error": str(e)})
            return
        if path in ("/api/bootstrap", "/api/auto-install"):
            st = set_bootstrap_state(body or {})
            plan = build_install_plan(get_discover())
            self._send(200, {"state": st, **plan})
            return
        if path in ("/api/bootstrap/run", "/api/auto-install/run"):
            dry = bool((body or {}).get("dry_run", False))
            confirm = bool((body or {}).get("confirm", False))
            only_safe = bool((body or {}).get("only_safe", True))
            cats = (body or {}).get("categories")
            # refresh discover first
            disc = run_discover()
            plan = build_install_plan(disc)
            run = apply_plan(
                plan,
                confirm=confirm,
                only_safe=only_safe,
                categories=cats,
                dry_run=dry,
            )
            self._send(200, {"plan": plan, "run": run, "state": get_bootstrap_state()})
            return
        if path in ("/api/combos/import", "/api/combo/import"):
            try:
                raw = body.get("combo") if isinstance(body.get("combo"), dict) else body
                self._send(200, import_combo(raw, persist=bool(body.get("persist", True))))
            except (ValueError, json.JSONDecodeError) as e:
                self._send(400, {"error": str(e)})
            return
        if path.startswith("/api/combos/") and path.endswith("/launch"):
            cid = path[len("/api/combos/") : -len("/launch")].strip("/")
            try:
                self._send(200, launch_combo(cid, get_snapshot()))
            except ValueError as e:
                self._send(404, {"error": str(e)})
            return
        if path.startswith("/api/combos/") and path.endswith("/plan"):
            cid = path[len("/api/combos/") : -len("/plan")].strip("/")
            try:
                self._send(200, plan_with_combo(cid, get_snapshot(), body or {}))
            except ValueError as e:
                self._send(404, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/api/agents/plan", "/api/agents/event"):
            try:
                plan = plan_event(get_snapshot(), body or {})
                # Store plan briefly in memory namespace for multi-agent continuity
                if body.get("remember", True):
                    _memory.upsert_vector(
                        text=json.dumps(
                            {
                                "event_id": plan.get("event_id"),
                                "mode": plan.get("mode"),
                                "models": plan.get("models_in_event") or [
                                    a.get("model") for a in plan.get("agents") or []
                                ],
                                "goal": (plan.get("goal") or {}).get("text", "")[:500],
                            }
                        ),
                        namespace="agent-events",
                        meta={"event_id": plan.get("event_id"), "mode": plan.get("mode")},
                    )
                self._send(200, plan)
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/api/discover", "/api/scan"):
            hs = body.get("host_scan") or body
            if body.get("host_scan") is not None or any(
                k in body
                for k in (
                    "windows_ollama_and_wsl_both",
                    "ollama_missing_rocm_libs",
                    "wsl_ollama_ip",
                    "flags",
                )
            ):
                set_host_scan(hs if body.get("host_scan") is not None else body)
            self._send(200, run_discover(get_host_scan()))
            return
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
        "GET  /api/discover          ← scan system first",
        "GET  /api/discover/text",
        "POST /api/discover          {host_scan: {...}}",
        "GET|POST /api/modes         ← inline|multi_agent, token_saver, role pins",
        "POST /api/agents/plan       ← multi-LLM event plan",
        "GET|POST /api/bootstrap     ← optional auto-install plan (off by default)",
        "POST /api/bootstrap/run     ← {confirm, dry_run, only_safe}",
        "GET  /api/combos            ← tiers + situation packs",
        "POST /api/combos/{id}/launch",
        "POST /api/combos/{id}/plan",
        "GET  /api/combos/{id}/export",
        "POST /api/combos/import",
        "/api/health",
        "/api/matrix",
        "/api/route?need=code&prefer=local",
        "/api/sync",
        "POST /api/memory/vectors",
        "POST /api/memory/search",
    ]


def _index_html() -> bytes:
    snap = get_snapshot()
    disc = get_discover()
    summary = snap.get("summary") or {}
    dsum = disc.get("summary") or {}
    recs = disc.get("recommendations") or []
    rows = matrix_table(snap)
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
    rec_html = "".join(
        f"<li class='sev-{r.get('severity')}'><b>{r.get('severity')}</b> — {r.get('action')}"
        f"<div class='muted'>{r.get('detail') or ''}</div></li>"
        for r in recs[:8]
    )
    ollama_eps = disc.get("ollama") or {}
    ep_html = ""
    for ep in ollama_eps.get("endpoints") or []:
        st = "up" if ep.get("reachable") else "dn"
        models = ", ".join(m.get("name", "") for m in (ep.get("models") or [])[:5]) or "—"
        ep_html += f"<div class='ep {st}'><code>{ep.get('label')}</code> {ep.get('base')} → {models}</div>"

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Aether Hub — discover · matrix · memory</title>
<style>
 body{{font-family:ui-monospace,Consolas,monospace;background:#0b1020;color:#e8eefc;margin:1rem;font-size:13px}}
 h1{{font-size:1.1rem;color:#7dd3a7}} h2{{font-size:.85rem;color:#9db0d0;margin:1rem 0 .4rem}}
 a{{color:#7aa2f7}}
 table{{border-collapse:collapse;width:100%;margin-top:.5rem}}
 th,td{{border:1px solid #243056;padding:.25rem .4rem;text-align:center}}
 th{{color:#9db0d0;font-weight:600}} td:first-child{{text-align:left}}
 tr.off{{opacity:.45}} .y{{color:#4ade80}} .n{{color:#334155}}
 .card{{background:#141b2f;border:1px solid #243056;border-radius:8px;padding:.75rem;margin:.5rem 0}}
 code{{color:#5ccfe6}} .muted{{color:#9db0d0;font-size:12px}}
 ul.rec{{margin:.3rem 0;padding-left:1.1rem}}
 .sev-high{{color:#f87171}} .sev-medium{{color:#fbbf24}} .sev-ok{{color:#4ade80}} .sev-info{{color:#9db0d0}}
 .ep{{margin:.2rem 0}} .ep.up{{color:#4ade80}} .ep.dn{{color:#64748b}}
</style></head><body>
<h1>Aether Hub · scan first, then route</h1>
<div class="card">
 <b>System scan</b> —
 Ollama: <b>{"OK" if dsum.get("ollama_ok") else "DOWN"}</b>
 ({dsum.get("ollama_models") or 0} models) ·
 LiteLLM: <b>{"OK" if dsum.get("litellm_ok") else "DOWN"}</b> ·
 Redis: <b>{"OK" if dsum.get("redis_ok") else "DOWN"}</b> ·
 cloud keys: <b>{"yes" if dsum.get("cloud_keys") else "no"}</b>
 <div class="muted" style="margin-top:.35rem">{ep_html or "No Ollama endpoints probed yet — open /api/discover"}</div>
 <div style="margin-top:.5rem">
  <a href="/api/discover">/api/discover</a> ·
  <a href="/api/discover?refresh=1">refresh</a> ·
  <a href="/api/modes">/api/modes</a> ·
  <a href="/api/combos">/api/combos</a> ·
  <a href="/api/combos/guide">guide</a> ·
  <a href="/api/matrix">matrix</a> ·
  <a href="/api/health">health</a>
 </div>
</div>
<div class="card" id="combosCard">
 <b>Combos</b> — Fable low / Sonnet / Opus / GPT · situations (coding, research, testing)
 <div class="muted" id="combosList">…</div>
 <div style="margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.35rem" id="comboBtns"></div>
 <div class="muted">Export JSON from GitHub <code>combos/export/*.aether-combo.json</code> · import via POST /api/combos/import</div>
</div>
<script>
async function refreshCombos(){{
  try {{
    const j = await fetch('/api/combos').then(r=>r.json());
    const sits = Object.keys(j.situations||{{}});
    const tiers = Object.keys(j.tiers||{{}});
    document.getElementById('combosList').textContent =
      'situations: '+sits.join(', ')+' · tiers: '+tiers.slice(0,6).join(', ')+'…';
    const box = document.getElementById('comboBtns');
    box.innerHTML = '';
    for (const id of sits.slice(0,8)) {{
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = id;
      b.onclick = () => launchCombo(id);
      box.appendChild(b);
    }}
  }} catch(e) {{
    document.getElementById('combosList').textContent = 'combos unavailable';
  }}
}}
async function launchCombo(id){{
  const j = await fetch('/api/combos/'+encodeURIComponent(id)+'/launch',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}}).then(r=>r.json());
  alert('Launched '+id+' · mode='+(j.runtime&&j.runtime.mode)+' · token_saver='+(j.runtime&&j.runtime.token_saver));
  if (typeof refreshModes==='function') refreshModes();
}}
refreshCombos();
</script>
<div class="card" id="modesCard">
 <b>Agent mode</b> · token saver (optional) · multi-LLM roles
 <div class="muted" style="margin-top:.35rem" id="modesRuntime">loading…</div>
 <div style="margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.35rem">
  <button type="button" onclick="setMode('inline')">inline</button>
  <button type="button" onclick="setMode('multi_agent')">multi-agent</button>
  <button type="button" onclick="setSaver(true)">token saver ON</button>
  <button type="button" onclick="setSaver(false)">token saver OFF</button>
  <button type="button" onclick="setPreset('thrifty')">preset: thrifty</button>
  <button type="button" onclick="setPreset('quality')">preset: quality</button>
  <button type="button" onclick="setPreset('local_only')">preset: local_only</button>
 </div>
 <div class="muted" style="margin-top:.4rem">
  Pin roles via API: mastermind / supervisor / worker by maker, tier, price, or model —
  see <a href="https://github.com/piksliviksi/aetherstack/blob/main/docs/AGENT-MODES.md">AGENT-MODES.md</a>
 </div>
</div>
<div class="card">
 <b>Auto-install</b> (optional, off by default)
 <div class="muted" id="bootState">…</div>
 <div style="margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.35rem">
  <button type="button" onclick="bootEnable(true)">enable</button>
  <button type="button" onclick="bootEnable(false)">disable</button>
  <button type="button" onclick="bootDry()">dry-run plan</button>
  <button type="button" onclick="bootApply()">apply safe</button>
 </div>
 <pre id="bootPlan" class="muted" style="white-space:pre-wrap;max-height:12rem;overflow:auto;font-size:11px"></pre>
 <div class="muted">Host full install: <code>.\\scripts\\auto-install.ps1 -Enable -Yes</code> · elevated: <code>-IncludeElevated</code></div>
</div>
<script>
async function refreshBoot(){{
  try {{
    const j = await fetch('/api/bootstrap?refresh=1').then(r=>r.json());
    const st = j.state||{{}};
    document.getElementById('bootState').textContent =
      'enabled='+st.enabled+' · actions='+j.action_count+' (safe='+j.safe_count+')';
    const lines = (j.actions||[]).slice(0,12).map(a =>
      '['+(a.safe?'safe':'elev')+'] '+a.title);
    document.getElementById('bootPlan').textContent = lines.join('\\n') || 'nothing missing';
  }} catch(e) {{
    document.getElementById('bootState').textContent = 'bootstrap unavailable';
  }}
}}
async function bootEnable(v){{
  await fetch('/api/bootstrap',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{enabled:v}})}});
  refreshBoot();
}}
async function bootDry(){{
  const j = await fetch('/api/bootstrap/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{confirm:true,dry_run:true,only_safe:true}})}}).then(r=>r.json());
  document.getElementById('bootPlan').textContent = JSON.stringify(j.run||j,null,2).slice(0,2500);
  refreshBoot();
}}
async function bootApply(){{
  if(!confirm('Apply SAFE auto-installs (pip/models via API)? Elevated host steps need auto-install.ps1 -Yes')) return;
  await fetch('/api/bootstrap',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{enabled:true}})}});
  const j = await fetch('/api/bootstrap/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{confirm:true,dry_run:false,only_safe:true}})}}).then(r=>r.json());
  document.getElementById('bootPlan').textContent = JSON.stringify(j.run||j,null,2).slice(0,2500);
  refreshBoot();
}}
refreshBoot();
</script>
<div class="card">
 <b>Do this next</b>
 <ul class="rec">{rec_html}</ul>
 <div class="muted">Host deep scan (WSL/GPU): <code>.\\scripts\\scan-system.ps1</code> or <code>./scripts/scan-system.sh</code></div>
</div>
<script>
async function refreshModes(){{
  try {{
    const j = await fetch('/api/modes').then(r=>r.json());
    const rt = j.runtime||{{}};
    const res = j.resolved_now||{{}};
    const lines = [
      'mode='+rt.mode+' · token_saver='+rt.token_saver+(rt.preset?' · preset='+rt.preset:''),
      'mastermind → '+(res.mastermind&&res.mastermind.model)+' ('+(res.mastermind&&res.mastermind.provider)+')',
      'supervisor → '+(res.supervisor&&res.supervisor.model)+' ('+(res.supervisor&&res.supervisor.provider)+')',
      'worker → '+(res.worker&&res.worker.model)+' ('+(res.worker&&res.worker.provider)+')',
      'inline → '+(res.inline&&res.inline.model)
    ];
    document.getElementById('modesRuntime').textContent = lines.join(' · ');
  }} catch(e) {{
    document.getElementById('modesRuntime').textContent = 'modes unavailable';
  }}
}}
async function postModes(body){{
  await fetch('/api/modes',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
  refreshModes();
}}
function setMode(m){{ postModes({{mode:m}}); }}
function setSaver(v){{ postModes({{token_saver:v}}); }}
function setPreset(p){{ postModes({{preset:p}}); }}
refreshModes();
</script>
<div class="card">
 matrix live: local <b>{summary.get('local_online')}</b> · cloud <b>{summary.get('cloud_ready')}</b> · down <b>{summary.get('unavailable')}</b>
 · memory <b>{_memory.backend}</b>
</div>
<h2>Capability matrix (live availability)</h2>
<table>
<thead><tr><th>model</th><th>tier</th><th>live</th>{head}</tr></thead>
<tbody>
{table}
</tbody>
</table>
<p class="muted" style="margin-top:1rem">Memory: POST /api/memory/vectors · POST /api/memory/search</p>
</body></html>"""
    return html.encode("utf-8")


def main() -> None:
    print("[hub] agent modes + token saver…")
    init_runtime_from_config()
    print(f"[hub] mode={get_runtime().get('mode')} token_saver={get_runtime().get('token_saver')}")
    print("[hub] initial system discover…")
    refresh_snapshot()
    t = threading.Thread(target=_bg_sync, daemon=True)
    t.start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Aether Hub → http://{HOST}:{PORT}/")
    print("  FIRST:  GET /api/discover")
    print("  MODES:  GET|POST /api/modes   (inline|multi_agent, token_saver)")
    print("  PLAN:   POST /api/agents/plan (multi-LLM event)")
    print("  ROUTE:  GET /api/route?need=code&prefer=local")
    print(f"  redis:  {REDIS_URL}  backend={_memory.backend}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()


if __name__ == "__main__":
    main()
