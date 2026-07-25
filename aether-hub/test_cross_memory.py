#!/usr/bin/env python3
"""Offline unit test for cross_memory (no docker required)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Fail Redis/embed network fast for unit tests
os.environ.setdefault("AETHER_REDIS_CONNECT_TIMEOUT", "0.4")
os.environ.setdefault("AETHER_REDIS_SOCKET_TIMEOUT", "0.4")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")  # closed port
os.environ["AETHER_HASH_EMBED"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from memory import MemoryStore  # noqa: E402
from cross_memory import (  # noqa: E402
    cross_search,
    index_scan,
    pull_context,
    scan_project_tree,
    set_xref_state,
)


def main() -> None:
    td = Path(tempfile.mkdtemp())
    (td / ".claude").mkdir()
    (td / ".claude" / "session.md").write_text(
        "We built OAuth middleware and tested it with pytest. Decision: use PKCE.",
        encoding="utf-8",
    )
    (td / ".aetherstack").mkdir()
    (td / ".aetherstack" / "notes.md").write_text(
        "Research: ROCm compute units for RX 6600 XT.",
        encoding="utf-8",
    )

    print("connecting memory…", flush=True)
    mem = MemoryStore()
    print("backend", mem.backend, flush=True)

    set_xref_state({"multi_project": True})
    sc = scan_project_tree(td)
    print("chunks", sc["chunk_count"], "sources", len(sc["sources"]), flush=True)
    assert sc["chunk_count"] >= 1, sc

    ix = index_scan(mem, sc)
    print("indexed", ix["indexed"], ix["kinds"], flush=True)
    assert ix["indexed"] >= 1

    r = cross_search(
        mem,
        "OAuth middleware tested",
        kinds=["code", "concept", "chat", "research", "test", "session"],
    )
    print("hits", len(r["hits"]), (r["hits"][0]["kind"] if r["hits"] else None), flush=True)
    assert r.get("ok"), r
    assert len(r["hits"]) >= 1, r

    p = pull_context(mem, "OAuth")
    print("pull", p.get("hit_count"), "block_len", len(p.get("prompt_block") or ""), flush=True)
    assert (p.get("hit_count") or 0) >= 1
    assert "Cross-project memory" in (p.get("prompt_block") or "")

    set_xref_state({"multi_project": False})
    r2 = cross_search(mem, "OAuth")
    assert r2.get("error") == "multi_project_off", r2
    print("gate_ok", flush=True)

    # Route symbols present without starting HTTP server
    import server as hub  # noqa: F401

    src = Path(hub.__file__).read_text(encoding="utf-8")
    for needle in (
        "/api/xref",
        "/api/xref/scan",
        "/api/xref/index",
        "/api/xref/search",
        "/api/xref/pull",
        "pull_context",
        "xref_pull",
    ):
        assert needle in src, f"missing {needle} in server.py"
    print("server_routes_ok", flush=True)
    print("ALL_OK", flush=True)


if __name__ == "__main__":
    main()
