from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "aether-hub"))

from services import _augment_final_message_with_attachments, _select_vision_model

SNAPSHOT = {
    "models": {
        "gpt-4o": {"available": True, "executor": "litellm", "capabilities": ["chat", "vision"]},
        "claude-cli": {"available": True, "executor": "host_cli", "capabilities": ["chat", "vision"]},
        "local-tiny": {"available": True, "executor": "litellm", "capabilities": ["chat"]},
    }
}


def test_select_vision_model_excludes_host_cli():
    assert _select_vision_model(SNAPSHOT) == "gpt-4o"


def test_select_vision_model_returns_none_when_unavailable():
    snapshot = {"models": {"local-tiny": SNAPSHOT["models"]["local-tiny"]}}
    assert _select_vision_model(snapshot) is None


def test_augment_with_no_attachments_is_a_no_op():
    messages = [{"role": "user", "content": "hello"}]
    final_call = {"model": "local-tiny"}
    _augment_final_message_with_attachments(messages, [], SNAPSHOT, final_call)
    assert messages[-1]["content"] == "hello"
    assert final_call["model"] == "local-tiny"


def test_augment_with_pdf_inlines_text(monkeypatch):
    import services

    monkeypatch.setattr(services, "extract_pdf_text", lambda data: "extracted body")
    messages = [{"role": "user", "content": "goal text"}]
    final_call = {"model": "local-tiny"}
    encoded = base64.b64encode(b"%PDF-1.4 fake").decode("ascii")
    attachments = [{"type": "pdf", "name": "notes.pdf", "data": encoded}]
    _augment_final_message_with_attachments(messages, attachments, SNAPSHOT, final_call)
    assert "--- notes.pdf ---" in messages[-1]["content"]
    assert "extracted body" in messages[-1]["content"]


def test_augment_with_image_switches_to_vision_model():
    messages = [{"role": "user", "content": "goal text"}]
    final_call = {"model": "local-tiny"}
    encoded = base64.b64encode(b"\x89PNG...").decode("ascii")
    attachments = [{"type": "image", "name": "shot.png", "mime": "image/png", "data": encoded}]
    _augment_final_message_with_attachments(messages, attachments, SNAPSHOT, final_call)
    assert final_call["model"] == "gpt-4o"
    parts = messages[-1]["content"]
    assert parts[0] == {"type": "text", "text": "goal text"}
    assert parts[1]["type"] == "image_url"


def test_augment_with_image_and_no_vision_model_falls_back_to_text_note():
    snapshot = {"models": {"local-tiny": SNAPSHOT["models"]["local-tiny"]}}
    messages = [{"role": "user", "content": "goal text"}]
    final_call = {"model": "local-tiny"}
    encoded = base64.b64encode(b"\x89PNG...").decode("ascii")
    attachments = [{"type": "image", "name": "shot.png", "mime": "image/png", "data": encoded}]
    _augment_final_message_with_attachments(messages, attachments, snapshot, final_call)
    assert final_call["model"] == "local-tiny"
    assert "image omitted" in messages[-1]["content"]


def test_execute_service_wires_event_attachments_into_final_completion(monkeypatch):
    # End-to-end: goes through execute_service's own
    # `event.get("attachments")` extraction rather than calling
    # _augment_final_message_with_attachments directly, so a broken
    # extraction/call-site (wrong key, wrong filter, swapped args) fails this.
    import services
    from tests.test_services import snapshot as full_snapshot

    monkeypatch.setattr(services, "extract_pdf_text", lambda data: "extracted body")

    calls: list[tuple[str, list[dict] | None]] = []

    def completion(call: dict, messages: list[dict] | None = None) -> dict:
        calls.append((call["model"], messages))
        return {
            "model": call["model"],
            "content": f"response-{len(calls)}",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    encoded = base64.b64encode(b"%PDF-1.4 fake").decode("ascii")
    result = services.execute_service(
        "planning",
        full_snapshot(),
        {
            "goal": "describe this",
            "verify": False,
            "attachments": [{"type": "pdf", "name": "notes.pdf", "data": encoded}],
        },
        completion=completion,
    )
    assert result["ok"]
    final_messages = calls[-1][1]
    assert "--- notes.pdf ---" in final_messages[-1]["content"]
    assert "extracted body" in final_messages[-1]["content"]
