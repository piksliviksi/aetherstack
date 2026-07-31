#!/usr/bin/env python3
"""First-run setup: step reporting, and the consent boundary around installing."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import first_run  # noqa: E402


def _discover() -> dict:
    return {
        "ts": 1234567890.0,
        "runtime": {"platform": "win32", "docker": True},
        "gpu_hints": {"vendor": "AMD"},
        "ollama": {"any_reachable": True, "all_model_names": ["qwen2.5-coder:1.5b"]},
        "summary": {"cloud_keys": True},
    }


def _snapshot() -> dict:
    return {
        "models": {
            "claude-cli": {"available": True, "executor": "host_cli", "tier": "subscription"},
            "codex-cli": {"available": False, "executor": "host_cli", "tier": "subscription"},
            "local-default": {"available": True, "tier": "local"},
        }
    }


def _isolate(tmp_path, monkeypatch, actions=()) -> None:
    """Own state file + a stub plan, so step logic is not read off this machine."""
    monkeypatch.setattr(first_run, "STATE_FILE", tmp_path / "first_run.json")
    monkeypatch.setattr(
        first_run,
        "plan_and_maybe_apply",
        lambda discover, **kw: {"plan": {"actions": list(actions)}, "run": None},
    )


def test_status_reports_every_step(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    result = first_run.status(_discover(), _snapshot(), auto_order=["claude-cli"], saved_order=True)
    steps = {step["id"]: step for step in result["steps"]}
    assert set(steps) == set(first_run.STEP_IDS)
    assert steps["scan"]["done"] is True
    assert steps["scan"]["detail"]["gpu"] == "AMD"
    assert steps["scan"]["detail"]["local_models"] == ["qwen2.5-coder:1.5b"]
    # only available models count as connected
    assert steps["connect"]["done"] is True
    assert steps["connect"]["host_cli"] == ["claude-cli"]
    assert steps["connect"]["local"] == ["local-default"]
    assert steps["order"]["done"] is True
    assert result["ready"] is True


def test_unsaved_order_leaves_the_flow_incomplete(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    result = first_run.status(_discover(), _snapshot(), auto_order=[], saved_order=False)
    assert result["next_step"] == "order"
    assert result["completed"] is False


def test_no_models_means_not_ready(tmp_path, monkeypatch) -> None:
    _isolate(tmp_path, monkeypatch)
    empty = {"models": {"codex-cli": {"available": False, "executor": "host_cli"}}}
    result = first_run.status(_discover(), empty, saved_order=True)
    assert result["ready"] is False
    assert result["next_step"] == "connect"


def test_run_without_confirm_installs_nothing(tmp_path, monkeypatch) -> None:
    """The consent boundary: no confirm, no apply."""
    monkeypatch.setattr(first_run, "STATE_FILE", tmp_path / "first_run.json")
    applied_calls = []

    def _spy(discover, *, confirm=False, dry_run=True, only_safe=True):
        applied_calls.append({"confirm": confirm, "dry_run": dry_run})
        return {"plan": {"actions": []}, "run": None}

    monkeypatch.setattr(first_run, "plan_and_maybe_apply", _spy)
    result = first_run.run(_discover(), _snapshot(), confirm=False, saved_order=True)
    assert result["dry_run"] is True
    assert result["applied"] is None
    assert result["completed"] is False
    # every call made was a dry run
    assert applied_calls, "expected the plan to be built"
    assert all(call["dry_run"] for call in applied_calls), applied_calls


def test_run_with_confirm_applies_and_completes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(first_run, "STATE_FILE", tmp_path / "first_run.json")
    seen = []

    def _spy(discover, *, confirm=False, dry_run=True, only_safe=True):
        seen.append({"confirm": confirm, "dry_run": dry_run})
        return {"plan": {"actions": []}, "run": {"applied": ["pip:redis"]}}

    monkeypatch.setattr(first_run, "plan_and_maybe_apply", _spy)
    monkeypatch.setattr(first_run, "set_bootstrap_state", lambda patch: patch)
    result = first_run.run(_discover(), _snapshot(), confirm=True, saved_order=True)
    assert result["dry_run"] is False
    assert result["applied"]["run"]["applied"] == ["pip:redis"]
    assert result["completed"] is True
    assert first_run.is_complete() is True
    assert any(call["confirm"] and not call["dry_run"] for call in seen), seen


def test_reset_reopens_the_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(first_run, "STATE_FILE", tmp_path / "first_run.json")
    first_run.mark_complete()
    assert first_run.is_complete() is True
    first_run.reset()
    assert first_run.is_complete() is False
