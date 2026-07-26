"""
Node graph model for visual pipeline scripting (VFX-style canvas).
Converts to/from aetherstack.pipeline.v1; auto-connect best practices.
"""
from __future__ import annotations

import copy
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import os

from pipelines import get_pipeline

SCHEMA = "aetherstack.graph.v1"
ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
GRAPH_DIR = Path(os.environ.get("AETHER_GRAPHS_DIR", str(REPO / "pipelines" / "graphs")))
GRAPH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _safe_graph_id(value: Any) -> str:
    gid = str(value or "").strip()
    if not GRAPH_ID_RE.fullmatch(gid):
        raise ValueError("graph id must be 1-128 letters, numbers, '-' or '_'")
    return gid

NODE_TYPES = {
    "goal": {"label": "Goal", "ports_in": 0, "ports_out": 1, "color": "#3b82f6"},
    "master": {"label": "Master", "ports_in": 1, "ports_out": 1, "color": "#a78bfa"},
    "worker": {"label": "Worker", "ports_in": 1, "ports_out": 1, "color": "#34d399"},
    "analyser": {"label": "Analyser", "ports_in": 1, "ports_out": 1, "color": "#fbbf24"},
    "tester": {"label": "Tester", "ports_in": 1, "ports_out": 1, "color": "#22d3ee"},
    "memory": {"label": "Memory", "ports_in": 1, "ports_out": 1, "color": "#fb7185"},
    "slash": {"label": "Slash", "ports_in": 1, "ports_out": 1, "color": "#94a3b8"},
    "output": {"label": "Output", "ports_in": 1, "ports_out": 0, "color": "#64748b"},
}

ROLE_MAP = {
    "master": "mastermind",
    "worker": "builder",
    "analyser": "critic",
    "tester": "tester",
}

_DEFAULT_DATA = {
    "goal": {"text": ""},
    "master": {
        "role": "mastermind",
        "instructions_md": "",
        "maker": None,
        "model": None,
        "tier": None,
        "max_cost": "high",
        "strategy": "best_score",
    },
    "worker": {
        "role": "builder",
        "instructions_md": "",
        "maker": None,
        "model": None,
        "tier": "local",
        "max_cost": "medium",
        "strategy": "cheapest",
        "parallel": 2,
    },
    "analyser": {
        "role": "critic",
        "instructions_md": "",
        "maker": None,
        "model": None,
        "tier": None,
        "max_cost": "high",
        "strategy": "best_score",
        "gate": True,
        "ack": True,
    },
    "tester": {
        "role": "tester",
        "instructions_md": "",
        "maker": None,
        "model": None,
        "tier": "local",
        "max_cost": "low",
        "strategy": "cheapest",
    },
    "memory": {"namespace": "default", "action": "search"},
    "slash": {"commands": ["/done all", "/compact"]},
    "output": {},
}


def node_types() -> dict[str, Any]:
    return {
        k: {**v, "defaults": copy.deepcopy(_DEFAULT_DATA.get(k, {}))}
        for k, v in NODE_TYPES.items()
    }


def new_node(ntype: str, x: float = 0, y: float = 0, data: dict | None = None) -> dict[str, Any]:
    if ntype not in NODE_TYPES:
        raise ValueError(f"unknown node type: {ntype}")
    d = copy.deepcopy(_DEFAULT_DATA.get(ntype, {}))
    if data:
        d.update(data)
    return {
        "id": f"n_{uuid.uuid4().hex[:8]}",
        "type": ntype,
        "x": x,
        "y": y,
        "data": d,
    }


def empty_graph(gid: str | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "id": gid or f"graph-{uuid.uuid4().hex[:8]}",
        "title": "Untitled graph",
        "nodes": [],
        "edges": [],
        "updated_at": time.time(),
    }


def best_practice_template(goal_text: str = "") -> dict[str, Any]:
    """Canonical master → analyser → worker → tester → slash layout."""
    g = empty_graph("best-practice")
    g["title"] = "Best practice: research → critique → build → test"
    nodes = [
        new_node("goal", 40, 160, {"text": goal_text or "Describe the goal…"}),
        new_node(
            "master",
            240,
            140,
            {
                "role": "mastermind",
                "maker": None,
                "model": None,
                "max_cost": "high",
                "strategy": "best_score",
            },
        ),
        new_node(
            "analyser",
            460,
            140,
            {
                "role": "critic",
                "maker": None,
                "model": None,
                "gate": True,
                "ack": True,
                "max_cost": "high",
            },
        ),
        new_node(
            "worker",
            680,
            120,
            {
                "role": "builder",
                "tier": "local",
                "strategy": "cheapest",
                "model": None,
                "parallel": 2,
                "max_cost": "medium",
            },
        ),
        new_node(
            "tester",
            900,
            140,
            {
                "role": "tester",
                "strategy": "cheapest",
                "tier": "local",
                "max_cost": "low",
            },
        ),
        new_node("slash", 1100, 140, {"commands": ["/done all", "/compact"]}),
        new_node("output", 1280, 160, {}),
    ]
    g["nodes"] = nodes
    g["edges"] = auto_connect(nodes)["edges"]
    return g


