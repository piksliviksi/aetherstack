#!/usr/bin/env python3
"""Memory deletion/TTL primitives that GDPR erasure and retention rely on."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from memory import MemoryStore  # noqa: E402


def _mem() -> MemoryStore:
    # No REDIS_URL / unreachable Redis in the test sandbox -> falls back to
    # the in-process local store, which is exactly what we want to exercise
    # here (same code paths memory.py uses for both backends).
    return MemoryStore(url="redis://127.0.0.1:1/0")


def test_delete_vector_removes_only_the_named_one() -> None:
    mem = _mem()
    a = mem.upsert_vector("keep me", namespace="ns1")
    b = mem.upsert_vector("delete me", namespace="ns1")
    assert mem.delete_vector("ns1", b["id"]) is True
    remaining = [v["id"] for v in mem.list_vectors("ns1")]
    assert remaining == [a["id"]]


def test_delete_vector_on_missing_id_returns_false() -> None:
    mem = _mem()
    mem.upsert_vector("x", namespace="ns1")
    assert mem.delete_vector("ns1", "does-not-exist") is False


def test_delete_namespace_removes_everything_in_it() -> None:
    mem = _mem()
    mem.upsert_vector("a", namespace="archive:s1")
    mem.upsert_vector("b", namespace="archive:s1")
    assert mem.delete_namespace("archive:s1") is True
    assert mem.list_vectors("archive:s1") == []


def test_delete_namespace_on_nonexistent_namespace_returns_false() -> None:
    mem = _mem()
    assert mem.delete_namespace("never-existed") is False


def test_expired_vector_is_filtered_out_and_lazily_removed() -> None:
    mem = _mem()
    mem.upsert_vector("stale", namespace="ns1", ttl_seconds=-1)  # already expired
    fresh = mem.upsert_vector("fresh", namespace="ns1", ttl_seconds=3600)
    hits = mem.list_vectors("ns1")
    assert [v["id"] for v in hits] == [fresh["id"]]


def test_vector_without_ttl_never_expires() -> None:
    mem = _mem()
    v = mem.upsert_vector("forever", namespace="ns1")
    assert mem.list_vectors("ns1")[0]["id"] == v["id"]
    assert "expires_at" not in mem.list_vectors("ns1")[0]


def test_expiry_is_exercised_through_search_too() -> None:
    mem = _mem()
    mem.upsert_vector("old and gone", namespace="ns1", ttl_seconds=-1)
    result = mem.search("gone", namespace="ns1")
    assert result["hits"] == []
