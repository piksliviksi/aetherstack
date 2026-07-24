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


class Handler(BaseHTTPRequestHandler):
    project_default: str | None = None

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[engine] " + (fmt % args) + "\n")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path
        qs = parse_qs(u.query)
        project = (qs.get("path") or qs.get("project") or [self.project_default])[0]

        if path in ("/", "/index.html"):
            html = (STATIC / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            rel = path[len("/static/") :]
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
                if not project:
                    self._json(400, {"error": "pass ?path= or start with --project"})
                else:
                    self._json(200, project_impact(project))
            elif path == "/api/full":
                self._json(200, full_report(project))
            elif path == "/api/health":
                self._json(200, {"ok": True, "service": "aetherstack-project-engine"})
            else:
                self._json(404, {"error": "not found", "paths": ["/", "/api/live", "/api/system", "/api/project", "/api/full"]})
        except Exception as e:
            self._json(500, {"error": str(e)})


def main() -> None:
    ap = argparse.ArgumentParser(description="AetherStack Project Data Management Engine")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--project", default=None, help="Default project path for scans")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    Handler.project_default = args.project
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    if args.project:
        url += f"?project={args.project}"
    print(f"AetherStack Project Engine → {url}")
    print("API: /api/live  /api/system  /api/project?path=  /api/full")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()


if __name__ == "__main__":
    main()