def service_to_graph(service: dict[str, Any], goal_text: str = "") -> dict[str, Any]:
    """Build the real editable lead -> parallel workers -> review -> synthesis service graph."""
    service_id = _safe_graph_id(f"service-{service.get('id') or 'preset'}")
    graph = empty_graph(service_id)
    graph["title"] = f"{service.get('label') or service.get('id')} service tree"
    graph["service_id"] = service.get("id")
    graph["token_saver"] = bool(service.get("token_saver"))
    graph["lean_mode"] = service.get("lean_mode")
    agents = list(service.get("agents") or [])
    lead = next((agent for agent in agents if agent.get("role") == "mastermind"), None)
    reviewer = next((agent for agent in agents if agent.get("role") == "supervisor"), None)
    workers = [agent for agent in agents if agent.get("role") == "worker"]
    center_y = max(70, 45 + max(0, len(workers) - 1) * 65)

    def agent_node(agent: dict[str, Any] | None, node_id: str, ntype: str, x: int, y: int, label: str) -> dict[str, Any]:
        agent = agent or {}
        return {
            "id": node_id,
            "type": ntype,
            "x": x,
            "y": y,
            "data": {
                "label": agent.get("label") or label,
                "role": agent.get("role") or label.lower(),
                "model": agent.get("model"),
                "provider": agent.get("provider"),
                "backend": agent.get("backend"),
                "tier": agent.get("tier"),
                "strategy": agent.get("strategy") or "best_score",
                "needs": list(agent.get("needs") or []),
                "available": bool(agent.get("available")),
                "service_id": service.get("id"),
            },
        }

    goal = new_node(
        "goal",
        30,
        center_y,
        {
            "label": "Task / goal",
            "text": goal_text or service.get("summary") or service.get("label") or "Describe the task",
            "service_id": service.get("id"),
        },
    )
    goal["id"] = f"{service_id}-goal"
    lead_node = agent_node(lead, f"{service_id}-lead", "master", 180, center_y, "Lead")
    worker_nodes = [
        agent_node(agent, f"{service_id}-worker-{index + 1}", "worker", 370, 45 + index * 130, f"Worker {index + 1}")
        for index, agent in enumerate(workers)
    ]
    reviewer_node = agent_node(reviewer, f"{service_id}-review", "analyser", 570, center_y, "Review")
    synthesis_node = agent_node(lead, f"{service_id}-synthesis", "master", 760, center_y, "Final synthesis")
    synthesis_node["data"]["label"] = "Final synthesis"
    synthesis_node["data"]["role"] = "synthesizer"
    output = new_node("output", 930, center_y, {"label": "Final answer", "service_id": service.get("id")})
    output["id"] = f"{service_id}-output"

    if not worker_nodes:
        worker_nodes = [agent_node(None, f"{service_id}-worker-1", "worker", 370, center_y, "Unresolved worker")]
    nodes = [goal, lead_node, *worker_nodes, reviewer_node, synthesis_node, output]
    edges = []

    def connect(source: dict[str, Any], target: dict[str, Any]) -> None:
        edges.append({"id": f"e-{source['id']}-{target['id']}", "from": source["id"], "to": target["id"], "kind": "data"})

    connect(goal, lead_node)
    for worker in worker_nodes:
        connect(lead_node, worker)
        connect(worker, reviewer_node)
    connect(reviewer_node, synthesis_node)
    connect(synthesis_node, output)
    graph["nodes"] = nodes
    graph["edges"] = edges
    graph["resolved_models"] = sorted({agent.get("model") for agent in agents if agent.get("model")})
    return graph


