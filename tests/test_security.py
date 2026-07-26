from __future__ import annotations

import io
import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO = Path(__file__).resolve().parents[1]
HUB = REPO / "aether-hub"
sys.path.insert(0, str(HUB))

import backup  # noqa: E402
import graph  # noqa: E402
import server as hub_server  # noqa: E402


def load_project_server():
    path = REPO / "project-engine" / "server.py"
    spec = importlib.util.spec_from_file_location("aether_project_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(module)
    return module


class SecurityBoundaryTests(unittest.TestCase):
    def test_brand_icon_is_consistent_across_surfaces(self) -> None:
        icon_paths = (
            REPO / "aetherstack-icon.png",
            HUB / "static" / "aetherstack-icon.png",
            REPO / "project-engine" / "static" / "aetherstack-icon.png",
            REPO / "extension" / "aetherstack.png",
            REPO / "extension" / "ui" / "aetherstack-icon.png",
            REPO / "integrations" / "vscode" / "media" / "icon.png",
        )
        payloads = [path.read_bytes() for path in icon_paths]
        self.assertTrue(all(hashlib.sha256(data).digest() == hashlib.sha256(payloads[0]).digest() for data in payloads))
        self.assertEqual(payloads[0][:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", payloads[0][16:24])
        self.assertEqual((width, height), (256, 256))

    def test_hub_serves_brand_icon_as_png(self) -> None:
        sent = []
        fake = SimpleNamespace(
            path="/aetherstack-icon.png",
            _send=lambda code, value, content_type="application/json; charset=utf-8": sent.append(
                (code, value, content_type)
            ),
        )
        hub_server.Handler.do_GET(fake)
        self.assertEqual(sent[0][0], 200)
        self.assertEqual(sent[0][2], "image/png")
        self.assertEqual(sent[0][1][:8], b"\x89PNG\r\n\x1a\n")

    def test_graph_id_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_dir = graph.GRAPH_DIR
            graph.GRAPH_DIR = Path(td) / "graphs"
            try:
                with self.assertRaises(ValueError):
                    graph.save_graph({"id": "../../escaped", "nodes": [], "edges": []})
                self.assertFalse((Path(td) / "escaped.aether-graph.json").exists())
            finally:
                graph.GRAPH_DIR = old_dir

    def test_backup_output_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            payload = {
                "id": "aether-backup-test",
                "vectors": {},
                "sessions": {},
                "project_files": {"../../escaped.txt": "secret"},
            }
            with self.assertRaises(ValueError):
                backup.write_local_backup(payload, dest_dir=td, as_zip=False)
            self.assertFalse((Path(td).parent / "escaped.txt").exists())

    def test_hub_rejects_cross_site_origins(self) -> None:
        self.assertTrue(hub_server._request_origin_allowed(None, "127.0.0.1:8766"))
        self.assertTrue(
            hub_server._request_origin_allowed(
                "http://127.0.0.1:8766", "127.0.0.1:8766"
            )
        )
        self.assertFalse(
            hub_server._request_origin_allowed("https://attacker.example", "127.0.0.1:8766")
        )

    def test_hub_json_body_is_bounded_and_object_only(self) -> None:
        fake = SimpleNamespace(
            headers={"Content-Length": "2", "Content-Type": "application/json"},
            rfile=io.BytesIO(b"{}"),
        )
        self.assertEqual(hub_server.Handler._read_json(fake), {})

        too_large = SimpleNamespace(
            headers={
                "Content-Length": str(hub_server.MAX_JSON_BODY + 1),
                "Content-Type": "application/json",
            },
            rfile=io.BytesIO(),
        )
        with self.assertRaises(ValueError):
            hub_server.Handler._read_json(too_large)

        array_body = b"[]"
        array_request = SimpleNamespace(
            headers={
                "Content-Length": str(len(array_body)),
                "Content-Type": "application/json",
            },
            rfile=io.BytesIO(array_body),
        )
        with self.assertRaises(ValueError):
            hub_server.Handler._read_json(array_request)

    def test_project_static_containment_is_component_aware(self) -> None:
        project_server = load_project_server()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "static"
            sibling = Path(td) / "static-evil" / "payload.js"
            self.assertTrue(project_server._path_under(root / "app.js", root))
            self.assertFalse(project_server._path_under(sibling, root))

    def test_project_dashboard_escapes_dynamic_html(self) -> None:
        html = (REPO / "project-engine" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("function esc(value)", html)
        self.assertIn("${esc(j.path)}", html)
        self.assertNotIn("${j.path}</code>", html)

    def test_simple_hub_renders_api_content_without_inner_html(self) -> None:
        html = (HUB / "static" / "simple.html").read_text(encoding="utf-8")
        self.assertNotIn(".innerHTML", html)
        self.assertIn("textContent", html)
        self.assertIn("/api/update/stage", html)
        self.assertIn("/api/services/", html)
        self.assertIn('id="serviceGraphFrame"', html)
        self.assertIn("/graph?embed=1&service=", html)
        self.assertNotIn('class="graph-flow"', html)
        self.assertIn("align-items:stretch", html)
        self.assertIn("Selected service workspace", html)

    def test_advanced_graph_loads_capability_resolved_service_trees(self) -> None:
        html = (HUB / "static" / "graph.html").read_text(encoding="utf-8")
        self.assertIn('id="servicePreset"', html)
        self.assertIn("/api/services/${encodeURIComponent(id)}/graph", html)
        self.assertIn("d.label || TYPES[n.type]?.label", html)
        self.assertIn('id="inspectorAgent"', html)
        self.assertIn('fetch("/api/matrix")', html)
        self.assertIn("model.available", html)
        self.assertIn('node.type === "master"', html)

    def test_open_webui_and_litellm_privacy_defaults(self) -> None:
        for compose_path in (
            REPO / "docker-compose.yml",
            REPO / "extension" / "docker-compose.yaml",
        ):
            compose = compose_path.read_text(encoding="utf-8")
            self.assertIn(
                "CACHE_CONTROL=no-cache, no-store, must-revalidate, max-age=0",
                compose,
            )
            self.assertIn("WEBUI_SESSION_COOKIE_SAME_SITE=strict", compose)
            self.assertIn("WEBUI_AUTH_COOKIE_SAME_SITE=strict", compose)
            self.assertIn("chmod -R go-rwx /app/backend/data", compose)

        litellm = (REPO / "litellm_config.yaml").read_text(encoding="utf-8")
        self.assertIn("cache: false", litellm)
        self.assertNotIn("cache: true", litellm)

        gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("*.db", "*.sqlite", "*.sqlite3", "cache/", ".cache/"):
            self.assertIn(pattern, gitignore)

    def test_inference_status_contains_model_metadata_without_prompt_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            status_path = Path(td) / "inference-status.json"
            payload = {
                "active": [{"callId": "call-1", "model": "local-default", "startedAt": 1}],
                "activeCount": 1,
                "last": None,
            }
            status_path.write_text(json.dumps(payload), encoding="utf-8")
            code, result = hub_server.get_inference_status(status_path)
            self.assertEqual(code, 200)
            self.assertEqual(result, payload)
            self.assertNotIn("messages", json.dumps(result))
            self.assertNotIn("response", json.dumps(result))

            missing_code, missing = hub_server.get_inference_status(Path(td) / "missing.json")
            self.assertEqual(missing_code, 200)
            self.assertEqual(missing["activeCount"], 0)

    def test_inference_status_is_a_get_endpoint(self) -> None:
        sent = []
        fake = SimpleNamespace(
            path="/api/inference/status",
            _send=lambda code, value, content_type="application/json; charset=utf-8": sent.append(
                (code, value, content_type)
            ),
        )
        hub_server.Handler.do_GET(fake)
        self.assertEqual(sent[0][0], 200)
        self.assertIn("activeCount", sent[0][1])


if __name__ == "__main__":
    unittest.main()
