#!/usr/bin/env python3
"""Unit tests for Auto mode: host-CLI chain + failover + local Ollama fallback."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import (  # noqa: E402
    DEFAULT_MEMORY_CONTEXT_KB,
    MEMORY_CONTEXT_KB_OPTIONS,
    describe_auto_mode,
    execute_auto,
    is_failover_error,
    list_auto_failover_chain,
    memory_context_chars,
    resolve_memory_context_kb,
    _auto_memory_block,
    _auto_session_model,
)


def _snap() -> dict:
    return {
        "models": {
            "grok-cli": {
                "available": True,
                "executor": "host_cli",
                "tier": "subscription",
                "provider": "xai",
                "backend": "host-cli/grok",
                "capabilities": ["chat", "code", "reason"],
            },
            "claude-cli": {
                "available": True,
                "executor": "host_cli",
                "tier": "subscription",
                "provider": "anthropic",
                "backend": "host-cli/claude",
                "capabilities": ["chat", "code", "reason"],
            },
            "codex-cli": {
                "available": False,
                "executor": "host_cli",
                "tier": "subscription",
                "provider": "openai",
                "capabilities": ["chat", "code"],
            },
            "local-default": {
                "available": True,
                "tier": "local",
                "provider": "ollama",
                "backend": "ollama/qwen",
                "capabilities": ["chat", "code"],
            },
            "local-tiny": {
                "available": True,
                "tier": "local",
                "provider": "ollama",
                "capabilities": ["chat"],
            },
        }
    }


def test_chain_order() -> None:
    chain = list_auto_failover_chain(_snap())
    models = [c["model"] for c in chain]
    assert models[0] == "grok-cli"
    assert "claude-cli" in models
    assert "codex-cli" not in models  # unavailable
    assert models.index("local-default") > models.index("claude-cli")
    assert "local-tiny" in models


def test_sticky_and_local_only() -> None:
    _auto_session_model["s1"] = "claude-cli"
    chain = list_auto_failover_chain(_snap(), session_id="s1")
    assert chain[0]["model"] == "claude-cli"
    local = list_auto_failover_chain(_snap(), prefer_local=True)
    assert all(c.get("tier") == "local" or c["model"].startswith("local") for c in local)
    assert local[0]["model"] == "local-default"


def test_failover_error_detection() -> None:
    assert is_failover_error("Error 429 rate limit exceeded")
    assert is_failover_error("weekly limit reached for this account")
    assert is_failover_error("insufficient_quota")
    assert not is_failover_error("syntax error in user code")


def test_execute_auto_failsover_to_local() -> None:
    calls: list[str] = []

    def completion(call: dict, messages=None) -> dict:
        model = call["model"]
        calls.append(model)
        if model.endswith("-cli"):
            raise RuntimeError("429 rate limit: weekly quota exceeded")
        return {"model": model, "content": f"ok from {model}", "usage": {"total_tokens": 3}}

    result = execute_auto(
        _snap(),
        {"goal": "Write a hello world function"},
        completion=completion,
        session_id="fail-over-test",
    )
    assert result["ok"] is True
    assert result["auto_mode"] is True
    assert result["model"] == "local-default"
    assert result["memory"] == "unified"
    assert "grok-cli" in calls and "claude-cli" in calls and "local-default" in calls
    assert len(result["failover_attempts"]) >= 2
    assert _auto_session_model.get("fail-over-test") == "local-default"


def test_describe_auto() -> None:
    d = describe_auto_mode(_snap())
    assert d["service_id"] == "auto"
    assert d["memory"] == "unified"
    assert d["host_cli_count"] >= 2
    assert d["local_count"] >= 1
    assert d["memory_context_kb"] == DEFAULT_MEMORY_CONTEXT_KB
    assert d["memory_context_options_kb"] == list(MEMORY_CONTEXT_KB_OPTIONS)


def test_memory_context_budget() -> None:
    assert resolve_memory_context_kb(None) == 512
    assert resolve_memory_context_kb(256) == 256
    assert resolve_memory_context_kb(9999) == 2048  # nearest
    assert memory_context_chars(512) == 512 * 1024
    # budget must bound injected block
    class FakeMem:
        def get_session(self, sid, limit=50):
            return [{"role": "user", "content": "x" * 50000} for _ in range(40)]

        def search(self, query, namespace="default", top_k=5):
            return {"hits": [{"score": 0.9, "text": "y" * 20000}]}

    block = _auto_memory_block(FakeMem(), "s", "goal", None, context_kb=256)
    assert len(block) <= memory_context_chars(256) + 64


def main() -> None:
    test_chain_order()
    test_sticky_and_local_only()
    test_failover_error_detection()
    test_execute_auto_failsover_to_local()
    test_describe_auto()
    test_memory_context_budget()
    print("ok test_auto_mode")


if __name__ == "__main__":
    main()
