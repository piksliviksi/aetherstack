#!/usr/bin/env python3
"""Private mode isolation unit test."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["AETHER_HASH_EMBED"] = "1"
os.environ["AETHER_REDIS_CONNECT_TIMEOUT"] = "0.3"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
os.environ["AETHER_PRIVACY_STATE"] = str(Path(tempfile.mkdtemp()) / "privacy_state.json")

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reset privacy module state after env
import importlib
import privacy as privacy_mod

importlib.reload(privacy_mod)

from memory import MemoryStore
from privacy import (
    apply_privacy_patch,
    force_private_namespace,
    get_privacy_state,
    is_common_namespace,
    release_project,
    resolve_private_context,
    set_project_private,
)
from slash_commands import archive_to_memory, maybe_handle_message
from cross_memory import index_scan, scan_project_tree


def main() -> None:
    mem = MemoryStore()
    print("backend", mem.backend, flush=True)

    # Enable private project + bind session
    r = set_project_private(
        path="D:/code/secret-lab",
        private=True,
        session_id="sec-session",
        models=["local-default"],
    )
    assert r["private"] is True
    pid = r["project"]["id"]
    print("project_id", pid, flush=True)

    ctx = resolve_private_context(session_id="sec-session", model="local-default")
    assert ctx["private"] is True
    assert "session" in ctx["reasons"] or "model" in ctx["reasons"]

    # Common namespace blocked for private write remap
    ns = force_private_namespace("default", ctx)
    assert ns.startswith("private:"), ns
    assert is_common_namespace("conversation-index")
    assert not is_common_namespace(ns)

    # Messages go to vault only path via maybe_handle_message
    out = maybe_handle_message("secret research note about X", mem, session_id="sec-session")
    assert out.get("private") is True

    # Common pool default must stay empty
    common = mem.search("secret research", namespace="default", top_k=5)
    assert len(common.get("hits") or []) == 0, common

    # Vault has content
    vault_ns = force_private_namespace("session:sec-session", ctx)
    # message path uses private session key; archive uses vault
    arch = archive_to_memory("sec-session", mem, reason="test")
    assert arch.get("private") is True
    assert arch.get("common_pool") is False
    assert arch.get("index_id") is None  # no conversation-index sticky
    assert str(arch.get("namespace", "")).startswith("private:")

    idx = mem.search("secret", namespace="conversation-index", top_k=5)
    assert len(idx.get("hits") or []) == 0, "leak into conversation-index"

    # Cross-memory refuses private project path
    td = Path(tempfile.mkdtemp())
    # Mark this temp dir private by path registration
    set_project_private(path=str(td), private=True, session_id="other")
    (td / ".claude").mkdir()
    (td / ".claude" / "x.md").write_text("private code concept", encoding="utf-8")
    sc = scan_project_tree(td)
    assert sc.get("error") == "project_private" or sc.get("private") is True, sc
    ix = index_scan(mem, {"project_id": sc.get("project_id") or "x", "path": str(td), "chunks": [{"text": "x", "kind": "code"}]})
    assert ix.get("error") == "project_private" or ix.get("ok") is False, ix

    # Release
    rel = release_project(pid, purge_vault=True, mem=mem)
    assert rel.get("private") is False
    assert rel.get("merged_to_common") is False
    ctx2 = resolve_private_context(session_id="sec-session")
    # session unbound after release
    assert ctx2.get("private") is False, ctx2

    st = get_privacy_state()
    print("after_release private_projects", st["private_project_count"], flush=True)
    print("ALL_OK", flush=True)


if __name__ == "__main__":
    main()
