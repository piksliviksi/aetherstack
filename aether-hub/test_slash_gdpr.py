#!/usr/bin/env python3
"""/clear under GDPR mode: erase instead of archive-then-clear."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import gdpr  # noqa: E402
from memory import MemoryStore  # noqa: E402
from slash_commands import cmd_clear, cmd_save  # noqa: E402


def _mem() -> MemoryStore:
    return MemoryStore(url="redis://127.0.0.1:1/0")


@pytest.fixture(autouse=True)
def isolate_gdpr_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(gdpr, "GDPR_SETTINGS_FILE", tmp_path / "gdpr_settings.json")
    yield


def test_clear_archives_as_before_when_gdpr_mode_is_off() -> None:
    mem = _mem()
    mem.append_message("s1", "user", "hello")
    result = cmd_clear("s1", mem)
    assert result["ok"] is True
    assert result["archived"]["archive_id"] is not None
    assert mem.list_vectors("archive:s1"), "normal mode should still archive"


def test_clear_erases_instead_of_archiving_when_gdpr_mode_is_on() -> None:
    gdpr.set_settings({"enabled": True})
    mem = _mem()
    mem.append_message("s1", "user", "sensitive prompt content")
    result = cmd_clear("s1", mem)
    assert result["ok"] is True
    assert result["archived"]["erased"] is True
    assert result["archived"]["archive_id"] is None
    assert mem.list_vectors("archive:s1") == [], "GDPR mode must not create a permanent archive"
    # only the system continuity note remains, not the erased user content
    remaining = mem.get_session("s1")
    assert all(m["role"] == "system" for m in remaining)
    assert not any("sensitive prompt content" in m["content"] for m in remaining)


def test_save_still_archives_under_gdpr_mode_since_the_user_asked_to_keep_it() -> None:
    gdpr.set_settings({"enabled": True})
    mem = _mem()
    mem.append_message("s1", "user", "keep this")
    result = cmd_clear("s1", mem, keep_summary=True)
    assert result["command"] == "/compact"
    assert result["archived"].get("erased") is not True
    assert mem.list_vectors("archive:s1"), "/compact (keep_summary) is an explicit keep request"


def test_gdpr_mode_archives_get_an_expiring_ttl_not_indefinite_storage() -> None:
    gdpr.set_settings({"enabled": True, "retention_days": 30})
    mem = _mem()
    mem.append_message("s1", "user", "keep this")
    cmd_clear("s1", mem, keep_summary=True)
    vectors = mem.list_vectors("archive:s1")
    assert vectors and vectors[0].get("expires_at") is not None


def test_normal_mode_archives_never_expire() -> None:
    mem = _mem()
    mem.append_message("s1", "user", "keep this")
    cmd_clear("s1", mem)
    vectors = mem.list_vectors("archive:s1")
    assert vectors and "expires_at" not in vectors[0]
