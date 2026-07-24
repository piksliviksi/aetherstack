#!/usr/bin/env python3
"""AetherStack Project Data Management Engine — local dashboard + JSON API."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from collectors import full_report, live_metrics, project_impact, system_footprint  # noqa: E402

STATIC = ROOT / "static"
DEFAULT_PORT = 8765


def _path_under(target: Path, root: Path) -> bool:
    """True if target is root or a strict descendant (no prefix tricks)."""
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed_roots(project_default: str | None) -> list[Path]:
    """
    Roots that /api/project and /api/full may inspect.

    Intentionally narrow — no whole drive letters / no /var|/opt|/tmp.
    """
    candidates: list[Path] = [
        Path.cwd().resolve(),
        Path.home().resolve(),
        ROOT.parent.resolve(),  # AetherStack repo
        ROOT.resolve(),
    ]
    if project_default:
        try:
            p = Path(project_default).expanduser().resolve()
            candidates.append(p)
            # Allow scanning the project itself and its immediate parent workspace
            if p.parent and p.parent != p:
                candidates.append(p.parent.resolve())
        except OSError:
            pass

    seen: set[str] = set()
    roots: list[Path] = []
    for c in candidates:
        try:
            key = str(c.resolve())
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            roots.append(c)
    return roots


def resolve_project_path(raw: str | None, project_default: str | None) -> tuple[Path | None, str | None]:
    """
    Resolve and authorize a project path.
    Returns (path, error_message).
    """
    if not raw or not str(raw).strip():
        return None, "pass ?path= or start with --project"
    if "\x00" in str(raw):
        return None, "invalid path"
    try:
        target = Path(str(raw).strip()).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as e:
        return None, f"invalid path: {e}"
    if not target.exists() or not target.is_dir():
        return None, f"Not a directory: {target}"

    allowed = _allowed_roots(project_default)
    for root in allowed:
        if _path_under(target, root):
            return target, None
    roots_hint = ", ".join(str(r) for r in allowed[:6])
    more = " …" if len(allowed) > 6 else ""
    return None, (
        "path not under allowed roots (cwd, home, AetherStack repo, --project). "
        f"Allowed: {roots_hint}{more}. Refusing filesystem scan."
    )


class Handler(BaseHTTPRequestHandler):
    project_default: str | None = None
    engine_token: str | None = None  # if set, required for /api/*

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[engine] " + (fmt % args) + "\n")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Local tool only — do not open responses to arbitrary web origins
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Aether-Token")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _client_token(self, qs: dict) -> str | None:
        auth = self.headers.get("X-Aether-Token") or self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        if auth and not auth.lower().startswith("bearer"):
            # raw header value if not Bearer scheme
            if self.headers.get("X-Aether-Token"):
                return self.headers.get("X-Aether-Token", "").strip()
        xt = self.headers.get("X-Aether-Token")
        if xt:
            return xt.strip()
        t = (qs.get("token") or [None])[0]
        return t.strip() if t else None

    def _require_api_auth(self, qs: dict) -> bool:
        """Return True if request may proceed; send 401 and return False if blocked."""
        expected = self.engine_token
        if not expected:
            return True
        got = self._client_token(qs)
        if (
            got
            and len(got) == len(expected)
            and secrets.compare_digest(got, expected)
        ):
            return True
        self._json(
            401,
            {
                "error": "unauthorized",
                "hint": "Set header X-Aether-Token or ?token= (env AETHERSTACK_ENGINE_TOKEN / --token)",
            },
        )
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Aether-Token")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path
        qs = parse_qs(u.query)
        project_raw = (qs.get("path") or qs.get("project") or [self.project_default])[0]

        if path in ("/", "/index.html"):
            html = (STATIC / "index.html").read_bytes()
            # Soft hint for UI: whether token is required (never embed the secret)
            flag = b"true" if self.engine_token else b"false"
            html = html.replace(b"__AETHER_TOKEN_REQUIRED__", flag)
            roots = [str(r) for r in _allowed_roots(self.project_default)]
            html = html.replace(
                b"__AETHER_ALLOWED_ROOTS__",
                json.dumps(roots).encode("utf-8"),
            )
            self._send(200, html, "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            if ".." in rel.replace("\\", "/").split("/"):
                self._json(404, {"error": "not found"})
                return
            fp = (STATIC / rel).resolve()
            if not str(fp).startswith(str(STATIC.resolve())) or not fp.is_file():
                self._json(404, {"error": "not found"})
                return
            ctype = (
                "text/css"
                if fp.suffix == ".css"
                else "application/javascript"
                if fp.suffix == ".js"
                else "application/octet-stream"
            )
            self._send(200, fp.read_bytes(), ctype)
            return

        # API routes need optional token
        if path.startswith("/api/"):
            if path != "/api/health" and not self._require_api_auth(qs):
                return

        try:
            if path == "/api/live":
                self._json(200, live_metrics())
            elif path == "/api/system":
                self._json(200, system_footprint())
            elif path == "/api/project":
                target, err = resolve_project_path(project_raw, self.project_default)
                if err:
                    self._json(400, {"error": err})
                else:
                    self._json(200, project_impact(str(target)))
            elif path == "/api/full":
                target, err = resolve_project_path(project_raw, self.project_default)
                if err and project_raw:
                    self._json(400, {"error": err})
                elif err:
                    self._json(200, full_report(None))
                else:
                    self._json(200, full_report(str(target)))
            elif path == "/api/health":
                self._json(
                    200,
                    {
                        "ok": True,
                        "service": "aetherstack-project-engine",
                        "auth_required": bool(self.engine_token),
                    },
                )
            elif path == "/api/roots":
                self._json(
                    200,
                    {
                        "allowed_roots": [str(r) for r in _allowed_roots(self.project_default)],
                        "auth_required": bool(self.engine_token),
                    },
                )
            else:
                self._json(
                    404,
                    {
                        "error": "not found",
                        "paths": [
                            "/",
                            "/api/live",
                            "/api/system",
                            "/api/project",
                            "/api/full",
                            "/api/health",
                            "/api/roots",
                        ],
                    },
                )
        except Exception as e:
            self._json(500, {"error": str(e)})


def main() -> None:
    ap = argparse.ArgumentParser(description="AetherStack Project Data Management Engine")
    ap.add_argument("--host", default="127.0.0.1", help="Bind address (default localhost only)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--project", default=None, help="Default project path for scans")
    ap.add_argument(
        "--token",
        default=os.environ.get("AETHERSTACK_ENGINE_TOKEN") or None,
        help="Optional shared secret for /api/* (or env AETHERSTACK_ENGINE_TOKEN)",
    )
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"WARNING: binding to {args.host!r} exposes filesystem scan APIs. Prefer 127.0.0.1.",
            file=sys.stderr,
        )

    Handler.project_default = args.project
    Handler.engine_token = (args.token or "").strip() or None
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    if args.project:
        url += f"?project={args.project}"
    print(f"AetherStack Project Engine → {url}")
    print("API: /api/live  /api/system  /api/project?path=  /api/full  /api/roots")
    print("Project scans: cwd, home, AetherStack repo, --project only (no whole drives).")
    if Handler.engine_token:
        print("Auth: ON — send X-Aether-Token or ?token= for /api/* (except /api/health).")
    else:
        print("Auth: OFF — set AETHERSTACK_ENGINE_TOKEN or --token to require a secret.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()


if __name__ == "__main__":
    main()
