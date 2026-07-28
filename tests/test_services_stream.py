import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "aether-hub"))

from services import execute_service


class _FakeStreamResponse:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)


def test_execute_service_streams_final_answer_via_on_delta(monkeypatch):
    import services

    def fake_plan_service(service_id, snapshot, event):
        call = {"model": "local-tiny", "messages": [{"role": "system", "content": "lead"}], "task_id": "lead"}
        return {
            "service": {"agents": []},
            "litellm_calls": [{**call, "role": "mastermind"}],
            "lean_mode": "balanced",
            "token_saver": False,
        }

    monkeypatch.setattr(services, "plan_service", fake_plan_service)
    monkeypatch.setattr(services, "_activate_resolved_service", lambda *a, **k: {})

    def fake_completion(call, messages):
        return {"model": call.get("model"), "content": "lead output", "usage": {}}

    monkeypatch.setattr(services, "_chat_completion", fake_completion)

    def fake_stream(call, messages, on_delta):
        on_delta("Hello, ")
        on_delta("world.")
        return {"model": call.get("model"), "content": "Hello, world.", "usage": {"total_tokens": 5}}

    monkeypatch.setattr(services, "_chat_completion_stream", fake_stream)

    received = []
    snapshot = {"models": {"local-tiny": {"available": True, "executor": "litellm", "capabilities": ["chat"]}}}
    result = execute_service("demo", snapshot, {"goal": "hi"}, on_delta=received.append)

    assert received == ["Hello, ", "world."]
    assert result["answer"] == "Hello, world."


def test_execute_service_falls_back_to_blocking_for_host_cli_final_model(monkeypatch):
    import services

    def fake_plan_service(service_id, snapshot, event):
        call = {"model": "claude-cli", "messages": [{"role": "system", "content": "lead"}], "task_id": "lead"}
        return {
            "service": {"agents": []},
            "litellm_calls": [{**call, "role": "mastermind"}],
            "lean_mode": "balanced",
            "token_saver": False,
        }

    monkeypatch.setattr(services, "plan_service", fake_plan_service)
    monkeypatch.setattr(services, "_activate_resolved_service", lambda *a, **k: {})

    def fake_completion(call, messages):
        return {"model": call.get("model"), "content": "cli output", "usage": {}}

    monkeypatch.setattr(services, "_chat_completion", fake_completion)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("_chat_completion_stream must not be used for host_cli models")

    monkeypatch.setattr(services, "_chat_completion_stream", fail_if_called)

    received = []
    snapshot = {"models": {"claude-cli": {"available": True, "executor": "host_cli", "capabilities": ["chat"]}}}
    result = execute_service("demo", snapshot, {"goal": "hi"}, on_delta=received.append)

    assert received == ["cli output"]
    assert result["answer"] == "cli output"


def test_chat_completion_stream_parses_sse_lines_and_captures_trailing_usage(monkeypatch):
    """Exercises the real SSE parsing in _chat_completion_stream (line-by-line `data:`
    parsing, [DONE] handling, per-chunk json.loads) against a faked urlopen, plus the
    Fix 1 behavior: a stream_options.include_usage-style trailing chunk with empty
    `choices` and a `usage` field must be captured without being treated as content."""
    import services

    lines = [
        b'data: {"model": "local-tiny", "choices": [{"delta": {"content": "Hello, "}}]}\n',
        b'data: {"model": "local-tiny", "choices": [{"delta": {"content": "world."}}]}\n',
        b'data: {"choices": [], "usage": {"total_tokens": 42}}\n',
        b"data: [DONE]\n",
    ]
    captured_requests = []

    def fake_urlopen(request, timeout=None):
        captured_requests.append(request)
        return _FakeStreamResponse(lines)

    monkeypatch.setattr(services.urllib.request, "urlopen", fake_urlopen)

    received = []
    call = {"model": "local-tiny", "max_tokens": 500}
    result = services._chat_completion_stream(call, [{"role": "user", "content": "hi"}], received.append)

    assert received == ["Hello, ", "world."]
    assert result["content"] == "Hello, world."
    assert result["model"] == "local-tiny"
    assert result["usage"] == {"total_tokens": 42}

    sent_payload = json.loads(captured_requests[0].data.decode("utf-8"))
    assert sent_payload["stream_options"] == {"include_usage": True}
