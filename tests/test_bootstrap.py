from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "aether-hub"))

import bootstrap  # noqa: E402


def _discover(ram_gb: float) -> dict:
    return {
        "host_scan": {"ram_gb": ram_gb},
        "ollama": {
            "any_reachable": True,
            "all_model_names": [],
            "primary": {"base": "http://127.0.0.1:11434"},
        },
        "services": {"litellm": {"ok": True}, "redis": {"ok": True}},
        "runtime": {},
    }


def _pull_names(plan: dict) -> list[str]:
    return [action["id"].split(":", 1)[1] for action in plan["actions"] if action["category"] == "ollama_models"]


def test_bootstrap_selects_llama_on_capable_host() -> None:
    names = _pull_names(bootstrap.build_install_plan(_discover(24)))
    assert "qwen2.5-coder:1.5b" in names
    assert "llama3.1:8b" in names
    assert "nomic-embed-text" in names
    assert "tinyllama" not in names


def test_bootstrap_selects_small_fallback_on_low_memory_host() -> None:
    names = _pull_names(bootstrap.build_install_plan(_discover(8)))
    assert "qwen2.5-coder:1.5b" in names
    assert "nomic-embed-text" in names
    assert "llama3.1:8b" not in names
