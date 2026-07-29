"""Privacy-minimal in-process activity tracking for Hub-owned inference.

LiteLLM writes its own status file through ``aetherstack_callback.py``.  Host
CLI calls bypass LiteLLM, so the Hub tracks those calls here and the HTTP status
endpoint merges both sources.  Prompts, responses, headers, users, keys, and
costs are never accepted by this module.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any


_LOCK = threading.Lock()
_ACTIVE: dict[str, dict[str, Any]] = {}
_LAST: dict[str, Any] | None = None
_MAX_ACTIVE = 256
_MAX_TEXT = 256


def begin(model: str, source: str = "host_cli") -> str:
    """Register one running call and return its opaque correlation id."""
    global _LAST
    call_id = f"{source}-{uuid.uuid4().hex}"[:_MAX_TEXT]
    entry = {
        "callId": call_id,
        "model": str(model or "unknown")[:_MAX_TEXT],
        "source": str(source or "hub")[:32],
        "startedAt": time.time(),
    }
    with _LOCK:
        if len(_ACTIVE) >= _MAX_ACTIVE:
            oldest = min(_ACTIVE.values(), key=lambda item: item.get("startedAt") or 0)
            _ACTIVE.pop(str(oldest.get("callId")), None)
        _ACTIVE[call_id] = entry
        _LAST = {**entry, "state": "running"}
    return call_id


def finish(call_id: str, state: str) -> None:
    """Finish a call without recording its payload or result."""
    global _LAST
    with _LOCK:
        started = _ACTIVE.pop(str(call_id), None)
        if started is None:
            return
        _LAST = {
            **started,
            "finishedAt": time.time(),
            "state": str(state or "unknown")[:32],
        }


def snapshot() -> dict[str, Any]:
    """Return a detached status snapshot safe for the local operator UI."""
    with _LOCK:
        active = [dict(item) for item in _ACTIVE.values()]
        last = dict(_LAST) if _LAST is not None else None
    return {
        "active": active,
        "activeCount": len(active),
        "last": last,
        "updatedAt": time.time(),
    }


def reset_for_tests() -> None:
    global _LAST
    with _LOCK:
        _ACTIVE.clear()
        _LAST = None
