#!/usr/bin/env python3
"""GDPR mode: settings persistence, consent gating, export, and real erasure."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import gdpr  # noqa: E402
from memory import MemoryStore  # noqa: E402


def _mem() -> MemoryStore:
    return MemoryStore(url="redis://127.0.0.1:1/0")


@pytest.fixture(autouse=True)
def isolate_settings_and_consent(tmp_path, monkeypatch):
    monkeypatch.setattr(gdpr, "GDPR_SETTINGS_FILE", tmp_path / "gdpr_settings.json")
    gdpr._consented_sessions.clear()
    yield
    gdpr._consented_sessions.clear()


def test_defaults_are_disabled_with_a_sane_retention() -> None:
    settings = gdpr.get_settings()
    assert settings["enabled"] is False
    assert settings["retention_days"] == gdpr.DEFAULT_RETENTION_DAYS
    assert gdpr.is_enabled() is False


def test_set_settings_persists_and_round_trips() -> None:
    gdpr.set_settings({"enabled": True, "retention_days": 14, "require_cloud_consent": False})
    settings = gdpr.get_settings()
    assert settings["enabled"] is True
    assert settings["retention_days"] == 14
    assert settings["require_cloud_consent"] is False
    assert settings["updated_at"] is not None
    assert gdpr.retention_seconds() == 14 * 86400


def test_retention_days_is_bounded() -> None:
    with pytest.raises(ValueError, match="between"):
        gdpr.set_settings({"retention_days": 0})
    with pytest.raises(ValueError, match="between"):
        gdpr.set_settings({"retention_days": 999_999})


def test_retention_days_must_be_an_integer() -> None:
    with pytest.raises(ValueError, match="integer"):
        gdpr.set_settings({"retention_days": "soon"})


def test_a_partial_update_does_not_reset_other_settings() -> None:
    gdpr.set_settings({"enabled": True, "retention_days": 7})
    gdpr.set_settings({"require_cloud_consent": False})
    settings = gdpr.get_settings()
    assert settings["enabled"] is True
    assert settings["retention_days"] == 7
    assert settings["require_cloud_consent"] is False


def test_cloud_dispatch_allowed_by_default_when_gdpr_mode_is_off() -> None:
    assert gdpr.cloud_dispatch_allowed("any-session") is True


def test_cloud_dispatch_blocked_until_consent_when_gdpr_mode_is_on() -> None:
    gdpr.set_settings({"enabled": True, "require_cloud_consent": True})
    assert gdpr.cloud_dispatch_allowed("s1") is False
    gdpr.record_consent("s1")
    assert gdpr.cloud_dispatch_allowed("s1") is True
    assert gdpr.cloud_dispatch_allowed("s2") is False  # consent is per-session


def test_cloud_dispatch_allowed_when_gdpr_mode_on_but_consent_not_required() -> None:
    gdpr.set_settings({"enabled": True, "require_cloud_consent": False})
    assert gdpr.cloud_dispatch_allowed("s1") is True


def test_revoke_consent_removes_it() -> None:
    gdpr.set_settings({"enabled": True, "require_cloud_consent": True})
    gdpr.record_consent("s1")
    assert gdpr.has_consent("s1") is True
    gdpr.revoke_consent("s1")
    assert gdpr.has_consent("s1") is False


def test_subprocessors_lists_every_cloud_provider_litellm_config_routes_to() -> None:
    report = gdpr.subprocessors()
    names = {p["provider"] for p in report["cloud_providers"]}
    assert names == {"xAI", "OpenAI", "Anthropic", "Mistral AI", "Google"}
    assert "local" in report["local_note"].lower()


def test_export_user_data_includes_session_archive_and_tagged_vectors() -> None:
    mem = _mem()
    mem.append_message("s1", "user", "hello")
    mem.upsert_vector("archived transcript", namespace="archive:s1", meta={"session_id": "s1"})
    mem.upsert_vector("unrelated note", namespace="notes", meta={"session_id": "s1"})
    mem.upsert_vector("someone else's note", namespace="notes", meta={"session_id": "s2"})

    export = gdpr.export_user_data(mem, "s1")
    assert export["session"]["messages"][0]["content"] == "hello"
    assert export["archive"]["count"] == 1
    tagged_texts = {v["text"] for v in export["tagged_vectors"]}
    assert tagged_texts == {"unrelated note"}


def test_erase_user_data_removes_session_archive_and_tagged_vectors_only() -> None:
    mem = _mem()
    mem.append_message("s1", "user", "hello")
    mem.upsert_vector("archived transcript", namespace="archive:s1", meta={"session_id": "s1"})
    mem.upsert_vector("tagged note", namespace="notes", meta={"session_id": "s1"})
    mem.upsert_vector("someone else's note", namespace="notes", meta={"session_id": "s2"})

    removed = gdpr.erase_user_data(mem, "s1")
    assert removed["session"] is True
    assert removed["archive_namespace"] == "archive:s1"
    assert removed["tagged_vectors"] == 1

    assert mem.get_session("s1") == []
    assert mem.list_vectors("archive:s1") == []
    remaining_notes = {v["text"] for v in mem.list_vectors("notes")}
    assert remaining_notes == {"someone else's note"}


def test_erase_user_data_on_a_session_with_nothing_stored_is_a_safe_no_op() -> None:
    mem = _mem()
    removed = gdpr.erase_user_data(mem, "never-existed")
    assert removed["session"] is True
    assert removed["archive_namespace"] is None
    assert removed["tagged_vectors"] == 0


def test_export_and_erase_resolve_the_private_vault_storage_id(monkeypatch) -> None:
    # A private session is stored under a vault-prefixed id/namespace, not the
    # bare session_id (see privacy.private_session_key / private_archive_ns).
    # export/erase must resolve that first or they silently miss the data.
    monkeypatch.setattr(
        gdpr,
        "resolve_private_context",
        lambda session_id=None, **kw: {"private": True, "project_id": "proj-x"},
    )
    mem = _mem()
    store_sid = "private:proj-x:sess-1"
    archive_ns = "private:proj-x:archive:sess-1"
    mem.append_message(store_sid, "user", "sensitive private content")
    mem.upsert_vector("private archive", namespace=archive_ns, meta={"session_id": "sess-1"})
    # nothing under the bare id — export/erase must not need it to find the data
    assert mem.get_session("sess-1") == []

    export = gdpr.export_user_data(mem, "sess-1")
    assert export["session"]["messages"][0]["content"] == "sensitive private content"
    assert export["archive"]["count"] == 1

    removed = gdpr.erase_user_data(mem, "sess-1")
    assert removed["archive_namespace"] == archive_ns
    assert mem.get_session(store_sid) == []
    assert mem.list_vectors(archive_ns) == []


def test_session_lock_serializes_a_concurrent_archive_write_against_erase() -> None:
    import threading
    import time as time_mod

    mem = _mem()
    mem.append_message("s1", "user", "hello")
    order: list[str] = []
    archive_started = threading.Event()

    def slow_archive_write():
        with gdpr.session_lock("s1"):
            order.append("archive_start")
            archive_started.set()
            time_mod.sleep(0.05)
            mem.upsert_vector("archived after erase would have run", namespace="archive:s1", meta={"session_id": "s1"})
            order.append("archive_end")

    t = threading.Thread(target=slow_archive_write)
    t.start()
    archive_started.wait(timeout=1)
    # erase_user_data must block until the archive write releases the lock,
    # not run concurrently and see a namespace state mid-write.
    gdpr.erase_user_data(mem, "s1")
    order.append("erase_done")
    t.join(timeout=1)

    assert order == ["archive_start", "archive_end", "erase_done"]
    # the archive written *while holding the lock* is erased too, because
    # erase only started after the archive released it
    assert mem.list_vectors("archive:s1") == []


class _TruncatedNamespaceMemory:
    """A memory double whose "notes" namespace claims more real vectors than
    list_vectors() actually returns — simulates hitting MAX_VECTORS_SCAN."""

    def export_session(self, session_id):
        return {"session_id": session_id, "messages": []}

    def export_namespace(self, namespace):
        return {"namespace": namespace, "count": 0, "vectors": []}

    def list_vector_namespaces(self):
        return ["notes"]

    def list_vectors(self, namespace):
        return [{"id": "v1", "meta": {}, "text": "only one of many"}]

    def namespace_size(self, namespace):
        return 9999  # far more than list_vectors() returned

    def clear_session(self, session_id):
        pass

    def delete_namespace(self, namespace):
        return False

    def delete_vector(self, namespace, vector_id):
        return True


def test_export_flags_a_namespace_that_may_be_truncated() -> None:
    export = gdpr.export_user_data(_TruncatedNamespaceMemory(), "s1")
    assert export["possibly_incomplete"] is True
    assert export["truncated_namespaces"] == ["notes"]


def test_erase_flags_a_namespace_that_may_be_truncated() -> None:
    removed = gdpr.erase_user_data(_TruncatedNamespaceMemory(), "s1")
    assert removed["possibly_incomplete"] is True
    assert removed["truncated_namespaces"] == ["notes"]


def test_export_and_erase_do_not_flag_incomplete_when_nothing_is_truncated() -> None:
    mem = _mem()
    mem.upsert_vector("just one", namespace="notes", meta={"session_id": "s1"})
    export = gdpr.export_user_data(mem, "s1")
    assert export["possibly_incomplete"] is False
    assert "truncated_namespaces" not in export
