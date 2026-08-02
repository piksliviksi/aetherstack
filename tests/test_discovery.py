from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock


HUB = Path(__file__).resolve().parents[1] / "aether-hub"
sys.path.insert(0, str(HUB))

import discover  # noqa: E402
import matrix  # noqa: E402


def test_discovery_requires_the_ollama_version_api() -> None:
    with mock.patch.object(discover, "_http", return_value=(200, "not Ollama")) as request:
        result = discover.probe_ollama_endpoint("http://example.test:11434", "test")
    assert result["reachable"] is False
    assert result["error"]["code"] == "ollama_version_probe_failed"
    request.assert_called_once_with("http://example.test:11434/api/version", timeout=3.0)


def test_matrix_ollama_probe_reports_why_it_failed() -> None:
    with mock.patch.object(matrix, "_http_json_result", return_value=(None, "connection failed: refused")):
        result = matrix.probe_ollama("http://example.test:11434")
    assert result == {
        "base": "http://example.test:11434",
        "ok": False,
        "models": [],
        "reason": "connection failed: refused",
    }
