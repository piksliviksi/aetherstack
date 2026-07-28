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
