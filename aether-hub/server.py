#!/usr/bin/env python3
"""Aether Hub — system discover, capability matrix, shared agent memory."""
from __future__ import annotations

import html as html_lib
import json
import os
import queue
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
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
from services import (  # noqa: E402
    activate_service,
    build_auto_graph,
    build_service_graph,
    classify_service,
    default_service_id,
    describe_auto_mode,
    execute_auto,
    execute_service,
    list_services,
    plan_service,
    save_service_graph,
    save_auto_graph,
    set_auto_order,
    RunCancelled,
)
from first_run import reset as first_run_reset  # noqa: E402
from first_run import run as first_run_run  # noqa: E402
from first_run import status as first_run_status  # noqa: E402
from update import stage_update, update_status  # noqa: E402
from discover import full_discover, print_report_text  # noqa: E402
from matrix import (  # noqa: E402
    annotate_availability,
    load_matrix,
    matrix_table,
    merge_host_cli_models,
    probe_host_cli_bridge,
    route,
)
try:
    import gdpr  # noqa: E402
except ImportError:  # optional WIP / operator module
    gdpr = None  # type: ignore
import auth as hub_auth  # noqa: E402
import tenancy  # noqa: E402
from memory import MemoryStore  # noqa: E402
from inference_runtime import snapshot as hub_inference_snapshot  # noqa: E402
from graph import (  # noqa: E402
    auto_connect,
    best_practice_template,
    graph_to_pipeline,
    list_graphs,
    load_graph,
    node_types,
    pipeline_to_graph,
    plan_graph,
    save_graph,
)
from graph_exec import GraphExecutionError, GraphRunCancelled, execute_graph  # noqa: E402
from preset_script import PresetScriptError, graph_to_preset_script, preset_script_to_graph  # noqa: E402
from pipelines import (  # noqa: E402
    export_pipeline,
    get_pipeline,
    import_pipeline,
    list_pipelines,
    plan_pipeline,
    ranking,
    vote,
)
from slash_commands import (  # noqa: E402
    cmd_status,
    execute_slash,
    list_commands,
    maybe_handle_message,
    register_task,
)
from cross_memory import (  # noqa: E402
    cross_search,
    get_xref_state,
    index_scan,
    pull_context,
    scan_and_index_paths,
    set_xref_state,
)
from privacy import (  # noqa: E402
    apply_privacy_patch,
    force_private_namespace,
    get_privacy_state,
    is_common_namespace,
    is_session_private,
    load_from_redis as privacy_load_redis,
    private_session_key,
    redact_log,
    resolve_private_context,
)
from backup import (  # noqa: E402
    get_backup_status,
    list_local_backups,
    run_auto_if_due,
    run_backup,
    set_auto_config,
)
from openai_gateway import (  # noqa: E402
    GatewayError,
    authorized as gateway_authorized,
    chat_completion as gateway_chat_completion,
    error_body as gateway_error_body,
    model_list as gateway_model_list,
    stream_bytes as gateway_stream_bytes,
)

try:
    import redis as redis_lib
except ImportError:
    redis_lib = None

HOST = os.environ.get("AETHER_HUB_HOST", "127.0.0.1")
PORT = int(os.environ.get("AETHER_HUB_PORT", "8766"))
PUBLIC_BIND_HOST = os.environ.get("AETHER_PUBLIC_BIND_HOST", "127.0.0.1").strip().lower()
WORKSPACE_WRITE_TOKEN = os.environ.get("LITELLM_MASTER_KEY", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
SYNC_INTERVAL = int(os.environ.get("AETHER_MATRIX_SYNC_SEC", "60"))
MAX_JSON_BODY = int(os.environ.get("AETHER_MAX_JSON_BODY", str(12 * 1024 * 1024)))
MAX_INFERENCE_STATUS_BYTES = 64 * 1024
try:
    MAX_REQUEST_THREADS = max(8, min(512, int(os.environ.get("AETHER_MAX_REQUEST_THREADS", "64"))))
except ValueError:
    MAX_REQUEST_THREADS = 64
CORS_ORIGINS = {
    item.strip().rstrip("/")
    for item in os.environ.get("AETHER_CORS_ORIGINS", "").split(",")
    if item.strip()
}

_ERROR_CODES = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "request_too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
    500: "internal_error",
    502: "upstream_error",
    503: "service_unavailable",
    504: "upstream_timeout",
}


def _public_error_payload(status: int, value: Any, request_id: str) -> Any:
    """Attach stable recovery metadata and keep internal failures out of clients."""
    if not isinstance(value, dict) or not isinstance(value.get("error"), str):
        return value
    result = dict(value)
    result.setdefault("code", _ERROR_CODES.get(status, "request_failed"))
    result.setdefault("request_id", request_id)
    if status >= 500:
        result["error"] = {
            502: "An upstream model or service failed.",
            503: "A required AetherStack service is unavailable.",
            504: "An upstream model or service timed out.",
        }.get(status, "AetherStack could not complete the request.")
    return result


def _request_origin_allowed(origin: str | None, host: str) -> bool:
    """Allow CLI requests and same-origin/configured browser requests only."""
    if not origin:
        return True
    parsed = urlparse(origin)
    normalized = origin.rstrip("/")
    return (
        parsed.scheme in ("http", "https")
        and (parsed.netloc == host or normalized in CORS_ORIGINS)
    )


def _validate_public_binding(host: str = PUBLIC_BIND_HOST) -> None:
    normalized = host.strip().lower().strip("[]")
    if normalized in {"127.0.0.1", "localhost", "::1", ""}:
        return
    if hub_auth.allow_non_loopback_bind():
        sys.stderr.write(
            "[hub] non-loopback bind allowed because AETHER_REQUIRE_AUTH is enabled "
            f"(AETHER_EDITION={hub_auth.edition()})\n"
        )
        return
    raise RuntimeError(
        "Aether Hub cannot be published beyond loopback until authenticated control-plane "
        "APIs are enabled (set AETHER_REQUIRE_AUTH=1 or AETHER_EDITION=team|cloud)"
    )

_state_lock = threading.Lock()
_snapshot: dict = {}
_matrix_raw: dict = {}
_discover: dict = {}
_host_scan: dict = {}
_memory = MemoryStore(REDIS_URL)

# Broadcast bus for live node-status events: execute_service/execute_auto's
# existing on_status callback (phase/model updates originally built just for
# the calling chat window) is fanned out here too, so any other client — the
# node graph canvas open in another tab — can subscribe over SSE and light up
# the matching node in real time, without a second parallel status mechanism.
_stage_lock = threading.Lock()
_stage_subscribers: list["queue.Queue"] = []
_sync_health_lock = threading.Lock()
_sync_health: dict[str, Any] = {
    "last_cycle": None,
    "last_success": None,
    "last_error": None,
    "redis_ok": None,
}


def _update_sync_health(**changes: Any) -> None:
    with _sync_health_lock:
        _sync_health.update(changes)


def _get_sync_health() -> dict[str, Any]:
    with _sync_health_lock:
        value = dict(_sync_health)
    last_cycle = value.get("last_cycle")
    value["stale"] = bool(last_cycle and time.time() - float(last_cycle) > max(45, SYNC_INTERVAL * 3))
    return value


def _stage_subscribe() -> "queue.Queue":
    q: "queue.Queue" = queue.Queue(maxsize=200)
    with _stage_lock:
        _stage_subscribers.append(q)
    return q


def _stage_unsubscribe(q: "queue.Queue") -> None:
    with _stage_lock:
        if q in _stage_subscribers:
            _stage_subscribers.remove(q)


# A client-visible run_id -> cancel flag, so switching presets/services mid-run
# (or an explicit Cancel click) can actually stop the server-side work instead
# of only hiding it client-side. Runs register themselves for their duration
# and are always removed in a `finally`, so this cannot grow unbounded.
_run_cancel_lock = threading.Lock()
_run_cancel_flags: dict[str, bool] = {}


def _register_run(run_id: str) -> None:
    with _run_cancel_lock:
        _run_cancel_flags[run_id] = False


def _unregister_run(run_id: str) -> None:
    with _run_cancel_lock:
        _run_cancel_flags.pop(run_id, None)


def _cancel_run(run_id: str) -> bool:
    with _run_cancel_lock:
        if run_id not in _run_cancel_flags:
            return False
        _run_cancel_flags[run_id] = True
        return True


def _make_cancel_check(run_id: str):
    def check() -> bool:
        with _run_cancel_lock:
            return bool(_run_cancel_flags.get(run_id))
    return check


def _stage_publish(event: dict) -> None:
    with _stage_lock:
        subs = list(_stage_subscribers)
    for q in subs:
        try:
            q.put_nowait(event)
        except queue.Full:
            pass


def _redis_client():
    if redis_lib is None:
        return None
    try:
        r = redis_lib.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1.5,
            socket_timeout=3,
        )
        r.ping()
        return r
    except Exception:
        return None


# Restore privacy registry from Redis (after helper is defined)
try:
    privacy_load_redis(_redis_client())
except Exception:
    pass


def get_host_scan() -> dict:
    with _state_lock:
        return dict(_host_scan)


def set_host_scan(data: dict) -> None:
    global _host_scan
    with _state_lock:
        _host_scan = data or {}


