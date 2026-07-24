#!/usr/bin/env python3
"""AetherStack Project Data Management Engine — local dashboard + JSON API."""
from __future__ import annotations

import argparse
import json
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


def _allowed_roots(project_default: str | None) -> list[Path]:
    """Roots that /api/project and /api/full may inspect."""
    roots: list[Path] = []
    candidates = [
        Path.cwd().resolve(),
        Path.home().resolve(),
        ROOT.parent.resolve(),  # AetherStack repo
    ]
    if project_default:
        try:
            candidates.append(Path(project_default).expanduser().resolve())
        except OSError:
            pass
    if sys.platform == "win32":
        for letter in "CDEFGHIJ":
            p = Path(f"{letter}:/")
            if p.exists():
                candidates.append(p.resolve())
    else:
        for p in (Path("/home"), Path("/opt"), Path("/var"), Path("/tmp")):
            if p.exists():
                candidates.append(p.resolve())
    seen: set[str] = set()
    for c in candidates:
        key = str(c)
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
    try:
        target = Path(str(raw).strip()).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as e:
        return None, f"invalid path: {e}"
    if not target.exists() or not target.is_dir():
        return None, f"Not a directory: {target}"
    # Reject null bytes / odd control chars
    if "\x00" in str(raw):
        return None, "invalid path"
    allowed = _allowed_roots(project_default)
    t_str = str(target)
    for root in allowed:
        r_str = str(root)
        if t_str == r_str or t_str.startswith(r_str + "\\") or t_str.startswith(r_str + "/"):
            return target, None
    return None, (
        "path not under allowed roots (cwd, home, AetherStack repo, "
        "optional --project parent drives). Refusing filesystem scan."
    )


class Handler(BaseHTTPRequestHandler):
    project_default: str | None = None

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[engine] " + (fmt % args) + "\n")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Local tool only — do not open responses to arbitrary web origins
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path
        qs = parse_qs(u.query)
        project_raw = (qs.get("path") or qs.get("project") or [self.project_default])[0]

        if path in ("/", "/index.html"):
            html = (STATIC / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            # block path traversal in static
            if ".." in rel.replace("\\", "/").split("/"):
                self._json(404, {"error": "not found"})
                return
            fp = (STATIC / rel).resolve()
            if not str(fp).startswith(str(STATIC.resolve())) or not fp.is_file():
                self._json(404, {"error": "not found"})
                return
            ctype = "text/css" if fp.suffix == ".css" else "application/javascript" if fp.suffix == ".js" else "application/octet-stream"
            self._send(200, fp.read_bytes(), ctype)
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
                    # full without project still returns live+system
                    self._json(200, full_report(None))
                else:
                    self._json(200, full_report(str(target)))
            elif path == "/api/health":
                self._json(200, {"ok": True, "service": "aetherstack-project-engine"})
            else:
                self._json(404, {"error": "not found", "paths": ["/", "/api/live", "/api/system", "/api/project", "/api/full"]})
        except Exception as e:
            self._json(500, {"error": str(e)})


def main() -> None:
    ap = argparse.ArgumentParser(description="AetherStack Project Data Management Engine")
    ap.add_argument("--host", default="127.0.0.1", help="Bind address (default localhost only)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--project", default=None, help="Default project path for scans")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"WARNING: binding to {args.host!r} exposes filesystem scan APIs. Prefer 127.0.0.1.",
            file=sys.stderr,
        )

    Handler.project_default = args.project
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    if args.project:
        url += f"?project={args.project}"
    print(f"AetherStack Project Engine → {url}")
    print("API: /api/live  /api/system  /api/project?path=  /api/full")
    print("Project scans restricted to allowed roots (cwd, home, repo, drives).")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()


if __name__ == "__main__":
    main()
