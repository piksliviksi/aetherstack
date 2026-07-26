"""Minimal LiteLLM activity telemetry for the local AetherStack control UI.

Only model aliases and timing/state are recorded. Prompts, responses, headers,
API keys, users, and costs are deliberately excluded.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from litellm.integrations.custom_logger import CustomLogger


STATE_PATH = Path(os.environ.get("AETHER_INFERENCE_STATUS_PATH", "/aetherstack-state/inference-status.json"))
MAX_ACTIVE = 256
MAX_TEXT = 256
STALE_SECONDS = 2 * 60 * 60


class AetherStackActivityLogger(CustomLogger):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._active: dict[str, dict[str, Any]] = {}
        self._last: dict[str, Any] | None = None
        self._write_state()

    @staticmethod
    def _call_id(kwargs: dict[str, Any]) -> str:
        return str(kwargs.get("litellm_call_id") or kwargs.get("litellm_trace_id") or id(kwargs))[:MAX_TEXT]

    @staticmethod
    def _model_alias(model: str | None, kwargs: dict[str, Any]) -> str:
        params = kwargs.get("litellm_params") or {}
        metadata = params.get("metadata") or {}
        return str(metadata.get("model_group") or kwargs.get("model") or model or "unknown")[:MAX_TEXT]

    def _write_state(self) -> None:
        cutoff = time.time() - STALE_SECONDS
        self._active = {
            call_id: entry
            for call_id, entry in self._active.items()
            if float(entry.get("startedAt") or 0) >= cutoff
        }
        payload = {
            "updatedAt": time.time(),
            "active": list(self._active.values()),
            "activeCount": len(self._active),
            "last": self._last,
        }
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = STATE_PATH.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, STATE_PATH)
        except OSError:
            # Telemetry must never interrupt inference.
            pass

    def log_pre_api_call(self, model, messages, kwargs):
        del messages
        now = time.time()
        entry = {
            "callId": self._call_id(kwargs),
            "model": self._model_alias(model, kwargs),
            "startedAt": now,
        }
        with self._lock:
            if len(self._active) >= MAX_ACTIVE:
                oldest = min(self._active.values(), key=lambda value: value.get("startedAt") or 0)
                self._active.pop(str(oldest.get("callId")), None)
            self._active[entry["callId"]] = entry
            self._last = {**entry, "state": "running"}
            self._write_state()

    def _finish(self, kwargs: dict[str, Any], state: str) -> None:
        now = time.time()
        call_id = self._call_id(kwargs)
        with self._lock:
            started = self._active.pop(call_id, None)
            model = self._model_alias(None, kwargs)
            if started is None:
                # Some LiteLLM versions generate the proxy call id after the
                # pre-call hook. Match the oldest active call for this model.
                matching = [
                    entry
                    for entry in self._active.values()
                    if entry.get("model") == model
                ]
                if matching:
                    started = min(matching, key=lambda entry: entry.get("startedAt") or 0)
                    self._active.pop(str(started.get("callId")), None)
            self._last = {
                "callId": call_id,
                "model": (started or {}).get("model") or model,
                "startedAt": (started or {}).get("startedAt"),
                "finishedAt": now,
                "state": state,
            }
            self._write_state()

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        del response_obj, start_time, end_time
        self._finish(kwargs, "complete")

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        del response_obj, start_time, end_time
        self._finish(kwargs, "failed")


proxy_handler_instance = AetherStackActivityLogger()
