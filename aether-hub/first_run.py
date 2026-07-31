#!/usr/bin/env python3
"""
First-run setup: scan the machine, finish the install, pick the fallback order.

This module owns no install logic of its own. It sequences the pieces that
already exist — discover, bootstrap, the host-CLI bridge, and the Auto chain —
into the one flow a new user should meet on first launch, and remembers that
the flow has been completed.

Consent rule: the scan and the plan are always safe and run unprompted. Nothing
is installed until the caller passes ``confirm=True``. "Automatic setup" means
the user answers once and the rest happens, not that software appears silently.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from bootstrap import get_bootstrap_state, plan_and_maybe_apply, set_bootstrap_state

ROOT = Path(__file__).resolve().parent
STATE_FILE = Path(
    os.environ.get("AETHER_FIRST_RUN_STATE", str(ROOT / "data" / "first_run.json"))
)

STEP_IDS = ("scan", "install", "connect", "order")


def _read_state() -> dict[str, Any]:
    try:
        if STATE_FILE.is_file():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _write_state(patch: dict[str, Any]) -> dict[str, Any]:
    state = {**_read_state(), **patch, "updated_at": time.time()}
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return state


def is_complete() -> bool:
    return bool(_read_state().get("completed_at"))


def mark_complete() -> dict[str, Any]:
    return _write_state({"completed_at": time.time()})


def reset() -> dict[str, Any]:
    """Forget that setup ran, so the flow is offered again."""
    return _write_state({"completed_at": None})


def _hardware(discover: dict[str, Any]) -> dict[str, Any]:
    gpu = discover.get("gpu_hints") or {}
    runtime = discover.get("runtime") or {}
    ollama = discover.get("ollama") or {}
    return {
        "platform": runtime.get("platform") or runtime.get("os"),
        "gpu": gpu.get("vendor") or gpu.get("detected") or "unknown",
        "gpu_detail": gpu,
        "docker": bool(runtime.get("docker") or runtime.get("docker_ok")),
        "ollama_reachable": bool(ollama.get("any_reachable")),
        "local_models": list(ollama.get("all_model_names") or []),
    }


def status(
    discover: dict[str, Any],
    snapshot: dict[str, Any],
    auto_order: list[str] | None = None,
    saved_order: bool = False,
) -> dict[str, Any]:
    """Per-step state of first-run setup. Pure: runs nothing, installs nothing."""
    discover = discover or {}
    summary = discover.get("summary") or {}
    models = (snapshot or {}).get("models") or {}
    available = [alias for alias, meta in models.items() if (meta or {}).get("available")]
    host_cli = [
        alias
        for alias in available
        if (models.get(alias) or {}).get("executor") == "host_cli"
    ]
    local = [alias for alias in available if (models.get(alias) or {}).get("tier") == "local"]

    # build_install_plan only emits actions for pieces that are actually
    # missing, so every action in the plan is still outstanding.
    plan = plan_and_maybe_apply(discover, confirm=False, dry_run=True)
    pending = list((plan.get("plan") or {}).get("actions") or [])

    steps = [
        {
            "id": "scan",
            "label": "Scan this machine",
            "done": bool(discover.get("ts")),
            "detail": _hardware(discover),
        },
        {
            "id": "install",
            "label": "Install what is missing",
            "done": not pending,
            "pending_actions": pending,
            "enabled": bool(get_bootstrap_state().get("enabled")),
        },
        {
            "id": "connect",
            "label": "Connect the models you already pay for",
            "done": bool(available),
            "host_cli": host_cli,
            "local": local,
            "cloud_keys": bool(summary.get("cloud_keys")),
        },
        {
            "id": "order",
            "label": "Choose the fallback order",
            "done": bool(saved_order),
            "order": list(auto_order or []),
        },
    ]
    nxt = next((step["id"] for step in steps if not step["done"]), None)
    return {
        "completed": is_complete(),
        "completed_at": _read_state().get("completed_at"),
        "next_step": nxt,
        "steps": steps,
        "ready": bool(available),
    }


def run(
    discover: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    confirm: bool = False,
    only_safe: bool = True,
    auto_order: list[str] | None = None,
    saved_order: bool = False,
) -> dict[str, Any]:
    """
    Execute setup. Without ``confirm`` this is a dry run that only reports the
    plan — no package, image, or model is fetched.
    """
    applied = None
    if confirm:
        # The user said yes; turn the installer on for this run.
        set_bootstrap_state({"enabled": True})
        applied = plan_and_maybe_apply(
            discover, confirm=True, dry_run=False, only_safe=only_safe
        )
    result = status(discover, snapshot, auto_order=auto_order, saved_order=saved_order)
    result["applied"] = applied
    result["dry_run"] = not confirm
    if confirm and result["ready"]:
        mark_complete()
        result["completed"] = True
    return result
