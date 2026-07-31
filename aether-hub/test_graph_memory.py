#!/usr/bin/env python3
"""Unit tests for Memory-node three-tier scopes (tree / project / global)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph import (  # noqa: E402
    graph_to_pipeline,
    memory_op_from_node,
    new_node,
    resolve_memory_namespace,
)


def test_resolve_namespaces() -> None:
    assert resolve_memory_namespace(scope="tree", graph_id="auth-flow") == "tree:auth-flow"
    assert resolve_memory_namespace(scope="project", project_id="acme-app") == "project:acme-app"
    assert resolve_memory_namespace(scope="global") == "global"
    assert resolve_memory_namespace(scope="tree", namespace="custom-ns") == "custom-ns"
    assert resolve_memory_namespace(scope="weird", graph_id="g1") == "tree:g1"


def test_memory_op_and_pipeline_export() -> None:
    g = {
        "schema": "aetherstack.graph.v1",
        "id": "decision-oauth",
        "project_id": "proj-alpha",
        "nodes": [
            new_node("goal", 0, 0, {"text": "Ship OAuth"}),
            new_node("master", 100, 0),
            new_node("memory", 200, 0, {"scope": "tree", "action": "store"}),
            new_node(
                "memory",
                300,
                0,
                {"scope": "project", "action": "search", "label": "Project recall"},
            ),
            new_node("memory", 400, 0, {"scope": "global", "action": "search"}),
            new_node("slash", 500, 0),
            new_node("output", 600, 0),
        ],
        "edges": [],
    }
    # Wire linear for topo order
    ids = [n["id"] for n in g["nodes"]]
    g["edges"] = [
        {"id": f"e{i}", "from": ids[i], "to": ids[i + 1]} for i in range(len(ids) - 1)
    ]

    op = memory_op_from_node(g["nodes"][2], g)
    assert op["scope"] == "tree"
    assert op["action"] == "store"
    assert op["namespace"] == "tree:decision-oauth"

    pipe = graph_to_pipeline(g)
    assert "memory_ops" in pipe
    scopes = [m["scope"] for m in pipe["memory_ops"]]
    assert scopes == ["tree", "project", "global"]
    by_scope = {m["scope"]: m for m in pipe["memory_ops"]}
    assert by_scope["tree"]["namespace"] == "tree:decision-oauth"
    assert by_scope["project"]["namespace"] == "project:proj-alpha"
    assert by_scope["global"]["namespace"] == "global"
    # Memory nodes are not LLM stages
    assert all(s.get("role") != "memory" for s in pipe["stages"])


def main() -> None:
    test_resolve_namespaces()
    test_memory_op_and_pipeline_export()
    print("ok test_graph_memory")


if __name__ == "__main__":
    main()
