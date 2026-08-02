#!/usr/bin/env python3
"""Pipeline stage model resolution: fallback picking must not leak global runtime state."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents import get_runtime  # noqa: E402
from pipelines import _pick_for_stage  # noqa: E402


def _snapshot() -> dict:
    return {
        "models": {
            "claude-cli": {
                "available": True,
                "tier": "subscription",
                "provider": "anthropic",
                "capabilities": ["chat"],
            },
        }
    }


def test_stage_fallback_does_not_mutate_global_runtime() -> None:
    before = get_runtime()["role_overrides"]
    assert before == {}

    stage = {
        "id": "s1",
        "role": "builder",
        "select": {"maker": "nobody"},  # filters out every available model
        "needs": ["chat"],
    }
    result = _pick_for_stage(_snapshot(), stage)

    assert result["selection"] == "fallback_role_picker"
    after = get_runtime()["role_overrides"]
    assert after == {}, f"stage fallback leaked into global runtime: {after}"
