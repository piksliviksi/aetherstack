#!/usr/bin/env python3
"""A human-authorable YAML alternative to hand-building a preset in the canvas.

Where node_script.py scripts one node's if/then behavior, this scripts an
entire preset: the master, its workers/parallel branches, an audit
(reviewer) and tester, each with their own model/tier/prompt/script — then
converts that straight into the same node graph the canvas edits and
execute_graph runs. It sits alongside the existing aetherstack.pipeline.v1
JSON export, not instead of it: pipeline JSON stays the full-fidelity dump
of an arbitrary graph; this format only covers the well-known
goal -> master -> (workers/parallel, fanned out) -> audit -> tester -> output
shape, in exchange for being much shorter to hand-write.

    schema: aetherstack.preset-script.v1
    title: My Custom Preset
    goal: Default goal text for this preset
    master:
      model: claude-sonnet-4
      prompt: Plan the work and delegate to workers.
    workers:
      - label: Backend
        model: grok-code
        prompt: Implement the backend change.
    parallel:
      - label: Survey
        branches: 3
        prompt: Independently investigate the approach.
    audit:
      prompt: Check the work for correctness and regressions.
    tester:
      prompt: Run and verify the tests.
"""
from __future__ import annotations

from typing import Any

import yaml

from graph import empty_graph, new_node
from graph_exec import MAX_PARALLEL_BRANCHES

SCRIPT_SCHEMA = "aetherstack.preset-script.v1"
MAX_TEXT_CHARS = 20_000
MAX_BRANCH_NODES = 12


def _parse_positive_int(value: Any, field: str, *, default: int, minimum: int, maximum: int) -> int:
    """Coerces a script-supplied number, raising a clean PresetScriptError
    instead of letting a bare ValueError/TypeError escape to the caller —
    server.py only catches PresetScriptError for this endpoint, so anything
    else propagates as an unhandled exception and drops the connection with
    no response at all."""
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise PresetScriptError(f"{field!r} must be a whole number, got {value!r}")
    return max(minimum, min(maximum, parsed))


class PresetScriptError(ValueError):
    """A preset script is malformed."""


def _node_spec(entry: Any, index: int, default_label: str) -> dict[str, Any]:
    if entry is None:
        entry = {}
    if not isinstance(entry, dict):
        raise PresetScriptError(f"{default_label} #{index + 1} must be a mapping")
    return entry


def _agent_data(spec: dict[str, Any], role: str, default_max_cost: str, default_label: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "label": str(spec.get("label") or default_label)[:120],
        "role": role,
        "model": spec.get("model") or None,
        "instructions_md": str(spec.get("prompt") or spec.get("instructions_md") or "")[:100_000],
        "max_cost": spec.get("max_cost") or default_max_cost,
    }
    if spec.get("tier"):
        data["tier"] = str(spec["tier"])
    if spec.get("strategy"):
        data["strategy"] = str(spec["strategy"])
    if spec.get("script"):
        data["script"] = str(spec["script"])[:20_000]
    if spec.get("workspace_write"):
        data["workspace_write"] = bool(spec["workspace_write"])
    return data


def preset_script_to_graph(text: str, graph_id: str | None = None) -> dict[str, Any]:
    """Parse a preset script and build the real node graph it describes."""
    raw = str(text or "").strip()
    if not raw:
        raise PresetScriptError("preset script is empty")
    if len(raw) > MAX_TEXT_CHARS:
        raise PresetScriptError(f"preset script exceeds {MAX_TEXT_CHARS} characters")
    try:
        spec = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PresetScriptError(f"invalid preset script YAML: {exc}") from exc
    if not isinstance(spec, dict):
        raise PresetScriptError("preset script must be a YAML mapping")

    g = empty_graph(graph_id)
    g["title"] = str(spec.get("title") or "Scripted preset")[:200]

    goal_node = new_node("goal", 30, 200, {"text": str(spec.get("goal") or "Describe the goal…")[:20_000]})
    master_spec = spec.get("master") if isinstance(spec.get("master"), dict) else {}
    master_node = new_node("master", 240, 200, _agent_data(master_spec, "mastermind", "high", "Lead"))

    worker_specs = spec.get("workers") or []
    if not isinstance(worker_specs, list):
        raise PresetScriptError("'workers' must be a list")
    parallel_specs = spec.get("parallel") or []
    if not isinstance(parallel_specs, list):
        raise PresetScriptError("'parallel' must be a list")
    if len(worker_specs) + len(parallel_specs) > MAX_BRANCH_NODES:
        raise PresetScriptError(f"more than {MAX_BRANCH_NODES} workers/parallel branches combined")

    branch_nodes: list[dict[str, Any]] = []
    y = 60
    for index, entry in enumerate(worker_specs):
        entry = _node_spec(entry, index, "workers")
        node = new_node("worker", 470, y, _agent_data(entry, "builder", "medium", f"Worker {index + 1}"))
        if entry.get("parallel") is not None:
            node["data"]["parallel"] = _parse_positive_int(
                entry["parallel"], "workers[].parallel", default=1, minimum=1, maximum=MAX_PARALLEL_BRANCHES
            )
        branch_nodes.append(node)
        y += 120
    for index, entry in enumerate(parallel_specs):
        entry = _node_spec(entry, index, "parallel")
        data = _agent_data(entry, "builder", "medium", f"Parallel {index + 1}")
        # Clamped to what graph_exec.py will actually run (MAX_PARALLEL_BRANCHES) at
        # parse time, so what's saved/shown in the tree matches what executes —
        # previously an unclamped `branches: 40` silently ran as 8 at run time.
        data["parallel"] = _parse_positive_int(
            entry.get("branches"), "parallel[].branches", default=3, minimum=2, maximum=MAX_PARALLEL_BRANCHES
        )
        node = new_node("parallel", 470, y, data)
        branch_nodes.append(node)
        y += 120
    if not branch_nodes:
        # Every preset needs at least one place to do the work; a lone master
        # with no workers/parallel entries would otherwise be a dead end.
        branch_nodes.append(new_node("worker", 470, y, _agent_data({}, "builder", "medium", "Worker 1")))

    audit_spec = spec.get("audit")
    audit_node = None
    if audit_spec is not None:
        audit_node = new_node(
            "analyser", 700, 200, _agent_data(_node_spec(audit_spec, 0, "audit"), "critic", "high", "Audit")
        )
        audit_node["data"]["gate"] = True
        audit_node["data"]["ack"] = True

    tester_spec = spec.get("tester")
    tester_node = None
    if tester_spec is not None:
        tester_node = new_node(
            "tester", 900, 200, _agent_data(_node_spec(tester_spec, 0, "tester"), "tester", "low", "Tester")
        )

    memory_node = None
    memory_spec = spec.get("memory")
    if isinstance(memory_spec, dict):
        memory_node = new_node(
            "memory",
            240,
            340,
            {
                "label": memory_spec.get("label") or "Memory",
                "scope": memory_spec.get("scope") or "tree",
                "action": memory_spec.get("action") or "search",
            },
        )

    output_node = new_node("output", 1100, 200, {"label": "Final answer"})

    nodes = [goal_node, master_node, *branch_nodes]
    if memory_node:
        nodes.append(memory_node)
    if audit_node:
        nodes.append(audit_node)
    if tester_node:
        nodes.append(tester_node)
    nodes.append(output_node)

    edges: list[dict[str, Any]] = []

    def connect(source: dict[str, Any], target: dict[str, Any]) -> None:
        edges.append({"id": f"e_{len(edges)}_{source['id'][-4:]}", "from": source["id"], "to": target["id"], "kind": "data"})

    connect(goal_node, master_node)
    if memory_node:
        connect(goal_node, memory_node)
        connect(memory_node, master_node)
    # Fan-out: master -> every worker/parallel branch, run concurrently.
    fan_in_target = audit_node or tester_node or output_node
    for branch in branch_nodes:
        connect(master_node, branch)
        connect(branch, fan_in_target)
    if audit_node and tester_node:
        connect(audit_node, tester_node)
    last = tester_node or audit_node
    if last:
        connect(last, output_node)

    g["nodes"] = nodes
    g["edges"] = edges
    return g


