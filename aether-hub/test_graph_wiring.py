#!/usr/bin/env python3
"""Multi-wire fan-in/fan-out + recursive feedback edges."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph import (  # noqa: E402
    edge_would_cycle,
    empty_graph,
    graph_to_pipeline,
    new_node,
    topo_order,
)


def test_fan_in_fan_out() -> None:
    g = empty_graph("fan-demo")
    goal = new_node("goal", 0, 0, {"text": "t"})
    master = new_node("master", 100, 0)
    w1 = new_node("worker", 200, 0)
    w2 = new_node("worker", 200, 80)
    review = new_node("analyser", 300, 40)
    out = new_node("output", 400, 40)
    for n in (goal, master, w1, w2, review, out):
        g["nodes"].append(n)
    # fan-out master→w1, master→w2; fan-in w1→review, w2→review
    g["edges"] = [
        {"id": "e1", "from": goal["id"], "to": master["id"], "kind": "data"},
        {"id": "e2", "from": master["id"], "to": w1["id"], "kind": "data"},
        {"id": "e3", "from": master["id"], "to": w2["id"], "kind": "data"},
        {"id": "e4", "from": w1["id"], "to": review["id"], "kind": "data"},
        {"id": "e5", "from": w2["id"], "to": review["id"], "kind": "data"},
        {"id": "e6", "from": review["id"], "to": out["id"], "kind": "data"},
    ]
    layout = topo_order(g)
    assert not layout["has_data_cycle"]
    assert set(layout["outgoing"][master["id"]]) == {w1["id"], w2["id"]}
    assert set(layout["incoming"][review["id"]]) == {w1["id"], w2["id"]}
    pipe = graph_to_pipeline(g)
    rev_stage = next(s for s in pipe["stages"] if s["id"] == review["id"])
    assert set(rev_stage["inputs_from"]) == {w1["id"], w2["id"]}
    m_stage = next(s for s in pipe["stages"] if s["id"] == master["id"])
    assert set(m_stage["outputs_to"]) == {w1["id"], w2["id"]}


def test_recursive_feedback() -> None:
    g = empty_graph("loop-demo")
    g["recursive"] = True
    g["max_iterations"] = 5
    goal = new_node("goal", 0, 0, {"text": "iterate"})
    master = new_node("master", 100, 0)
    worker = new_node("worker", 200, 0)
    out = new_node("output", 300, 0)
    for n in (goal, master, worker, out):
        g["nodes"].append(n)
    g["edges"] = [
        {"id": "e1", "from": goal["id"], "to": master["id"], "kind": "data"},
        {"id": "e2", "from": master["id"], "to": worker["id"], "kind": "data"},
        {"id": "e3", "from": worker["id"], "to": out["id"], "kind": "data"},
        # output feeds earlier master (recursive)
        {"id": "e4", "from": out["id"], "to": master["id"], "kind": "feedback"},
    ]
    assert edge_would_cycle(
        {"nodes": g["nodes"], "edges": g["edges"][:3]},
        out["id"],
        master["id"],
    )
    layout = topo_order(g)
    assert len(layout["feedback_edges"]) == 1
    assert layout["feedback_edges"][0]["to"] == master["id"]
    assert not layout["has_data_cycle"]
    pipe = graph_to_pipeline(g)
    assert pipe["recursive"] is True
    assert pipe["max_iterations"] == 5
    assert len(pipe["feedback_edges"]) == 1
    assert "recursive" in pipe["tags"]


def main() -> None:
    test_fan_in_fan_out()
    test_recursive_feedback()
    print("ok test_graph_wiring")


if __name__ == "__main__":
    main()