def _load_host_scan_file() -> dict:
    """Load last host scan written by scripts/scan-system.* if present."""
    candidates = [
        Path("/host-aetherstack/system-scan.json"),
        Path("/aetherstack/system-scan.json"),
        ROOT.parent / ".aetherstack" / "system-scan.json",
        ROOT / "data" / "system-scan.json",
    ]
    for p in candidates:
        try:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def get_inference_status(status_path: Path | None = None) -> tuple[int, dict]:
    """Merge privacy-minimal LiteLLM and Hub/host-CLI activity state."""
    path = status_path or Path(
        os.environ.get(
            "AETHER_INFERENCE_STATUS_PATH",
            "/host-aetherstack/inference-status.json",
        )
    )
    try:
        if path.stat().st_size > MAX_INFERENCE_STATUS_BYTES:
            raise ValueError("status file exceeds size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("status must be an object")
        active = value.get("active")
        if not isinstance(active, list) or len(active) > 256:
            raise ValueError("active status is invalid")
        clean_active = []
        for entry in active:
            if not isinstance(entry, dict):
                raise ValueError("active entry is invalid")
            clean_active.append(
                {
                    "callId": str(entry.get("callId", ""))[:256],
                    "model": str(entry.get("model", "unknown"))[:256],
                    "source": "litellm",
                    "startedAt": entry.get("startedAt"),
                }
            )
        last = value.get("last")
        if last is not None and not isinstance(last, dict):
            raise ValueError("last status is invalid")
        clean_last = None if last is None else {
            "callId": str(last.get("callId", ""))[:256],
            "model": str(last.get("model", "unknown"))[:256],
            "source": "litellm",
            "startedAt": last.get("startedAt"),
            "finishedAt": last.get("finishedAt"),
            "state": str(last.get("state", "unknown"))[:32],
        }
        host = hub_inference_snapshot()
        host_active = list(host.get("active") or [])
        candidates = [item for item in (clean_last, host.get("last")) if item]
        merged_last = max(
            candidates,
            key=lambda item: item.get("finishedAt") or item.get("startedAt") or 0,
        ) if candidates else None
        sanitized = {
            "active": clean_active + host_active,
            "activeCount": len(clean_active) + len(host_active),
            "last": merged_last,
        }
        if "updatedAt" in value:
            sanitized["updatedAt"] = value.get("updatedAt")
        return 200, sanitized
    except FileNotFoundError:
        return 200, hub_inference_snapshot()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return 503, {"error": f"inference status unavailable: {exc}"}


def run_discover(host_scan: dict | None = None) -> dict:
    global _discover
    hs = host_scan if host_scan is not None else get_host_scan()
    if not hs:
        hs = _load_host_scan_file()
        if hs:
            set_host_scan(hs)
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
    snap = merge_host_cli_models(snap, probe_host_cli_bridge())
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
            _update_sync_health(redis_ok=True)
        except Exception as exc:
            _update_sync_health(redis_ok=False, last_error=f"redis snapshot publish failed: {exc}"[:500])
            sys.stderr.write(f"[hub] redis snapshot publish error: {exc}\n")
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
        cycle_error = None
        try:
            refresh_snapshot()
        except Exception as e:
            cycle_error = f"matrix sync failed: {e}"[:500]
            sys.stderr.write(f"[hub] sync error: {e}\n")
        try:
            run_auto_if_due(_memory)
        except Exception as e:
            cycle_error = f"backup scheduler failed: {e}"[:500]
            sys.stderr.write(f"[hub] backup auto error: {e}\n")
        now = time.time()
        health = _get_sync_health()
        reported_error = cycle_error
        if reported_error is None and health.get("redis_ok") is False:
            reported_error = health.get("last_error") or "redis snapshot publish failed"
        _update_sync_health(
            last_cycle=now,
            last_success=now if reported_error is None else health.get("last_success"),
            last_error=reported_error,
        )
        time.sleep(max(15, SYNC_INTERVAL))


class Handler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.request_id = uuid.uuid4().hex[:16]
        self.auth_context: hub_auth.AuthContext | None = None

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"[hub] request_id={self.request_id} " + (fmt % args) + "\n")

    def _ensure_control_plane_auth(self, method: str, path: str) -> bool:
        """Attach auth_context; send 401 and return False when required auth fails."""
        ctx, err = hub_auth.resolve_request_auth(
            method=method,
            path=path,
            authorization=self.headers.get("Authorization"),
        )
        self.auth_context = ctx
        if err == "unauthorized":
            self._send(
                401,
                {
                    "error": "authentication required",
                    "code": "unauthorized",
                    "hint": "Send Authorization: Bearer <token>. "
                    "Mint a local JWT via POST /api/auth/token with the platform master key, "
                    "or use an OIDC access token when configured.",
                },
            )
            return False
        # Optional project scope from header when membership exists
        if ctx is not None:
            project_hdr = (self.headers.get("X-AetherStack-Project") or "").strip()
            if project_hdr:
                tenancy.attach_project_context(ctx, project_hdr)
        return True

    def _workspace_write_authorized(self) -> bool:
        # Platform admin JWT / master-key auth satisfies workspace write in team mode;
        # desktop still uses the dedicated workspace token header.
        if self.auth_context is not None and self.auth_context.is_admin():
            return True
        if self.auth_context is not None and self.auth_context.auth_method in {
            "local_jwt",
            "oidc",
            "master_key",
        }:
            # Members may write when they hold at least member on the active project
            # or when no project is scoped (single-tenant team ops).
            if self.auth_context.project_id:
                try:
                    tenancy.authorize_project(self.auth_context, self.auth_context.project_id, "member")
                    return True
                except PermissionError:
                    return False
            if self.auth_context.role in {"owner", "member", "admin"}:
                return True
        supplied = self.headers.get("X-AetherStack-Workspace-Token", "")
        return bool(WORKSPACE_WRITE_TOKEN and supplied) and secrets.compare_digest(
            supplied, WORKSPACE_WRITE_TOKEN
        )

    def _send(self, code: int, obj, content_type: str = "application/json; charset=utf-8") -> None:
        if code >= 500 and isinstance(obj, dict) and isinstance(obj.get("error"), str):
            sys.stderr.write(
                f"[hub] request_id={self.request_id} status={code} internal_error={obj['error'][:1000]}\n"
            )
        obj = _public_error_payload(code, obj, self.request_id)
        if isinstance(obj, (dict, list)):
            body = json.dumps(obj, default=str, indent=2).encode("utf-8")
        elif isinstance(obj, bytes):
            body = obj
        else:
            body = str(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("X-AetherStack-Request-ID", self.request_id)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        origin = self.headers.get("Origin")
        if origin and _request_origin_allowed(origin, self.headers.get("Host", "")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_sse_start(self) -> None:
        self.send_response(200)
        self.send_header("X-AetherStack-Request-ID", self.request_id)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        origin = self.headers.get("Origin")
        if origin and _request_origin_allowed(origin, self.headers.get("Host", "")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()

    def _send_sse_event(self, data: dict) -> None:
        payload = f"data: {json.dumps(data, default=str)}\n\n".encode("utf-8")
        self.wfile.write(payload)
        self.wfile.flush()

    def _send_sse_event_safe(self, data: dict) -> None:
        """Best-effort SSE send for error reporting: the client may already be gone
        (e.g. an earlier on_delta write is what caused the original error), so a
        failure here must not itself become a second unhandled exception."""
        try:
            self._send_sse_event(data)
        except Exception:
            pass

    def _read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if n <= 0:
            return {}
        if n > MAX_JSON_BODY:
            raise ValueError(f"request body exceeds {MAX_JSON_BODY} bytes")
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("Content-Type must be application/json")
        raw = self.rfile.read(n)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _origin_allowed(self) -> bool:
        return _request_origin_allowed(
            self.headers.get("Origin"),
            self.headers.get("Host", ""),
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._origin_allowed():
            self._send(403, {"error": "cross-origin request denied"})
            return
        self.send_response(204)
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        qs = parse_qs(u.query)
        if not self._ensure_control_plane_auth("GET", path):
            return

        if path in ("/", "/index.html", "/simple", "/simple.html"):
            simple = ROOT / "static" / "simple.html"
            if simple.is_file():
                self._send(200, simple.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, {"error": "simple.html missing"})
            return
        if path in ("/advanced", "/advanced.html"):
            self._send(200, _index_html(), "text/html; charset=utf-8")
            return
        if path in ("/graph", "/graph/", "/graph.html"):
            gp = ROOT / "static" / "graph.html"
            if gp.is_file():
                self._send(200, gp.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, {"error": "graph.html missing"})
            return
        if path in ("/gdpr", "/gdpr/", "/gdpr.html", "/privacy"):
            gp = ROOT / "static" / "gdpr.html"
            if gp.is_file():
                self._send(200, gp.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, {"error": "gdpr.html missing"})
            return
        if path in ("/aetherstack-icon.png", "/favicon.png"):
            icon = ROOT / "static" / "aetherstack-icon.png"
            if icon.is_file():
                self._send(200, icon.read_bytes(), "image/png")
            else:
                self._send(404, {"error": "aetherstack-icon.png missing"})
            return
        if path == "/v1/models":
            if not gateway_authorized(self.headers.get("Authorization")):
                self._send(401, {"error": {"message": "invalid AetherStack API key", "type": "authentication_error"}})
                return
            self._send(200, gateway_model_list(get_snapshot()))
            return
        if path == "/api/auth/config":
            self._send(200, hub_auth.public_auth_config())
            return
        if path == "/api/auth/me":
            if self.auth_context is None:
                self._send(401, {"error": "authentication required", "code": "unauthorized"})
                return
            self._send(200, self.auth_context.to_public())
            return
        if path in ("/api/tenancy", "/api/tenancy/snapshot"):
            self._send(200, tenancy.snapshot_for(self.auth_context))
            return
        if path == "/api/tenancy/projects":
            team_id = (qs.get("team_id") or [None])[0]
            self._send(200, {"projects": tenancy.list_projects_for(self.auth_context, team_id)})
            return
        if path.startswith("/api/tenancy/projects/") and path.count("/") >= 4:
            pid = path[len("/api/tenancy/projects/") :].strip("/")
            if pid and "/" not in pid:
                project = tenancy.get_project(pid)
                if not project:
                    self._send(404, {"error": "unknown project"})
                    return
                if self.auth_context is not None:
                    try:
                        tenancy.authorize_project(self.auth_context, pid, "viewer")
                    except PermissionError as e:
                        self._send(403, {"error": str(e), "code": "forbidden"})
                        return
                self._send(
                    200,
                    {
                        "project": project,
                        "memberships": tenancy.list_memberships(project_id=pid),
                    },
                )
                return
        if path == "/api/health":
            d = get_discover()
            models = get_snapshot().get("models") or {}
            routable_models = [
                alias
                for alias, meta in models.items()
                if meta.get("available") and "chat" in (meta.get("capabilities") or [])
            ]
            self._send(
                200,
                {
                    "ok": True,
                    "service": "aether-hub",
                    "memory": _memory.health(),
                    "xref": {
                        "multi_project": get_xref_state().get("multi_project"),
                        "project_count": get_xref_state().get("project_count"),
                        "auto_pull": get_xref_state().get("auto_pull"),
                    },
                    "privacy": {
                        "private_project_count": get_privacy_state().get("private_project_count"),
                        "private_model_count": get_privacy_state().get("private_model_count"),
                    },
                    "backup": {
                        "auto": get_backup_status().get("auto"),
                        "local_dir": get_backup_status().get("default_local_dir"),
                    },
                    "matrix_ts": get_snapshot().get("ts"),
                    "process_up": True,
                    "inference_ready": bool(routable_models),
                    "routable_model_count": len(routable_models),
                    "local_fallback_ready": "local-default" in routable_models,
                    "discover": d.get("summary"),
                    "background_sync": _get_sync_health(),
                    "auth": {
                        "require_auth": hub_auth.require_auth(),
                        "edition": hub_auth.edition(),
                    },
                    "tenancy": {
                        "project_count": tenancy.snapshot().get("project_count"),
                    },
                },
            )
            return
        if path == "/api/inference/status":
            code, value = get_inference_status()
            self._send(code, value)
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
        if path == "/api/auto/chain":
            self._send(200, describe_auto_mode(get_snapshot()))
            return
        if path == "/api/first-run":
            if (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes"):
                run_discover()
            desc = describe_auto_mode(get_snapshot())
            self._send(
                200,
                first_run_status(
                    get_discover(),
                    get_snapshot(),
                    auto_order=desc.get("priority_order"),
                    saved_order=desc.get("priority_order") != desc.get("priority_default"),
                ),
            )
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
        if path in ("/api/services", "/api/service-presets"):
            self._send(200, list_services(get_snapshot(), get_discover()))
            return
        if path == "/api/services/auto":
            try:
                self._send(200, describe_auto_mode(get_snapshot()))
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path.startswith("/api/services/") and path.endswith("/graph"):
            service_id = path[len("/api/services/") : -len("/graph")].strip("/")
            if service_id == "active":
                service_id = get_runtime().get("service") or "auto"
            try:
                self._send(200, build_auto_graph(get_snapshot()) if service_id == "auto" else build_service_graph(service_id, get_snapshot()))
            except ValueError as e:
                self._send(404, {"error": str(e)})
            return
        if path == "/api/events/stream":
            self._send_sse_start()
            q = _stage_subscribe()
            try:
                last_ping = time.time()
                while True:
                    try:
                        evt = q.get(timeout=15)
                        self._send_sse_event(evt)
                    except queue.Empty:
                        pass
                    if time.time() - last_ping > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_ping = time.time()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                _stage_unsubscribe(q)
            return
        if path in ("/api/update", "/api/updates"):
            self._send(200, update_status())
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
            ctx = resolve_private_context(session_id=sid)
            store_sid = (
                private_session_key(sid, ctx.get("project_id")) if ctx.get("private") else sid
            )
            self._send(
                200,
                {
                    "session_id": sid,
                    "store_session": store_sid,
                    "private": ctx.get("private"),
                    "messages": _memory.get_session(store_sid, limit=limit),
                },
            )
            return
        if path == "/api/memory/stats":
            ns = (qs.get("namespace") or ["default"])[0]
            # Never report private vault stats via bare common stats without context
            if str(ns).startswith("private:") and not (qs.get("private") or ["0"])[0] in (
                "1",
                "true",
                "yes",
            ):
                self._send(
                    403,
                    {"error": "private_vault_stats_require_private=1", "namespace": ns},
                )
                return
            self._send(200, _memory.stats(ns))
            return
        if path in ("/api/gdpr", "/api/gdpr/consent") and gdpr is None:
            self._send(503, {"error": "gdpr module not installed", "code": "service_unavailable"})
            return
        if path == "/api/gdpr":
            settings = gdpr.get_settings()
            self._send(200, {**settings, "subprocessors": gdpr.subprocessors()})
            return
        if path == "/api/gdpr/consent":
            sid = (qs.get("session_id") or [""])[0]
            self._send(200, {"session_id": sid, "consented": gdpr.has_consent(sid)})
            return
        if path in ("/api/slash", "/api/commands"):
            self._send(200, {"commands": list_commands()})
            return
        if path in ("/api/pipelines", "/api/scripts"):
            self._send(200, list_pipelines())
            return
        if path in ("/api/pipelines/ranking", "/api/scripts/ranking"):
            self._send(200, {"ranking": ranking()})
            return
        if path in ("/api/graphs", "/api/graph"):
            self._send(200, {"graphs": list_graphs(), "node_types": node_types()})
            return
        if path == "/api/graphs/template":
            self._send(200, best_practice_template())
            return
        if path == "/api/graphs/node-types":
            self._send(200, node_types())
            return
        if path.startswith("/api/graphs/") and path.count("/") == 3:
            gid = path[len("/api/graphs/") :].strip("/")
            if gid and gid not in ("template", "node-types", "auto-connect", "to-pipeline", "from-pipeline", "plan"):
                g = load_graph(gid)
                if g:
                    self._send(200, g)
                else:
                    self._send(404, {"error": f"unknown graph: {gid}"})
                return
        if path.startswith("/api/pipelines/") and path.endswith("/export"):
            pid = path[len("/api/pipelines/") : -len("/export")].strip("/")
            try:
                self._send(200, export_pipeline(pid))
            except ValueError as e:
                self._send(404, {"error": str(e)})
            return
        if path.startswith("/api/pipelines/") and not any(
            path.endswith(x) for x in ("/plan", "/vote", "/launch", "/export")
        ):
            pid = path[len("/api/pipelines/") :].strip("/")
            if pid and pid not in ("import", "ranking"):
                pipe = get_pipeline(pid)
                if pipe:
                    self._send(
                        200,
                        {k: v for k, v in pipe.items() if not str(k).startswith("_")},
                    )
                else:
                    self._send(404, {"error": f"unknown pipeline: {pid}"})
                return
        if path.startswith("/api/sessions/") and path.endswith("/status"):
            sid = path[len("/api/sessions/") : -len("/status")].strip("/") or "default"
            self._send(200, cmd_status(sid, _memory))
            return
        if path in ("/api/xref", "/api/cross-memory"):
            self._send(200, get_xref_state())
            return
        if path in ("/api/privacy", "/api/private"):
            self._send(200, get_privacy_state())
            return
        if path in ("/api/backup", "/api/backups"):
            self._send(200, {**get_backup_status(), **list_local_backups()})
            return
        self._send(404, {"error": "not found", "paths": _paths()})

    def do_POST(self) -> None:  # noqa: N802
        if not self._origin_allowed():
            self._send(403, {"error": "cross-origin request denied"})
            return
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        if not self._ensure_control_plane_auth("POST", path):
            return
        try:
            body = self._read_json()
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
            return

        if path == "/api/auth/token":
            try:
                self._send(200, hub_auth.mint_token_from_master_request(body or {}))
            except PermissionError as e:
                self._send(401, {"error": str(e), "code": "unauthorized"})
            except ValueError as e:
                self._send(400, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path == "/api/tenancy/projects":
            if self.auth_context is None:
                self._send(401, {"error": "authentication required", "code": "unauthorized"})
                return
            name = str((body or {}).get("name") or "").strip()
            if not name:
                self._send(400, {"error": "name is required"})
                return
            try:
                project = tenancy.create_project(
                    name=name,
                    team_id=(body or {}).get("team_id"),
                    owner_user_id=self.auth_context.user_id,
                    project_id=(body or {}).get("project_id"),
                )
                self._send(200, {"project": project})
            except ValueError as e:
                self._send(400, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path.startswith("/api/tenancy/projects/") and path.endswith("/members"):
            if self.auth_context is None:
                self._send(401, {"error": "authentication required", "code": "unauthorized"})
                return
            pid = path[len("/api/tenancy/projects/") : -len("/members")].strip("/")
            try:
                tenancy.authorize_project(self.auth_context, pid, "owner")
            except PermissionError as e:
                # platform admin still allowed via is_admin inside authorize
                if not self.auth_context.is_admin():
                    self._send(403, {"error": str(e), "code": "forbidden"})
                    return
            user_id = str((body or {}).get("user_id") or "").strip()
            role = str((body or {}).get("role") or "member").strip()
            if not user_id:
                self._send(400, {"error": "user_id is required"})
                return
            try:
                self._send(200, {"membership": tenancy.add_member(pid, user_id, role)})
            except ValueError as e:
                self._send(400, {"error": str(e)})
            return

        if path in ("/api/backup", "/api/backups", "/api/backup/run"):
            try:
                dests = body.get("destinations") or body.get("dest")
                if isinstance(dests, str):
                    dests = [d.strip() for d in dests.split(",") if d.strip()]
                self._send(
                    200,
                    run_backup(
                        _memory,
                        scope=str(body.get("scope") or "global"),
                        project_id=body.get("project_id"),
                        project_path=body.get("project_path") or body.get("path"),
                        session_id=body.get("session_id"),
                        include_private=body.get("include_private"),
                        include_embeddings=body.get("include_embeddings"),
                        destinations=dests,
                    ),
                )
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/api/backup/config", "/api/backups/config"):
            try:
                self._send(200, set_auto_config(body or {}))
            except Exception as e:
                self._send(400, {"error": str(e)})
            return
        if path in ("/api/privacy", "/api/private"):
            try:
                self._send(
                    200,
                    apply_privacy_patch(
                        body or {},
                        redis_client=_redis_client(),
                        mem=_memory,
                    ),
                )
            except ValueError as e:
                self._send(400, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/api/privacy/release", "/api/private/release"):
            try:
                patch = dict(body or {})
                patch["release"] = True
                self._send(
                    200,
                    apply_privacy_patch(patch, redis_client=_redis_client(), mem=_memory),
                )
            except ValueError as e:
                self._send(400, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/api/xref", "/api/cross-memory"):
            try:
                self._send(200, set_xref_state(body or {}))
            except Exception as e:
                self._send(400, {"error": str(e)})
            return
        if path in ("/api/xref/scan", "/api/cross-memory/scan"):
            paths = body.get("paths") or body.get("path") or []
            if isinstance(paths, str):
                paths = [paths]
            if not paths:
                self._send(400, {"error": "paths required (list of project roots)"})
                return
            try:
                self._send(
                    200,
                    scan_and_index_paths(
                        _memory,
                        [str(p) for p in paths],
                        max_files=int(body.get("max_files") or 80),
                    ),
                )
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/api/xref/index", "/api/cross-memory/index"):
            # Host-side scan payload: {scan: {...}} or raw scan dict with chunks
            scan = body.get("scan") if isinstance(body.get("scan"), dict) else body
            if not isinstance(scan, dict) or not (scan.get("chunks") or scan.get("project_id") or scan.get("path")):
                self._send(400, {"error": "scan payload required (chunks + path/project_id)"})
                return
            try:
                self._send(
                    200,
                    index_scan(
                        _memory,
                        scan,
                        replace_project=bool(body.get("replace_project", True)),
                    ),
                )
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/api/xref/search", "/api/cross-memory/search"):
            q = (body.get("query") or body.get("q") or "").strip()
            if not q:
                self._send(400, {"error": "query required"})
                return
            try:
                self._send(
                    200,
                    cross_search(
                        _memory,
                        q,
                        kinds=body.get("kinds"),
                        project_ids=body.get("project_ids") or body.get("projects"),
                        top_k=int(body.get("top_k") or 10),
                        require_multi=bool(body.get("require_multi", True)),
                    ),
                )
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/api/xref/pull", "/api/cross-memory/pull"):
            q = (body.get("query") or body.get("q") or body.get("goal") or "").strip()
            if not q:
                self._send(400, {"error": "query required"})
                return
            try:
                self._send(
                    200,
                    pull_context(
                        _memory,
                        q,
                        kinds=body.get("kinds"),
                        top_k=body.get("top_k") or body.get("max_pull"),
                        as_prompt_block=bool(body.get("as_prompt_block", True)),
                    ),
                )
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/api/slash", "/api/commands"):
            text = body.get("text") or body.get("command") or ""
            sid = body.get("session_id") or body.get("session") or "default"
            try:
                self._send(200, execute_slash(text, _memory, session_id=sid))
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path.startswith("/api/gdpr") and gdpr is None:
            self._send(503, {"error": "gdpr module not installed", "code": "service_unavailable"})
            return
        if path == "/api/gdpr":
            try:
                settings = gdpr.set_settings(body or {})
                self._send(200, {**settings, "subprocessors": gdpr.subprocessors()})
            except ValueError as e:
                self._send(400, {"error": str(e)})
            return
        if path == "/api/gdpr/consent":
            sid = str(body.get("session_id") or "").strip()
            if not sid:
                self._send(400, {"error": "session_id is required"})
                return
            if body.get("revoke"):
                gdpr.revoke_consent(sid)
            else:
                gdpr.record_consent(sid)
            self._send(200, {"session_id": sid, "consented": gdpr.has_consent(sid)})
            return
        if path == "/api/gdpr/export":
            sid = str(body.get("session_id") or "").strip()
            if not sid:
                self._send(400, {"error": "session_id is required"})
                return
            try:
                self._send(200, gdpr.export_user_data(_memory, sid))
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path == "/api/gdpr/erase":
            sid = str(body.get("session_id") or "").strip()
            if not sid:
                self._send(400, {"error": "session_id is required"})
                return
            try:
                self._send(200, {"session_id": sid, "removed": gdpr.erase_user_data(_memory, sid)})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/api/pipelines/import", "/api/scripts/import"):
            try:
                raw = body.get("pipeline") if body.get("pipeline") is not None else body
                self._send(
                    200,
                    import_pipeline(raw, persist=bool(body.get("persist", True))),
                )
            except (ValueError, json.JSONDecodeError) as e:
                self._send(400, {"error": str(e)})
            return
        if path in ("/api/graphs", "/api/graph"):
            try:
                self._send(200, save_graph(body or {}))
            except Exception as e:
                self._send(400, {"error": str(e)})
            return
        if path.startswith("/api/services/") and path.endswith("/graph"):
            service_id = path[len("/api/services/") : -len("/graph")].strip("/")
            if service_id == "active":
                service_id = get_runtime().get("service") or "auto"
            try:
                self._send(200, save_auto_graph(body or {}) if service_id == "auto" else save_service_graph(service_id, body or {}))
            except ValueError as e:
                self._send(400, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path == "/api/graphs/auto-connect":
            g = body.get("graph") or body
            nodes = g.get("nodes") or []
            res = auto_connect(nodes=nodes, graph=g)
            # merge layout back
            out = dict(g)
            out["nodes"] = res.get("nodes") or nodes
            out["edges"] = res.get("edges") or []
            out["practices"] = res.get("practices")
            self._send(200, out)
            return
        if path == "/api/graphs/to-pipeline":
            g = body.get("graph") or body
            try:
                self._send(200, graph_to_pipeline(g))
            except Exception as e:
                self._send(400, {"error": str(e)})
            return
        if path == "/api/graphs/from-pipeline":
            try:
                self._send(
                    200,
                    pipeline_to_graph(
                        pipeline_id=body.get("pipeline_id"),
                        pipeline=body.get("pipeline"),
                    ),
                )
            except ValueError as e:
                self._send(404, {"error": str(e)})
            return
        if path == "/api/graphs/from-preset-script":
            try:
                self._send(200, preset_script_to_graph(body.get("text") or "", graph_id=body.get("graph_id")))
            except PresetScriptError as e:
                self._send(400, {"error": str(e)})
            return
        if path == "/api/graphs/to-preset-script":
            g = body.get("graph") or body
            try:
                self._send(200, {"text": graph_to_preset_script(g)})
            except Exception as e:
                self._send(400, {"error": str(e)})
            return
        if path == "/api/graphs/plan":
            g = body.get("graph") or body
            try:
                self._send(
                    200,
                    plan_graph(g, get_snapshot(), goal=body.get("goal") or ""),
                )
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path == "/api/graphs/run":
            graph_body = body.get("graph")
            if not graph_body and body.get("graph_id"):
                graph_body = load_graph(str(body["graph_id"]))
            if not graph_body:
                self._send(404, {"error": "graph or graph_id is required"})
                return
            try:
                body["_workspace_write_authorized"] = self._workspace_write_authorized()
                self._send(
                    200,
                    execute_graph(
                        graph_body,
                        get_snapshot(),
                        body or {},
                        memory=_memory,
                        session_id=body.get("session_id") or body.get("session"),
                    ),
                )
            except ValueError as e:
                self._send(400, {"error": str(e)})
            except PermissionError as e:
                self._send(403, {"error": str(e), "code": "workspace_write_unauthorized"})
            except GraphExecutionError as e:
                self._send(502, {"ok": False, "error": str(e), "steps": e.steps})
            except Exception as e:
                self._send(502, {"error": f"graph execution failed: {str(e)[:500]}"})
            return
        if path == "/api/graphs/run/stream":
            graph_body = body.get("graph")
            if not graph_body and body.get("graph_id"):
                graph_body = load_graph(str(body["graph_id"]))
            if not graph_body:
                self._send(404, {"error": "graph or graph_id is required"})
                return
            graph_id = str(graph_body.get("service_id") or graph_body.get("id") or "graph")
            run_id = str(body.get("run_id") or uuid.uuid4().hex)
            self._send_sse_start()
            _register_run(run_id)
            try:
                body["_workspace_write_authorized"] = self._workspace_write_authorized()

                def on_delta(chunk_text: str) -> None:
                    self._send_sse_event({"type": "delta", "text": chunk_text})

                def on_status(payload: dict) -> None:
                    event = {"type": "status", "run_id": run_id}
                    if isinstance(payload, dict):
                        for key in ("phase", "model", "models", "label", "stage_id", "index", "total"):
                            if payload.get(key) is not None:
                                event[key] = payload[key]
                    self._send_sse_event(event)
                    # Same fan-out channel /run/stream uses, so this graph's own
                    # canvas (or any other tab watching it) lights up live instead
                    # of only reacting to a run started elsewhere.
                    _stage_publish({**event, "service_id": graph_id})

                result = execute_graph(
                    graph_body,
                    get_snapshot(),
                    body or {},
                    memory=_memory,
                    session_id=body.get("session_id") or body.get("session"),
                    on_status=on_status,
                    on_delta=on_delta,
                    cancel_check=_make_cancel_check(run_id),
                )
                self._send_sse_event({"type": "done", "result": result})
            except GraphRunCancelled:
                self._send_sse_event_safe({"type": "cancelled", "run_id": run_id})
            except ValueError as e:
                self._send_sse_event_safe(
                    {"type": "error", "error": str(e), "code": "invalid_request", "request_id": self.request_id}
                )
            except PermissionError as e:
                self._send_sse_event_safe(
                    {
                        "type": "error",
                        "error": str(e),
                        "code": "workspace_write_unauthorized",
                        "request_id": self.request_id,
                    }
                )
            except GraphExecutionError as e:
                self._send_sse_event_safe(
                    {"type": "error", "error": str(e), "code": "graph_execution_failed", "steps": e.steps}
                )
            except Exception as e:
                sys.stderr.write(f"[hub] request_id={self.request_id} graph_stream_error={str(e)[:1000]}\n")
                self._send_sse_event_safe(
                    {
                        "type": "error",
                        "error": "AetherStack could not complete the streamed graph run.",
                        "code": "upstream_error",
                        "request_id": self.request_id,
                    }
                )
            finally:
                _unregister_run(run_id)
            return
        if path == "/api/runs/cancel":
            run_id = str(body.get("run_id") or "").strip()
            if not run_id:
                self._send(400, {"error": "run_id is required"})
                return
            found = _cancel_run(run_id)
            self._send(200, {"ok": True, "run_id": run_id, "found": found})
            return
        if path.startswith("/api/pipelines/") and path.endswith("/vote"):
            pid = path[len("/api/pipelines/") : -len("/vote")].strip("/")
            try:
                self._send(
                    200,
                    vote(
                        pid,
                        up=body.get("up"),
                        down=body.get("down"),
                        hw_flag=body.get("hw_flag") or body.get("hw"),
                        voter=body.get("voter") or "local",
                    ),
                )
            except Exception as e:
                self._send(400, {"error": str(e)})
            return
        if path.startswith("/api/pipelines/") and path.endswith("/plan"):
            pid = path[len("/api/pipelines/") : -len("/plan")].strip("/")
            try:
                self._send(
                    200,
                    plan_pipeline(
                        pid,
                        get_snapshot(),
                        goal=body.get("goal") or body.get("prompt") or "",
                        session_id=body.get("session_id") or "default",
                    ),
                )
            except ValueError as e:
                self._send(404, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path.startswith("/api/sessions/") and path.endswith("/message"):
            sid = path[len("/api/sessions/") : -len("/message")].strip("/") or "default"
            text = body.get("text") or body.get("content") or ""
            try:
                self._send(
                    200,
                    maybe_handle_message(
                        text,
                        _memory,
                        session_id=sid,
                        store_user=bool(body.get("store_user", True)),
                    ),
                )
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path == "/api/auto/chain":
            try:
                set_auto_order((body or {}).get("order") or [], (body or {}).get("sequence_mode"))
                self._send(200, describe_auto_mode(get_snapshot()))
            except ValueError as e:
                self._send(400, {"error": str(e)})
            return
        if path == "/api/first-run":
            try:
                if (body or {}).get("reset"):
                    first_run_reset()
                run_discover()
                desc = describe_auto_mode(get_snapshot())
                self._send(
                    200,
                    first_run_run(
                        get_discover(),
                        get_snapshot(),
                        confirm=bool((body or {}).get("confirm")),
                        only_safe=(body or {}).get("only_safe", True) is not False,
                        auto_order=desc.get("priority_order"),
                        saved_order=desc.get("priority_order") != desc.get("priority_default"),
                    ),
                )
            except Exception as e:
                self._send(500, {"error": f"first-run setup failed: {str(e)[:400]}"})
            return
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
        if path in ("/api/services/refresh", "/api/service-presets/refresh"):
            try:
                self._send(200, list_services(refresh_snapshot(), run_discover()))
            except Exception as e:
                self._send(500, {"error": str(e)})
            return

        if path == "/v1/chat/completions":
            if not gateway_authorized(self.headers.get("Authorization")):
                self._send(401, {"error": {"message": "invalid AetherStack API key", "type": "authentication_error"}})
                return
            try:
                completion, wants_stream = gateway_chat_completion(body, get_snapshot())
                if wants_stream:
                    self._send(200, gateway_stream_bytes(completion), "text/event-stream; charset=utf-8")
                else:
                    self._send(200, completion)
            except GatewayError as exc:
                self._send(exc.status, gateway_error_body(exc))
            except Exception as exc:
                self._send(502, gateway_error_body(GatewayError(str(exc), 502, "backend_error")))
            return
        if path == "/api/services/classify":
            try:
                goal = body.get("goal") or body.get("prompt")
                # Auto is no longer intent→preset; return direct model chain description.
                if str(body.get("mode") or "").lower() == "auto" or str(body.get("service_id") or "") == "auto":
                    snap = get_snapshot()
                    desc = describe_auto_mode(snap, session_id=body.get("session_id") or body.get("session"))
                    self._send(
                        200,
                        {
                            "service_id": "auto",
                            "label": "Auto",
                            "confidence": "direct",
                            "score": 100,
                            "matched_terms": ["auto", "direct-models", "unified-memory"],
                            "candidates": [{"service_id": "auto", "score": 100}],
                            **{k: desc[k] for k in ("model_chain", "primary", "host_cli_count", "local_count", "memory", "mode") if k in desc},
                        },
                    )
                    return
                self._send(200, classify_service(goal, get_snapshot()))
            except ValueError as e:
                self._send(400, {"error": str(e)})
            return
        if path == "/api/services/auto":
            try:
                self._send(
                    200,
                    describe_auto_mode(
                        get_snapshot(),
                        session_id=(body or {}).get("session_id") or (body or {}).get("session"),
                    ),
                )
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/api/update/stage", "/api/updates/stage"):
            try:
                self._send(200, stage_update())
            except Exception as e:
                self._send(502, {"error": f"update staging failed: {str(e)[:500]}"})
            return
        if path.startswith("/api/services/") and path.endswith("/activate"):
            service_id = path[len("/api/services/") : -len("/activate")].strip("/")
            try:
                if service_id == "auto":
                    self._send(200, {"ok": True, **describe_auto_mode(get_snapshot())})
                    return
                result = activate_service(service_id, get_snapshot(), body or {})
                self._send(200, result)
            except ValueError as e:
                self._send(404, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path.startswith("/api/services/") and path.endswith("/plan"):
            service_id = path[len("/api/services/") : -len("/plan")].strip("/")
            try:
                if service_id == "auto":
                    desc = describe_auto_mode(
                        get_snapshot(),
                        session_id=body.get("session_id") or body.get("session"),
                    )
                    self._send(
                        200,
                        {
                            "service": "auto",
                            "auto_mode": True,
                            "model_chain": desc.get("model_chain"),
                            "memory": "unified",
                            "selection": {
                                "service_id": "auto",
                                "label": "Auto",
                                "confidence": "direct",
                                "source": "auto-direct-models",
                                "model": desc.get("primary"),
                            },
                        },
                    )
                    return
                result = plan_service(service_id, get_snapshot(), body or {})
                self._send(200, result)
            except ValueError as e:
                self._send(404, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path.startswith("/api/services/") and path.endswith("/run"):
            service_id = path[len("/api/services/") : -len("/run")].strip("/")
            try:
                body["_workspace_write_authorized"] = self._workspace_write_authorized()
                sid = body.get("session_id") or body.get("session")
                if service_id == "auto":
                    result = execute_auto(
                        get_snapshot(),
                        body or {},
                        memory=_memory,
                        session_id=sid,
                    )
                    self._send(200, result)
                    return
                result = execute_service(
                    service_id,
                    get_snapshot(),
                    body or {},
                    memory=_memory,
                    session_id=sid,
                )
                self._send(200, result)
            except ValueError as e:
                self._send(400, {"error": str(e)})
            except PermissionError as e:
                self._send(403, {"error": str(e), "code": "workspace_write_unauthorized"})
            except Exception as e:
                self._send(502, {"error": f"service execution failed: {str(e)[:500]}"})
            return
        if path.startswith("/api/services/") and path.endswith("/run/stream"):
            service_id = path[len("/api/services/") : -len("/run/stream")].strip("/")
            run_id = str(body.get("run_id") or uuid.uuid4().hex)
            self._send_sse_start()
            _register_run(run_id)
            try:
                body["_workspace_write_authorized"] = self._workspace_write_authorized()
                def on_delta(chunk_text: str) -> None:
                    self._send_sse_event({"type": "delta", "text": chunk_text})

                def on_status(payload: dict) -> None:
                    # phase/model only — no prompt content
                    event = {"type": "status", "run_id": run_id}
                    if isinstance(payload, dict):
                        for key in ("phase", "model", "models", "label"):
                            if payload.get(key) is not None:
                                event[key] = payload[key]
                    self._send_sse_event(event)
                    # Fan the same phase/model updates out to any other client —
                    # e.g. the node graph canvas open in another tab — watching
                    # this preset run live, not just the caller of this request.
                    if service_id != "auto":
                        _stage_publish({**event, "service_id": service_id})

                sid = body.get("session_id") or body.get("session")
                cancel_check = _make_cancel_check(run_id)
                if service_id == "auto":
                    result = execute_auto(
                        get_snapshot(),
                        body or {},
                        on_delta=on_delta,
                        on_status=on_status,
                        memory=_memory,
                        session_id=sid,
                        cancel_check=cancel_check,
                    )
                else:
                    result = execute_service(
                        service_id,
                        get_snapshot(),
                        body or {},
                        on_delta=on_delta,
                        on_status=on_status,
                        memory=_memory,
                        session_id=sid,
                        cancel_check=cancel_check,
                    )
                self._send_sse_event({"type": "done", "result": result})
            except RunCancelled:
                self._send_sse_event_safe({"type": "cancelled", "run_id": run_id})
            except ValueError as e:
                self._send_sse_event_safe(
                    {
                        "type": "error",
                        "error": str(e),
                        "code": "invalid_request",
                        "request_id": self.request_id,
                    }
                )
            except PermissionError as e:
                self._send_sse_event_safe(
                    {
                        "type": "error",
                        "error": str(e),
                        "code": "workspace_write_unauthorized",
                        "request_id": self.request_id,
                    }
                )
            except Exception as e:
                sys.stderr.write(f"[hub] request_id={self.request_id} stream_error={str(e)[:1000]}\n")
                self._send_sse_event_safe(
                    {
                        "type": "error",
                        "error": "AetherStack could not complete the streamed request.",
                        "code": "upstream_error",
                        "request_id": self.request_id,
                    }
                )
            finally:
                _unregister_run(run_id)
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
                sid = body.get("session_id") or body.get("session") or "default"
                # Privacy: private sessions/models never hit common xref or agent-events
                priv = resolve_private_context(
                    session_id=sid,
                    project_id=body.get("project_id"),
                    path=body.get("path"),
                    model=body.get("model")
                    or ((plan.get("models_in_event") or [None])[0] if plan else None),
                    private_flag=body.get("private"),
                )
                plan["privacy"] = {
                    "private": priv.get("private"),
                    "reasons": priv.get("reasons"),
                    "project_id": priv.get("project_id"),
                }
                # Auto-pull cross-project concepts/code/research when multi-project is on
                xref = get_xref_state()
                want_pull = body.get("xref_pull")
                if want_pull is None:
                    want_pull = bool(xref.get("multi_project") and xref.get("auto_pull", True))
                if priv.get("private"):
                    want_pull = False
                    plan["xref_pull"] = {
                        "ok": False,
                        "skipped": "private_mode",
                        "message": "Cross-project pull disabled for private sessions/models.",
                    }
                if want_pull:
                    goal_text = (
                        (plan.get("goal") or {}).get("text")
                        or body.get("goal")
                        or body.get("query")
                        or ""
                    )
                    if goal_text:
                        try:
                            pulled = pull_context(
                                _memory,
                                str(goal_text)[:500],
                                kinds=body.get("xref_kinds"),
                                top_k=body.get("xref_max") or xref.get("max_pull"),
                            )
                            plan["xref_pull"] = {
                                "ok": pulled.get("ok"),
                                "hit_count": pulled.get("hit_count") or len(pulled.get("hits") or []),
                                "message": pulled.get("message"),
                                "prompt_block": pulled.get("prompt_block") or "",
                                "hits": (pulled.get("hits") or [])[:5],
                            }
                            if pulled.get("prompt_block") and body.get("remember", True) and not priv.get("private"):
                                _memory.upsert_vector(
                                    text=pulled["prompt_block"][:6000],
                                    namespace=f"session-context:{sid}",
                                    meta={
                                        "kind": "xref_pull",
                                        "query": str(goal_text)[:200],
                                    },
                                )
                        except Exception as xe:
                            plan["xref_pull"] = {"ok": False, "error": str(xe)}
                # Store plan briefly — private: vault only, redacted goal
                if body.get("remember", True):
                    if priv.get("private"):
                        vault_ns = force_private_namespace("agent-events", priv)
                        _memory.upsert_vector(
                            text=redact_log(
                                "agent_plan",
                                priv,
                                event_id=plan.get("event_id"),
                                mode=plan.get("mode"),
                            ),
                            namespace=vault_ns,
                            meta={
                                "event_id": plan.get("event_id"),
                                "mode": plan.get("mode"),
                                "private": True,
                            },
                        )
                    else:
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
                # Track as open task so /clear waits until /done
                if body.get("track_task", True):
                    goal = (plan.get("goal") or {}).get("text") or body.get("goal") or "agent event"
                    t = register_task(
                        f"event:{plan.get('event_id')}: {str(goal)[:80]}",
                        session_id=sid,
                        task_id=(plan.get("event_id") or "")[:8] or None,
                        meta={"event_id": plan.get("event_id"), "mode": plan.get("mode")},
                    )
                    plan["tracked_task"] = t
                    plan["slash_hint"] = (
                        "When agents finish: POST /api/slash "
                        f'{{\"session_id\":\"{sid}\",\"text\":\"/done {t.get("id")}\"}} '
                        f'then /clear or /compact'
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
            ctx = resolve_private_context(
                session_id=sid,
                project_id=body.get("project_id"),
                path=body.get("path"),
                model=body.get("model"),
                private_flag=body.get("private"),
            )
            store_sid = (
                private_session_key(sid, ctx.get("project_id")) if ctx.get("private") else sid
            )
            meta = dict(body.get("meta") or {})
            meta["private"] = bool(ctx.get("private"))
            msg = _memory.append_message(store_sid, role, content, meta)
            # Index into common pool only when not private
            if body.get("index", True) and not ctx.get("private"):
                _memory.upsert_vector(
                    text=f"{role}: {content}",
                    namespace=body.get("namespace") or f"session:{sid}",
                    meta={"session_id": sid, "role": role, **meta},
                )
            elif body.get("index", True) and ctx.get("private"):
                ns = force_private_namespace(
                    body.get("namespace") or f"session:{sid}", ctx
                )
                _memory.upsert_vector(
                    text=f"{role}: {content}",
                    namespace=ns,
                    meta={"session_id": sid, "role": role, **meta},
                )
            out_msg = msg
            if ctx.get("private"):
                # Do not echo full content in API response logs path — keep message but flag
                out_msg = {**msg, "private": True}
            self._send(
                200,
                {
                    "ok": True,
                    "message": out_msg,
                    "private": ctx.get("private"),
                    "store_session": store_sid if ctx.get("private") else sid,
                    "common_pool": not ctx.get("private"),
                },
            )
            return
        if path == "/api/memory/vectors":
            text = body.get("text") or ""
            if not text:
                self._send(400, {"error": "text required"})
                return
            ctx = resolve_private_context(
                session_id=body.get("session_id"),
                project_id=body.get("project_id"),
                path=body.get("path"),
                model=body.get("model"),
                private_flag=body.get("private"),
            )
            ns = body.get("namespace") or "default"
            if ctx.get("private"):
                ns = force_private_namespace(ns, ctx)
            elif body.get("private") is True:
                self._send(400, {"error": "private=true requires project_id, session_id, or model"})
                return
            # Block accidental common write when private
            if ctx.get("private") and is_common_namespace(ns) and not str(ns).startswith("private:"):
                self._send(
                    403,
                    {
                        "error": "private_mode_blocks_common_namespace",
                        "namespace": ns,
                        "log": redact_log("vector_upsert_blocked", ctx, namespace=ns),
                    },
                )
                return
            res = _memory.upsert_vector(
                text=text,
                namespace=ns,
                meta={
                    **(body.get("meta") or {}),
                    "private": bool(ctx.get("private")),
                    "project_id": ctx.get("project_id"),
                },
                id=body.get("id"),
                embedding=body.get("embedding"),
            )
            res["private"] = bool(ctx.get("private"))
            res["common_pool"] = not ctx.get("private")
            self._send(200, res)
            return
        if path == "/api/memory/search":
            q = body.get("query") or body.get("q") or ""
            if not q:
                self._send(400, {"error": "query required"})
                return
            ctx = resolve_private_context(
                session_id=body.get("session_id"),
                project_id=body.get("project_id"),
                path=body.get("path"),
                model=body.get("model"),
                private_flag=body.get("private"),
            )
            ns = body.get("namespace") or "default"
            # Private clients may only search their vault unless they explicitly leave private
            if ctx.get("private"):
                ns = force_private_namespace(ns, ctx)
            # Common search never scans private: namespaces (isolation)
            if not ctx.get("private") and str(ns).startswith("private:"):
                self._send(
                    403,
                    {
                        "error": "private_vault_not_readable_from_common",
                        "message": "Release project or pass matching private session/project context.",
                    },
                )
                return
            res = _memory.search(
                query=q,
                namespace=ns,
                top_k=int(body.get("top_k") or 5),
                embedding=body.get("embedding"),
            )
            res["private"] = bool(ctx.get("private"))
            self._send(200, res)
            return
        self._send(404, {"error": "not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._origin_allowed():
            self._send(403, {"error": "cross-origin request denied"})
            return
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        if not self._ensure_control_plane_auth("DELETE", path):
            return
        if path.startswith("/api/tenancy/projects/") and "/members/" in path:
            if self.auth_context is None:
                self._send(401, {"error": "authentication required", "code": "unauthorized"})
                return
            # /api/tenancy/projects/{pid}/members/{user_id}
            rest = path[len("/api/tenancy/projects/") :]
            parts = rest.split("/")
            if len(parts) == 3 and parts[1] == "members":
                pid, user_id = parts[0], parts[2]
                try:
                    if not self.auth_context.is_admin():
                        tenancy.authorize_project(self.auth_context, pid, "owner")
                except PermissionError as e:
                    self._send(403, {"error": str(e), "code": "forbidden"})
                    return
                ok = tenancy.remove_member(pid, user_id)
                self._send(200 if ok else 404, {"removed": ok, "project_id": pid, "user_id": user_id})
                return
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
        "GET  /api/services          ← capability-driven task services",
        "GET|POST /api/services/auto ← direct host-CLI + memory failover chain",
        "POST /api/services/classify ← choose a service from task language (presets)",
        "POST /api/services/{id}/activate",
        "POST /api/services/{id}/plan",
        "POST /api/services/{id}/run  ← use id=auto for direct models + unified memory",
        "GET  /api/services/{id|active}/graph ← editable resolved preset tree",
        "POST /api/services/{id|active}/graph ← save node edits back into service_catalog.yaml",
        "GET  /api/events/stream     ← SSE: live lead/worker/review/memory phase updates for any running preset",
        "GET  /api/update            ← check upstream",
        "POST /api/update/stage      ← download without applying",
        "POST /api/agents/plan       ← multi-LLM event plan",
        "GET|POST /api/bootstrap     ← optional auto-install plan (off by default)",
        "POST /api/bootstrap/run     ← {confirm, dry_run, only_safe}",
        "GET  /api/combos            ← tiers + situation packs",
        "POST /api/combos/{id}/launch",
        "POST /api/combos/{id}/plan",
        "GET  /api/combos/{id}/export",
        "POST /api/combos/import",
        "GET  /api/slash             ← list /clear /compact /save …",
        "POST /api/slash             {session_id, text:\"/clear\"}",
        "GET|POST /api/gdpr          ← settings + subprocessor list; POST {enabled, retention_days, require_cloud_consent}",
        "GET|POST /api/gdpr/consent  ← {session_id} — record/check per-session cloud-dispatch consent",
        "POST /api/gdpr/export       {session_id} ← Article 15/20: everything stored for that session",
        "POST /api/gdpr/erase        {session_id} ← Article 17: real deletion, not archive-then-clear",
        "GET  /api/pipelines         ← multi-stage LLM scripts",
        "POST /api/pipelines/import",
        "GET  /api/pipelines/{id}/export",
        "POST /api/pipelines/{id}/plan",
        "POST /api/pipelines/{id}/vote  {up|down, hw_flag}",
        "GET  /graph                 ← node canvas UI",
        "GET|POST /api/graphs",
        "POST /api/graphs/auto-connect",
        "POST /api/graphs/to-pipeline | from-pipeline | plan",
        "POST /api/graphs/to-preset-script | from-preset-script  ← whole-preset YAML (master/workers/parallel/audit/tester)",
        "POST /api/graphs/run          ← blocking; use run/stream for live node status",
        "POST /api/graphs/run/stream   ← SSE: same fan-out as services/*/run/stream, node-level status/delta",
        "POST /api/runs/cancel  {run_id} ← stops a running services/*/run/stream or graphs/run/stream run server-side",
        "POST /api/sessions/{id}/message",
        "GET  /api/sessions/{id}/status",
        "/api/health",
        "GET  /api/inference/status  ← active model aliases only; no prompt data",
        "/api/matrix",
        "/api/route?need=code&prefer=local",
        "/api/sync",
        "POST /api/memory/vectors",
        "POST /api/memory/search",
        "GET|POST /api/xref          ← multi-project cross memory (off by default)",
        "POST /api/xref/scan         {paths:[...]}  (if hub can read paths)",
        "POST /api/xref/index        host scan payload {chunks, path, …}",
        "POST /api/xref/search       {query, kinds?}",
        "POST /api/xref/pull         {query} → prompt_block for injection",
        "GET|POST /api/privacy       ← private project/model isolation (persistent)",
        "POST /api/privacy/release   {project_id, purge_vault?}",
        "GET  /api/backup            ← list local backups + config",
        "POST /api/backup            {scope, destinations, project_path?}",
        "POST /api/backup/config     auto schedule + local/aws/azure",
    ]


def _index_html() -> bytes:
    snap = get_snapshot()
    disc = get_discover()
    summary = snap.get("summary") or {}
    dsum = disc.get("summary") or {}
    recs = disc.get("recommendations") or []
    rows = matrix_table(snap)
    caps = [c for c in (snap.get("capabilities") or {}).keys()]
    def esc(value):
        return html_lib.escape(str(value if value is not None else ""), quote=True)
    head = "".join(f"<th>{esc(c)}</th>" for c in caps)
    body_rows = []
    for r in rows:
        cells = "".join(
            f"<td class='{'y' if r.get(c) else 'n'}'>{'●' if r.get(c) else '·'}</td>" for c in caps
        )
        av = "ok" if r.get("available") else "off"
        body_rows.append(
            f"<tr class='{av}'><td><code>{esc(r['model'])}</code></td>"
            f"<td>{esc(r.get('tier'))}</td><td>{av}</td>{cells}</tr>"
        )
    table = "\n".join(body_rows)
    rec_parts = []
    for rec in recs[:8]:
        severity = str(rec.get("severity") or "info")
        severity_class = severity if severity in {"high", "medium", "ok", "info"} else "info"
        rec_parts.append(
            f"<li class='sev-{severity_class}'><b>{esc(severity)}</b> — {esc(rec.get('action'))}"
            f"<div class='muted'>{esc(rec.get('detail') or '')}</div></li>"
        )
    rec_html = "".join(rec_parts)
    ollama_eps = disc.get("ollama") or {}
    ep_html = ""
    for ep in ollama_eps.get("endpoints") or []:
        st = "up" if ep.get("reachable") else "dn"
        models = ", ".join(m.get("name", "") for m in (ep.get("models") or [])[:5]) or "—"
        ep_html += (
            f"<div class='ep {st}'><code>{esc(ep.get('label'))}</code> "
            f"{esc(ep.get('base'))} → {esc(models)}</div>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Aether Hub — discover · matrix · memory</title>
<link rel="icon" type="image/png" href="/aetherstack-icon.png"/>
<style>
 :root{{color-scheme:dark;--bg:#090a0b;--panel:#111315;--raised:#17191b;--line:#303336;--line-strong:#4b4f52;--text:#ecebe7;--muted:#9b9b95;--accent:#d6b36a;--good:#76b98a;--warn:#d6a85f;--bad:#d87575}}
 *{{box-sizing:border-box}}
 body{{font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:var(--bg);color:var(--text);margin:0 0 2rem;font-size:13px;line-height:1.45}}
 main{{display:block;padding:1rem max(1rem,3vw) 0}}
 h1{{font-size:1.08rem;color:var(--text);letter-spacing:.01em;margin:0}} h2{{font-size:.76rem;color:var(--muted);margin:1rem 0 .35rem;text-transform:uppercase;letter-spacing:.08em}}
 a{{color:var(--accent)}} code,pre{{font-family:ui-monospace,Consolas,monospace}}
 table{{border-collapse:collapse;width:100%;margin-top:.5rem}}
 th,td{{border:1px solid var(--line);padding:.28rem .4rem;text-align:center}}
 th{{color:var(--muted);font-weight:600;background:#0d0f10}} td:first-child{{text-align:left}} tbody tr:nth-child(even){{background:#0d0f10}}
 tr.off{{opacity:.45}} .y{{color:var(--good)}} .n{{color:#55585a}}
 .card{{background:var(--panel);border:1px solid var(--line);border-radius:1px;padding:.7rem;margin:.45rem 0}}
 code{{color:#d7c48f}} .muted{{color:var(--muted);font-size:12px}}
 ul.rec{{margin:.3rem 0;padding-left:1.1rem}}
 .sev-high{{color:var(--bad)}} .sev-medium{{color:var(--warn)}} .sev-ok{{color:var(--good)}} .sev-info{{color:var(--muted)}}
 .ep{{margin:.2rem 0}} .ep.up{{color:var(--good)}} .ep.dn{{color:#666965}}
 header{{position:sticky;top:0;z-index:20;display:flex;justify-content:space-between;align-items:center;gap:1rem;min-height:62px;padding:.72rem max(1rem,3vw);border-bottom:1px solid var(--line);background:#0d0f10}}
 header .brand{{display:flex;align-items:center;gap:.7rem}} header .brand img{{width:34px;height:34px;display:block;border-radius:1px}}
 header .muted{{color:var(--muted);font-size:12px}}
 header nav{{display:flex;gap:0;align-items:center;flex-wrap:wrap;border:1px solid var(--line)}}
 header nav a{{padding:.43rem .72rem;border-right:1px solid var(--line);color:var(--muted);text-decoration:none}} header nav a:last-child{{border-right:0}} header nav a:hover{{color:var(--text);background:var(--raised)}} header nav a.active{{background:var(--accent);color:#17140d;font-weight:800}}
 input,button,select,textarea{{font:inherit;color:var(--text);background:#0b0c0d!important;border:1px solid var(--line)!important;border-radius:1px!important;padding:.32rem .5rem!important}} button{{background:var(--raised)!important;cursor:pointer}} button:hover{{border-color:var(--line-strong)!important;background:#202326!important}}
 a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
</style></head><body>
<header>
  <div class="brand"><img src="/aetherstack-icon.png" width="34" height="34" alt=""/><div><h1>AetherStack</h1><div class="muted">Choose the work. The system chooses the team.</div></div></div>
  <nav aria-label="AetherStack views"><a href="/">Simple</a><a class="active" aria-current="page" href="/advanced">Advanced</a><a href="/gdpr">Privacy</a><a href="http://127.0.0.1:3000/">WebUI</a></nav>
</header>
<main>
<div class="card">
 <b>System scan</b> —
 Ollama: <b>{"OK" if dsum.get("ollama_ok") else "DOWN"}</b>
 ({esc(dsum.get("ollama_models") or 0)} models) ·
 LiteLLM: <b>{"OK" if dsum.get("litellm_ok") else "DOWN"}</b> ·
 Redis: <b>{"OK" if dsum.get("redis_ok") else "DOWN"}</b> ·
 cloud keys: <b>{"yes" if dsum.get("cloud_keys") else "no"}</b>
 <div class="muted" style="margin-top:.35rem">{ep_html or "No Ollama endpoints probed yet — open /api/discover"}</div>
 <div style="margin-top:.5rem">
  <a href="/"><b>simple services</b></a> ·
  <a href="/api/discover">/api/discover</a> ·
  <a href="/api/discover?refresh=1">refresh</a> ·
  <a href="/api/modes">/api/modes</a> ·
  <a href="/api/combos">/api/combos</a> ·
  <a href="/api/pipelines">/api/pipelines</a> ·
  <a href="/api/xref">/api/xref</a> ·
  <a href="/api/privacy">/api/privacy</a> ·
  <a href="/graph"><b>node canvas</b></a> ·
  <a href="/api/matrix">matrix</a> ·
  <a href="/api/health">health</a>
 </div>
</div>
<div class="card" id="privCard">
 <b>Private mode</b> — isolated vault; no common session/xref/index/logs content
 <div class="muted" id="privState">…</div>
 <div style="margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.35rem;align-items:center">
  <input id="privPath" type="text" placeholder="project path or name" style="flex:1;min-width:140px;background:#0b1020;border:1px solid #243056;color:#e8eefc;padding:.3rem .5rem;border-radius:6px" />
  <input id="privModel" type="text" placeholder="model alias (optional)" style="min-width:120px;background:#0b1020;border:1px solid #243056;color:#e8eefc;padding:.3rem .5rem;border-radius:6px" />
  <button type="button" onclick="privOn()">set private</button>
  <button type="button" onclick="privRelease()">release</button>
  <button type="button" onclick="refreshPriv()">refresh</button>
 </div>
 <pre id="privOut" class="muted" style="white-space:pre-wrap;max-height:8rem;overflow:auto;font-size:11px"></pre>
 <div class="muted">Persists until release. Release does not merge vault into common pool. docs/PRIVATE-MODE.md</div>
</div>
<script>
async function refreshPriv(){{
  try {{
    const j = await fetch('/api/privacy').then(r=>r.json());
    document.getElementById('privState').textContent =
      'projects='+(j.private_project_count||0)+' · models='+(j.private_model_count||0);
    document.getElementById('privOut').textContent = JSON.stringify(j,null,2).slice(0,2500);
  }} catch(e) {{
    document.getElementById('privState').textContent = 'privacy unavailable';
  }}
}}
async function privOn(){{
  const path = document.getElementById('privPath').value;
  const model = document.getElementById('privModel').value;
  const body = {{private:true, session_id:'ui'}};
  if (path) body.path = path;
  if (model) body.model = model;
  if (!path && !model) body.path = 'ui-private-session';
  const j = await fetch('/api/privacy',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}}).then(r=>r.json());
  document.getElementById('privOut').textContent = JSON.stringify(j,null,2).slice(0,2500);
  refreshPriv();
}}
async function privRelease(){{
  const path = document.getElementById('privPath').value;
  let st = await fetch('/api/privacy').then(r=>r.json());
  let pid = Object.keys(st.projects||{{}})[0];
  if (path && st.projects) {{
    for (const [id,p] of Object.entries(st.projects)) {{
      if ((p.path||'').includes(path) || (p.name||'')===path || id===path) pid = id;
    }}
  }}
  if (!pid) {{ document.getElementById('privOut').textContent = 'no private project to release'; return; }}
  const j = await fetch('/api/privacy/release',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{project_id:pid,purge_vault:true}})}}).then(r=>r.json());
  document.getElementById('privOut').textContent = JSON.stringify(j,null,2).slice(0,2500);
  refreshPriv();
}}
refreshPriv();
</script>
<div class="card" id="xrefCard">
 <b>Cross-project memory</b> — scan LLM-native folders (.claude, .continue, .cursor, …) · multi-project pull
 <div class="muted" id="xrefState">…</div>
 <div style="margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.35rem;align-items:center">
  <button type="button" onclick="xrefMulti(true)">multi-project ON</button>
  <button type="button" onclick="xrefMulti(false)">OFF</button>
  <button type="button" onclick="xrefAuto(true)">auto-pull ON</button>
  <button type="button" onclick="xrefAuto(false)">auto-pull OFF</button>
  <input id="xrefQ" type="text" placeholder="search or pull query" style="flex:1;min-width:140px;background:#0b1020;border:1px solid #243056;color:#e8eefc;padding:.3rem .5rem;border-radius:6px" />
  <button type="button" onclick="xrefSearch()">search</button>
  <button type="button" onclick="xrefPull()">pull</button>
 </div>
 <pre id="xrefOut" class="muted" style="white-space:pre-wrap;max-height:10rem;overflow:auto;font-size:11px"></pre>
 <div class="muted">Host index (Docker cannot see Windows paths): <code>.\\scripts\\scan-cross-projects.ps1 -Paths D:\\code\\app -EnableMultiProject</code> · docs/CROSS-MEMORY.md</div>
</div>
<script>
async function refreshXref(){{
  try {{
    const j = await fetch('/api/xref').then(r=>r.json());
    const projs = Object.keys(j.projects||{{}});
    document.getElementById('xrefState').textContent =
      'multi_project='+j.multi_project+' · auto_pull='+j.auto_pull+' · projects='+(j.project_count||0)+
      (projs.length?(' · '+projs.slice(0,6).join(', ')):'');
  }} catch(e) {{
    document.getElementById('xrefState').textContent = 'xref unavailable';
  }}
}}
async function xrefMulti(v){{
  await fetch('/api/xref',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{multi_project:v}})}});
  refreshXref();
}}
async function xrefAuto(v){{
  await fetch('/api/xref',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{auto_pull:v}})}});
  refreshXref();
}}
async function xrefSearch(){{
  const q = document.getElementById('xrefQ').value || 'tested concept';
  const j = await fetch('/api/xref/search',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{query:q,top_k:8}})}}).then(r=>r.json());
  document.getElementById('xrefOut').textContent = JSON.stringify(j,null,2).slice(0,3500);
}}
async function xrefPull(){{
  const q = document.getElementById('xrefQ').value || 'tested concept';
  const j = await fetch('/api/xref/pull',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{query:q}})}}).then(r=>r.json());
  document.getElementById('xrefOut').textContent = (j.prompt_block||JSON.stringify(j,null,2)).slice(0,4000);
}}
refreshXref();
</script>
<div class="card" id="pipeCard">
 <b>Pipeline scripts</b> — research → critique → build → test (tier/cost per stage)
 <div class="muted" id="pipeList">…</div>
 <div id="pipeBtns" style="margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.35rem"></div>
 <pre id="pipeOut" class="muted" style="white-space:pre-wrap;max-height:8rem;overflow:auto;font-size:11px"></pre>
</div>
<script>
async function refreshPipes(){{
  try {{
    const j = await fetch('/api/pipelines').then(r=>r.json());
    const pipes = j.pipelines||[];
    document.getElementById('pipeList').textContent = pipes.map(p =>
      p.id+' (score '+(p.votes&&p.votes.score||0)+', hw='+p.hw_weight+')'
    ).join(' · ') || 'none';
    const box = document.getElementById('pipeBtns');
    box.innerHTML = '';
    for (const p of pipes.slice(0,6)) {{
      const b = document.createElement('button');
      b.type='button'; b.textContent='plan:'+p.id;
      b.onclick = () => planPipe(p.id);
      box.appendChild(b);
      const u = document.createElement('button');
      u.type='button'; u.textContent='▲';
      u.onclick = () => votePipe(p.id, true);
      box.appendChild(u);
    }}
  }} catch(e) {{
    document.getElementById('pipeList').textContent = 'pipelines unavailable';
  }}
}}
async function planPipe(id){{
  const j = await fetch('/api/pipelines/'+encodeURIComponent(id)+'/plan',{{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{goal:'Demo pipeline run', session_id:'ui'}})
  }}).then(r=>r.json());
  document.getElementById('pipeOut').textContent = (j.flow||'')+'\\n'+JSON.stringify(j.stages,null,2).slice(0,2000);
}}
async function votePipe(id, up){{
  await fetch('/api/pipelines/'+encodeURIComponent(id)+'/vote',{{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{up:up, down:!up, voter:'ui'}})
  }});
  refreshPipes();
}}
refreshPipes();
</script>
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
 matrix live: local <b>{esc(summary.get('local_online'))}</b> · cloud <b>{esc(summary.get('cloud_ready'))}</b> · down <b>{esc(summary.get('unavailable'))}</b>
 · memory <b>{esc(_memory.backend)}</b>
</div>
<h2>Capability matrix (live availability)</h2>
<table>
<thead><tr><th>model</th><th>tier</th><th>live</th>{head}</tr></thead>
<tbody>
{table}
</tbody>
</table>
<div class="card">
 <b>Slash commands</b> (archive to memory → clear context)
 <div class="muted">/status · /task add … · /done all · /save · /clear · /compact</div>
 <div style="margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.35rem;align-items:center">
  <input id="slashIn" type="text" placeholder="/status or /clear" style="flex:1;min-width:160px;background:#0b1020;border:1px solid #243056;color:#e8eefc;padding:.3rem .5rem;border-radius:6px" />
  <button type="button" onclick="runSlash()">run</button>
  <button type="button" onclick="runSlashText('/done all')">/done all</button>
  <button type="button" onclick="runSlashText('/clear')">/clear</button>
  <button type="button" onclick="runSlashText('/compact')">/compact</button>
 </div>
 <pre id="slashOut" class="muted" style="white-space:pre-wrap;max-height:10rem;overflow:auto;font-size:11px"></pre>
</div>
<script>
async function runSlashText(t){{
  document.getElementById('slashIn').value = t;
  return runSlash();
}}
async function runSlash(){{
  const text = document.getElementById('slashIn').value || '/help';
  const j = await fetch('/api/slash',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{session_id:'ui',text}})}}).then(r=>r.json());
  document.getElementById('slashOut').textContent = JSON.stringify(j,null,2).slice(0,3000);
}}
</script>
<p class="muted" style="margin-top:1rem">Memory: POST /api/memory/vectors · POST /api/memory/search · docs/SLASH-COMMANDS.md</p>
</main>
</body></html>"""
    return html.encode("utf-8")


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Keep long-lived SSE clients from creating an unbounded number of threads."""

    daemon_threads = True

    def __init__(self, server_address, request_handler_class, max_threads: int = MAX_REQUEST_THREADS):
        self._request_slots = threading.BoundedSemaphore(max_threads)
        super().__init__(server_address, request_handler_class)

    def process_request(self, request, client_address) -> None:
        # This runs on the single accept-loop thread (serve_forever calls it
        # directly, not in a worker thread) - a blocking acquire() here stalls
        # every client, not just the one over the limit, the moment all slots
        # are held (e.g. by long-lived SSE connections). Reject immediately
        # instead: closing the socket is a hard failure for that one caller,
        # but the hub keeps accepting everyone else.
        if not self._request_slots.acquire(blocking=False):
            try:
                request.close()
            except Exception:
                pass
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


def main() -> None:
    _validate_public_binding()
    print("[hub] agent modes + token saver…")
    init_runtime_from_config()
    print(f"[hub] mode={get_runtime().get('mode')} token_saver={get_runtime().get('token_saver')}")
    print(
        f"[hub] edition={hub_auth.edition()} require_auth={hub_auth.require_auth()} "
        f"oidc={'on' if hub_auth.oidc_issuer() else 'off'}"
    )
    print("[hub] initial system discover…")
    refresh_snapshot()
    t = threading.Thread(target=_bg_sync, daemon=True)
    t.start()
    httpd = BoundedThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Aether Hub -> http://{HOST}:{PORT}/")
    print("  FIRST:  GET /api/discover")
    print("  AUTH:   GET /api/auth/config  POST /api/auth/token  GET /api/auth/me")
    print("  TENANT: GET|POST /api/tenancy/projects")
    print("  MODES:  GET|POST /api/modes   (inline|multi_agent, token_saver)")
    print("  PLAN:   POST /api/agents/plan (multi-LLM event)")
    print("  SLASH:  POST /api/slash  {\"text\":\"/clear\"}  (archive -> clear)")
    print("  XREF:   GET|POST /api/xref  (multi-project memory; off by default)")
    print("  PRIV:   GET|POST /api/privacy  (private project/model vault; until release)")
    print("  GRAPH:  http://{HOST}:{PORT}/graph  (node canvas)".format(HOST=HOST, PORT=PORT))
    print("  ROUTE:  GET /api/route?need=code&prefer=local")
    print(f"  redis:  {REDIS_URL}  backend={_memory.backend}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()


if __name__ == "__main__":
    main()