def _node_to_agent_spec(node: dict[str, Any]) -> dict[str, Any]:
    d = node.get("data") or {}
    spec: dict[str, Any] = {}
    if d.get("label"):
        spec["label"] = d["label"]
    if d.get("model"):
        spec["model"] = d["model"]
    if d.get("tier"):
        spec["tier"] = d["tier"]
    if d.get("max_cost"):
        spec["max_cost"] = d["max_cost"]
    if d.get("strategy"):
        spec["strategy"] = d["strategy"]
    if d.get("instructions_md"):
        spec["prompt"] = d["instructions_md"]
    if d.get("script"):
        spec["script"] = d["script"]
    if d.get("workspace_write"):
        spec["workspace_write"] = True
    return spec


def graph_to_preset_script(graph: dict[str, Any]) -> str:
    """Best-effort export: only the well-known preset shape round-trips fully.

    Node types this format has no slot for (Private, Route, Slash, Memory
    beyond one node, custom wiring outside the fan-out/fan-in shape) are
    dropped — use "Export pipeline JSON" for a full-fidelity dump of an
    arbitrary graph instead.
    """
    nodes = graph.get("nodes") or []
    by_type: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        by_type.setdefault(node.get("type"), []).append(node)

    out: dict[str, Any] = {"schema": SCRIPT_SCHEMA, "title": graph.get("title") or "Scripted preset"}
    goal_nodes = by_type.get("goal") or []
    if goal_nodes:
        out["goal"] = (goal_nodes[0].get("data") or {}).get("text") or ""

    master_nodes = by_type.get("master") or []
    if master_nodes:
        out["master"] = _node_to_agent_spec(master_nodes[0])

    workers = []
    for n in sorted(by_type.get("worker") or [], key=lambda n: n.get("y", 0)):
        entry = _node_to_agent_spec(n)
        worker_parallel = int((n.get("data") or {}).get("parallel") or 1)
        if worker_parallel > 1:
            # Otherwise round-tripping a preset through export/import silently
            # drops fan-out: a worker with parallel > 1 imported fine (see
            # preset_script_to_graph), but exporting it back had no field for
            # this, so a re-import collapsed it to a single branch.
            entry["parallel"] = worker_parallel
        workers.append(entry)
    if workers:
        out["workers"] = workers

    parallels = []
    for n in sorted(by_type.get("parallel") or [], key=lambda n: n.get("y", 0)):
        entry = _node_to_agent_spec(n)
        entry["branches"] = int((n.get("data") or {}).get("parallel") or 3)
        parallels.append(entry)
    if parallels:
        out["parallel"] = parallels

    analyser_nodes = by_type.get("analyser") or []
    if analyser_nodes:
        out["audit"] = _node_to_agent_spec(analyser_nodes[0])

    tester_nodes = by_type.get("tester") or []
    if tester_nodes:
        out["tester"] = _node_to_agent_spec(tester_nodes[0])

    memory_nodes = by_type.get("memory") or []
    if memory_nodes:
        md = memory_nodes[0].get("data") or {}
        out["memory"] = {"scope": md.get("scope") or "tree", "action": md.get("action") or "search"}

    return yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=100)