def auto_connect(nodes: list[dict[str, Any]] | None = None, graph: dict | None = None) -> dict[str, Any]:
    """
    Wire nodes using best practices when edges missing.
    Order: goal → master → analyser → worker → tester → slash → output
    Falls back to type order if multiple of same type (y-sort).
    """
    if graph:
        nodes = list(graph.get("nodes") or [])
    nodes = list(nodes or [])
    order = ["goal", "master", "analyser", "worker", "tester", "memory", "slash", "output"]
    buckets: dict[str, list] = {t: [] for t in order}
    for n in nodes:
        t = n.get("type")
        if t in buckets:
            buckets[t].append(n)
    for t in buckets:
        buckets[t].sort(key=lambda n: (n.get("y", 0), n.get("x", 0)))

    chain: list[dict] = []
    for t in order:
        chain.extend(buckets[t])

    edges = []
    for i in range(len(chain) - 1):
        a, b = chain[i], chain[i + 1]
        # skip invalid: output has no out, goal has no need from non-start
        if NODE_TYPES.get(a["type"], {}).get("ports_out", 1) == 0:
            continue
        if NODE_TYPES.get(b["type"], {}).get("ports_in", 1) == 0 and b["type"] != "output":
            pass
        edges.append(
            {
                "id": f"e_{uuid.uuid4().hex[:8]}",
                "from": a["id"],
                "to": b["id"],
                "kind": "data",
            }
        )

    # auto layout x positions
    x = 40
    for n in chain:
        n["x"] = x
        n["y"] = n.get("y") if n.get("y") is not None else 140
        x += 200

    practices = [
        "goal → master (orchestrate)",
        "master → analyser (critique / ack gate; prefer different maker)",
        "analyser → worker (build after ack)",
        "worker → tester (cheap/local)",
        "tester → slash (/done + /compact) → output",
    ]
    return {"nodes": chain if graph is None else nodes, "edges": edges, "practices": practices}


def graph_to_pipeline(graph: dict[str, Any]) -> dict[str, Any]:
    """Convert node graph to aetherstack.pipeline.v1 linear stages (topo order)."""
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    edges = graph.get("edges") or []
    # topo from goal
    incoming: dict[str, list[str]] = {nid: [] for nid in nodes}
    outgoing: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in edges:
        if e.get("from") in nodes and e.get("to") in nodes:
            outgoing[e["from"]].append(e["to"])
            incoming[e["to"]].append(e["from"])

    starts = [nid for nid, inc in incoming.items() if not inc]
    if not starts:
        starts = list(nodes.keys())[:1]
    ordered: list[str] = []
    seen: set[str] = set()
    stack = list(starts)
    while stack:
        nid = stack.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        ordered.append(nid)
        for nxt in outgoing.get(nid, []):
            if all(p in seen for p in incoming.get(nxt, [])):
                stack.append(nxt)
            elif nxt not in stack:
                stack.append(nxt)

    stages = []
    slash_cmds = ["/done all", "/compact"]
    goal_text = ""
    for nid in ordered:
        n = nodes[nid]
        t = n.get("type")
        d = n.get("data") or {}
        if t == "goal":
            goal_text = d.get("text") or ""
            continue
        if t == "slash":
            slash_cmds = d.get("commands") or slash_cmds
            continue
        if t in ("output", "memory"):
            continue
        role = d.get("role") or ROLE_MAP.get(t, t)
        stage = {
            "id": n.get("id"),
            "label": NODE_TYPES.get(t, {}).get("label", t),
            "role": role,
            "purpose": d.get("purpose") or f"{t} node",
            "select": {
                k: d[k]
                for k in ("strategy", "max_cost", "tier", "maker", "model")
                if d.get(k) is not None
            },
            "prefer_models": [d["model"]] if d.get("model") else [],
            "prefer_makers": [d["maker"]] if d.get("maker") else [],
            "needs": d.get("needs")
            or (
                ["reason", "chat"]
                if t in ("master", "analyser")
                else ["code", "chat"]
                if t == "worker"
                else ["cheap", "fast"]
            ),
            "ack": bool(d.get("ack")),
            "gate": bool(d.get("gate")),
            "parallel": int(d.get("parallel") or 1),
            "behavior_markdown": str(d.get("instructions_md") or "")[:100_000],
            "behavior_source": str(d.get("instructions_source") or "")[:500],
        }
        # clean empty select keys
        stage["select"] = {k: v for k, v in stage["select"].items() if v not in (None, "")}
        stages.append(stage)

    return {
        "schema": "aetherstack.pipeline.v1",
        "id": graph.get("id") or f"from-graph-{uuid.uuid4().hex[:6]}",
        "title": graph.get("title") or "From node graph",
        "description": f"Converted from graph; goal={goal_text[:120]}",
        "tags": ["from-graph", "visual"],
        "hw_weight": graph.get("hw_weight") or "medium",
        "token_saver": bool(graph.get("token_saver", False)),
        "mode": "multi_agent",
        "stages": stages,
        "on_complete": {"slash": slash_cmds, "archive": True},
        "goal_default": goal_text,
    }


