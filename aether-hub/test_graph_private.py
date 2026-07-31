#!/usr/bin/env python3
"""Private node + pass-through metadata on graph export."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph import (  # noqa: E402
    NODE_TYPES,
    PASS_THROUGH_TYPES,
    empty_graph,
    graph_to_pipeline,
    new_node,
)


def test_private_node_export() -> None:
    assert "private" in NODE_TYPES
    assert "memory" in PASS_THROUGH_TYPES
    assert "slash" in PASS_THROUGH_TYPES
    assert "output" in PASS_THROUGH_TYPES
    assert "private" not in PASS_THROUGH_TYPES

    g = empty_graph("priv-demo")
    goal = new_node("goal", 0, 0, {"text": "Review sealed docs"})
    priv = new_node(
        "private",
        100,
        0,
        {
            "input_folder": "D:/vault/corpus",
            "input_globs": ["*.pdf", "*.txt"],
            "model": "local-default",
        },
    )
    mem = new_node("memory", 200, 0, {"scope": "tree", "action": "store"})
    out = new_node("output", 300, 0)
    for n in (goal, priv, mem, out):
        g["nodes"].append(n)
    g["edges"] = [
        {"id": "e1", "from": goal["id"], "to": priv["id"], "kind": "data"},
        {"id": "e2", "from": priv["id"], "to": mem["id"], "kind": "data"},
        {"id": "e3", "from": mem["id"], "to": out["id"], "kind": "data"},
    ]
    pipe = graph_to_pipeline(g)
    assert len(pipe["stages"]) == 1
    st = pipe["stages"][0]
    assert st["role"] == "private_local"
    assert st["private"] is True
    assert st["gpu_only"] is True
    assert st["select"]["tier"] == "local"
    assert st["input_folder"] == "D:/vault/corpus"
    assert "*.pdf" in st["input_globs"]
    assert pipe["memory_ops"] and pipe["memory_ops"][0]["scope"] == "tree"


def main() -> None:
    test_private_node_export()
    print("ok test_graph_private")


if __name__ == "__main__":
    main()
