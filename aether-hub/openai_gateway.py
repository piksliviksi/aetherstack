"""OpenAI-compatible facade over AetherStack's live capability matrix."""
from __future__ import annotations

import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable

from services import _chat_completion

LITELLM_BASE_URL = os.environ.get("LITELLM_INTERNAL_URL", "http://litellm:4000").rstrip("/")
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
TOOL_FIELDS = ("tools", "tool_choice", "parallel_tool_calls", "functions", "function_call")


class GatewayError(RuntimeError):
    def __init__(self, message: str, status: int = 400, error_type: str = "invalid_request_error"):
        super().__init__(message)
        self.status = status
        self.error_type = error_type


def authorized(value: str | None, key: str | None = None) -> bool:
    secret = key if key is not None else MASTER_KEY
    if not secret:
        return False
    expected = f"Bearer {secret}"
    return hmac.compare_digest(str(value or ""), expected)


def model_list(snapshot: dict[str, Any]) -> dict[str, Any]:
    created = int(float(snapshot.get("ts") or time.time()))
    data = []
    for alias, raw in sorted((snapshot.get("models") or {}).items()):
        meta = dict(raw or {})
        if not meta.get("available") or "chat" not in (meta.get("capabilities") or []):
            continue
        capabilities = list(meta.get("capabilities") or [])
        data.append(
            {
                "id": alias,
                "object": "model",
                "created": created,
                "owned_by": f"aetherstack/{meta.get('provider') or 'dynamic'}",
                "name": alias,
                "aetherstack": {
                    "provider": meta.get("provider"),
                    "backend": meta.get("backend"),
                    "tier": meta.get("tier"),
                    "capabilities": capabilities,
                    "supports_tools": "tools" in capabilities,
                    "availability_reason": meta.get("availability_reason"),
                },
            }
        )
    return {"object": "list", "data": data}


def sanitize_request(payload: dict[str, Any], snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    request = dict(payload or {})
    model = str(request.get("model") or "").strip()
    if not model:
        raise GatewayError("model is required")
    meta = (snapshot.get("models") or {}).get(model)
    if not isinstance(meta, dict) or not meta.get("available"):
        raise GatewayError(f"model {model!r} is not currently available", 404, "model_not_found")
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise GatewayError("messages must be a non-empty array")

    removed_tools = False
    if "tools" not in (meta.get("capabilities") or []):
        for field in TOOL_FIELDS:
            if request.pop(field, None) is not None:
                removed_tools = True
    request["stream"] = False
    request.pop("stream_options", None)
    request["model"] = model
    request["messages"] = messages
    if removed_tools:
        request["messages"] = [
            {
                "role": "system",
                "content": "This model does not support tool calls. Answer directly without invoking tools.",
            },
            *messages,
        ]
    return request, meta


def _proxy_litellm(payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{LITELLM_BASE_URL}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {MASTER_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error")
            if isinstance(detail, dict):
                detail = detail.get("message")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = None
        raise GatewayError(str(detail or f"model backend returned HTTP {exc.code}"), exc.code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GatewayError(f"model backend is unreachable: {exc.reason if hasattr(exc, 'reason') else exc}", 502, "backend_error") from exc
    if not isinstance(value, dict):
        raise GatewayError("model backend returned an invalid response", 502, "backend_error")
    return value


def chat_completion(
    payload: dict[str, Any],
    snapshot: dict[str, Any],
    proxy: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    cli_completion: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    wants_stream = bool(payload.get("stream"))
    request, meta = sanitize_request(payload, snapshot)
    if meta.get("executor") == "host_cli":
        result = (cli_completion or _chat_completion)(request)
        now = int(time.time())
        value = {
            "id": f"chatcmpl-aether-{uuid.uuid4().hex[:16]}",
            "object": "chat.completion",
            "created": now,
            "model": result.get("model") or request["model"],
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": result.get("content") or ""}, "finish_reason": "stop"}
            ],
            "usage": result.get("usage") or {},
        }
    else:
        value = (proxy or _proxy_litellm)(request)
    return value, wants_stream


def stream_bytes(completion: dict[str, Any]) -> bytes:
    choice = ((completion.get("choices") or [{}])[0])
    content = (choice.get("message") or {}).get("content") or ""
    chunk = {
        "id": completion.get("id") or f"chatcmpl-aether-{uuid.uuid4().hex[:16]}",
        "object": "chat.completion.chunk",
        "created": completion.get("created") or int(time.time()),
        "model": completion.get("model"),
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
    return (f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n").encode("utf-8")


def error_body(error: GatewayError) -> dict[str, Any]:
    return {"error": {"message": str(error), "type": error.error_type, "code": error.error_type}}