def pipeline_to_graph(pipeline_id: str | None = None, pipeline: dict | None = None) -> dict[str, Any]:
    p = pipeline or (get_pipeline(pipeline_id) if pipeline_id else None)
    if not p:
        raise ValueError("pipeline not found")
    g = empty_graph(f"g-{p.get('id')}")
    g["title"] = p.get("title") or p.get("id")
    g["token_saver"] = p.get("token_saver")
    g["hw_weight"] = p.get("hw_weight")
    nodes = [new_node("goal", 40, 160, {"text": p.get("description") or p.get("title") or ""})]
    type_for_role = {
        "researcher": "master",
        "mastermind": "master",
        "critic": "analyser",
        "supervisor": "analyser",
        "builder": "worker",
        "worker": "worker",
        "tester": "tester",
    }
    x = 240
    for st in p.get("stages") or []:
        role = st.get("role") or "worker"
        ntype = type_for_role.get(role, "worker")
        sel = st.get("select") or {}
        prefer = (st.get("prefer_models") or [None])[0]
        maker = (st.get("prefer_makers") or [None])[0] or sel.get("maker")
        data = {
            "role": role,
            "model": prefer or sel.get("model"),
            "maker": maker,
            "tier": sel.get("tier"),
            "max_cost": sel.get("max_cost"),
            "strategy": sel.get("strategy") or "best_score",
            "gate": st.get("gate"),
            "ack": st.get("ack"),
            "parallel": st.get("parallel") or 1,
            "purpose": st.get("purpose"),
            "needs": st.get("needs"),
            "instructions_md": st.get("behavior_markdown") or "",
            "instructions_source": st.get("behavior_source") or "",
        }
        nodes.append(new_node(ntype, x, 140, data))
        x += 200
    oc = p.get("on_complete") or {}
    nodes.append(new_node("slash", x, 140, {"commands": oc.get("slash") or ["/done all", "/compact"]}))
    nodes.append(new_node("output", x + 200, 160, {}))
    g["nodes"] = nodes
    g["edges"] = auto_connect(nodes)["edges"]
    return g


def save_graph(graph: dict[str, Any]) -> dict[str, Any]:
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    gid = _safe_graph_id(graph.get("id") or f"graph-{uuid.uuid4().hex[:8]}")
    graph["id"] = gid
    graph["schema"] = SCHEMA
    graph["updated_at"] = time.time()
    fp = GRAPH_DIR / f"{gid}.aether-graph.json"
    fp.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    graph["_file"] = str(fp)
    return graph


def load_graph(gid: str) -> dict[str, Any] | None:
    gid = _safe_graph_id(gid)
    fp = GRAPH_DIR / f"{gid}.aether-graph.json"
    if not fp.is_file():
        # search
        for f in GRAPH_DIR.glob("*.aether-graph.json") if GRAPH_DIR.is_dir() else []:
            try:
                g = json.loads(f.read_text(encoding="utf-8"))
                if g.get("id") == gid:
                    return g
            except Exception:
                continue
        return None
    return json.loads(fp.read_text(encoding="utf-8"))


def list_graphs() -> list[dict[str, Any]]:
    out = []
    if not GRAPH_DIR.is_dir():
        return out
    for f in sorted(GRAPH_DIR.glob("*.aether-graph.json")):
        try:
            g = json.loads(f.read_text(encoding="utf-8"))
            out.append(
                {
                    "id": g.get("id"),
                    "title": g.get("title"),
                    "nodes": len(g.get("nodes") or []),
                    "edges": len(g.get("edges") or []),
                    "updated_at": g.get("updated_at"),
                    "_file": str(f),
                }
            )
        except Exception:
            continue
    return out


def plan_graph(graph: dict[str, Any], snapshot: dict[str, Any], goal: str = "") -> dict[str, Any]:
    pipe = graph_to_pipeline(graph)
    if goal:
        pipe["goal_default"] = goal
    # reuse pipeline planner by injecting into temp id path — call stages via plan_pipeline logic
    # plan_pipeline needs registered pipeline — use inline stages from pipe
    from pipelines import _pick_for_stage  # local import

    stages_out = []
    for stage in pipe.get("stages") or []:
        stages_out.append(_pick_for_stage(snapshot, stage))
    return {
        "graph_id": graph.get("id"),
        "pipeline": pipe,
        "stages_resolved": stages_out,
        "flow": " → ".join(
            f"{s.get('label') or s.get('stage_id')}({s.get('model')})" for s in stages_out
        ),
        "on_complete": pipe.get("on_complete"),
    }
