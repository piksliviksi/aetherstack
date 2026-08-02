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

# ports_in / ports_out: 0 = none, -1 = unlimited fan-in/fan-out (multi-wire)
# pass_through: no LLM work — only routes/search/store (memory, slash, output)
NODE_TYPES = {
    "goal": {"label": "Goal", "ports_in": -1, "ports_out": -1, "color": "#3b82f6", "pass_through": False},
    "master": {"label": "Master", "ports_in": -1, "ports_out": -1, "color": "#a78bfa", "pass_through": False},
    "worker": {"label": "Worker", "ports_in": -1, "ports_out": -1, "color": "#34d399", "pass_through": False},
    "analyser": {"label": "Analyser", "ports_in": -1, "ports_out": -1, "color": "#fbbf24", "pass_through": False},
    "tester": {"label": "Tester", "ports_in": -1, "ports_out": -1, "color": "#22d3ee", "pass_through": False},
    "memory": {"label": "Memory", "ports_in": -1, "ports_out": -1, "color": "#fb7185", "pass_through": True},
    "route": {"label": "Model route", "ports_in": -1, "ports_out": -1, "color": "#e0a458", "pass_through": True},
    # Private: local-GPU-only inference over a folder of PDF/text; vault-isolated
    "private": {
        "label": "Private",
        "ports_in": -1,
        "ports_out": -1,
        "color": "#7c6f9e",
        "pass_through": False,
    },
    "slash": {"label": "Slash", "ports_in": -1, "ports_out": -1, "color": "#94a3b8", "pass_through": True},
    # Output accepts many results; out port used for recursive feedback into earlier nodes
    "output": {"label": "Output", "ports_in": -1, "ports_out": -1, "color": "#64748b", "pass_through": True},
}

EDGE_KINDS = ("data", "feedback")
DEFAULT_MAX_ITERATIONS = 3
PASS_THROUGH_TYPES = frozenset(
    t for t, meta in NODE_TYPES.items() if meta.get("pass_through")
)
DEFAULT_PRIVATE_GLOBS = ("*.pdf", "*.txt", "*.md", "*.markdown", "*.text")

ROLE_MAP = {
    "master": "mastermind",
    "worker": "builder",
    "analyser": "critic",
    "tester": "tester",
    "private": "private_local",
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
        "workspace_write": False,
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
        "workspace_write": False,
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
        "workspace_write": False,
    },
    "tester": {
        "role": "tester",
        "instructions_md": "",
        "maker": None,
        "model": None,
        "tier": "local",
        "max_cost": "low",
        "strategy": "cheapest",
        "workspace_write": False,
    },
    "memory": {
        # Three tiers: tree (this decision graph), project (all trees in project), global (pan-project)
        "scope": "tree",
        "action": "search",  # search | store
        "project_id": None,  # used when scope=project (else graph.project_id / service_id)
        "namespace": None,  # resolved at plan/export; optional override
    },
    "private": {
        "label": "Private local",
        "role": "private_local",
        # Forced local GPU inference — never cloud
        "tier": "local",
        "strategy": "local_first",
        "max_cost": "low",
        "model": "local-default",
        "provider": "ollama",
        "backend": "local",
        "gpu_only": True,
        "private_vault": True,
        # Corpus: folder of PDFs / text files on the host (or mounted path)
        "input_folder": "",
        "input_globs": list(DEFAULT_PRIVATE_GLOBS),
        "instructions_md": (
            "Work only on documents from the configured input folder. "
            "Do not send content to cloud providers. Prefer local GPU models."
        ),
    },
    "slash": {"commands": ["/done all", "/compact"]},
    "output": {},
    "route": {"model": None, "tier": None},
}

# Memory node scopes (tiers). Distinct from agent run-location `tier` (local/cloud/host_cli).
MEMORY_SCOPES = ("tree", "project", "global")
MEMORY_ACTIONS = ("search", "store")


def resolve_memory_namespace(
    *,
    scope: str | None = None,
    graph_id: str | None = None,
    project_id: str | None = None,
    namespace: str | None = None,
) -> str:
    """
    Map a Memory node scope to a vector namespace.

    Tiers:
      tree    → tree:{graph_id}     — this decision-tree only; other nodes in the same canvas share it
      project → project:{project_id} — all node graphs under the same project
      global  → global              — pan-project pool (cross-project research)
    """
    if namespace and str(namespace).strip():
        return str(namespace).strip()
    sc = (scope or "tree").strip().lower()
    if sc not in MEMORY_SCOPES:
        sc = "tree"
    if sc == "global":
        return "global"
    if sc == "project":
        pid = (project_id or "default").strip() or "default"
        # keep ids path-safe-ish
        pid = re.sub(r"[^A-Za-z0-9._:-]+", "-", pid)[:128]
        return f"project:{pid}"
    # tree
    gid = (graph_id or "canvas").strip() or "canvas"
    gid = re.sub(r"[^A-Za-z0-9._:-]+", "-", gid)[:128]
    return f"tree:{gid}"


def memory_op_from_node(node: dict[str, Any], graph: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a resolved memory op descriptor from a memory node."""
    d = node.get("data") or {}
    g = graph or {}
    scope = (d.get("scope") or "tree").strip().lower()
    if scope not in MEMORY_SCOPES:
        scope = "tree"
    action = (d.get("action") or "search").strip().lower()
    if action not in MEMORY_ACTIONS:
        action = "search"
    project_id = (
        d.get("project_id")
        or g.get("project_id")
        or g.get("service_id")
        or d.get("service_id")
    )
    ns = resolve_memory_namespace(
        scope=scope,
        graph_id=g.get("id") or node.get("graph_id"),
        project_id=str(project_id) if project_id else None,
        namespace=d.get("namespace"),
    )
    return {
        "node_id": node.get("id"),
        "label": d.get("label") or "Memory",
        "scope": scope,
        "action": action,
        "namespace": ns,
        "project_id": project_id,
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
        # recursive: allow feedback edges (cycles), output → earlier nodes, multi-pass
        "recursive": False,
        "max_iterations": DEFAULT_MAX_ITERATIONS,
        "updated_at": time.time(),
    }


def _edge_kind(edge: dict[str, Any]) -> str:
    kind = str(edge.get("kind") or "data").strip().lower()
    return kind if kind in EDGE_KINDS else "data"


def adjacency(
    graph: dict[str, Any],
    *,
    kinds: tuple[str, ...] | None = None,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build outgoing/incoming adjacency. kinds=None uses all edges; else filter by kind."""
    nodes = {n["id"] for n in graph.get("nodes") or [] if n.get("id")}
    outgoing: dict[str, list[str]] = {nid: [] for nid in nodes}
    incoming: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in graph.get("edges") or []:
        a, b = e.get("from"), e.get("to")
        if a not in nodes or b not in nodes:
            continue
        if kinds is not None and _edge_kind(e) not in kinds:
            continue
        if b not in outgoing[a]:
            outgoing[a].append(b)
        if a not in incoming[b]:
            incoming[b].append(a)
    return outgoing, incoming


def path_exists(outgoing: dict[str, list[str]], src: str, dst: str) -> bool:
    """True if dst is reachable from src following outgoing edges."""
    if src == dst:
        return True
    seen: set[str] = set()
    stack = [src]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for nxt in outgoing.get(cur) or []:
            if nxt == dst:
                return True
            if nxt not in seen:
                stack.append(nxt)
    return False


def edge_would_cycle(graph: dict[str, Any], frm: str, to: str) -> bool:
    """True if adding frm→to creates a cycle (to can already reach frm)."""
    if frm == to:
        return True
    outgoing, _ = adjacency(graph, kinds=("data", "feedback"))
    return path_exists(outgoing, to, frm)


def classify_edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return edges with kind set: feedback when explicitly marked, or when the edge
    closes a cycle under recursive graphs. Non-recursive graphs keep kind as stored.
    """
    recursive = bool(graph.get("recursive"))
    nodes = {n["id"] for n in graph.get("nodes") or [] if n.get("id")}
    raw = [e for e in (graph.get("edges") or []) if e.get("from") in nodes and e.get("to") in nodes]
    # First pass: honour explicit feedback; build forward-only graph for detection
    forward: list[dict[str, Any]] = []
    out_edges: list[dict[str, Any]] = []
    for e in raw:
        kind = _edge_kind(e)
        if kind == "feedback":
            out_edges.append({**e, "kind": "feedback"})
            continue
        forward.append(e)
    # Temporary graph of only candidate data edges
    probe = {"nodes": graph.get("nodes") or [], "edges": []}
    for e in forward:
        frm, to = e.get("from"), e.get("to")
        if recursive and edge_would_cycle(probe, frm, to):
            out_edges.append({**e, "kind": "feedback"})
        else:
            probe["edges"].append({**e, "kind": "data"})
            out_edges.append({**e, "kind": "data"})
    return out_edges


def topo_order(graph: dict[str, Any]) -> dict[str, Any]:
    """
    Topological order using forward (data) edges only.
    Feedback edges are listed separately and do not block ordering.
    Fan-in/fan-out are fully supported (multiple parents/children).
    """
    nodes = {n["id"]: n for n in graph.get("nodes") or [] if n.get("id")}
    classified = classify_edges(graph)
    data_edges = [e for e in classified if e["kind"] == "data"]
    feedback_edges = [e for e in classified if e["kind"] == "feedback"]

    g_forward = {"nodes": list(nodes.values()), "edges": data_edges}
    outgoing, incoming = adjacency(g_forward, kinds=("data",))

    # Kahn: multi-parent aware
    indeg = {nid: len(incoming.get(nid) or []) for nid in nodes}
    # Prefer goal nodes first among zero-indegree
    zeros = sorted(
        [nid for nid, d in indeg.items() if d == 0],
        key=lambda nid: (0 if (nodes[nid].get("type") == "goal") else 1, nid),
    )
    ordered: list[str] = []
    while zeros:
        nid = zeros.pop(0)
        ordered.append(nid)
        for nxt in outgoing.get(nid) or []:
            indeg[nxt] = indeg.get(nxt, 0) - 1
            if indeg[nxt] == 0:
                zeros.append(nxt)
                zeros.sort(
                    key=lambda x: (0 if (nodes[x].get("type") == "goal") else 1, x)
                )

    leftover = [nid for nid, d in indeg.items() if d > 0]
    # If cycles remain among data edges, append leftovers (stable) and flag
    if leftover:
        for nid in sorted(leftover):
            if nid not in ordered:
                ordered.append(nid)

    return {
        "order": ordered,
        "data_edges": data_edges,
        "feedback_edges": feedback_edges,
        "incoming": {k: list(v) for k, v in incoming.items()},
        "outgoing": {k: list(v) for k, v in outgoing.items()},
        "has_data_cycle": bool(leftover),
        "recursive": bool(graph.get("recursive")),
        "max_iterations": int(graph.get("max_iterations") or DEFAULT_MAX_ITERATIONS),
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
        editable = {
            "model": agent.get("model"),
            "needs": list(agent.get("needs") or []),
            "strategy": agent.get("strategy") or "best_score",
            "max_cost": agent.get("max_cost"),
            "tier": agent.get("tier"),
        }
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
                "max_cost": agent.get("max_cost"),
                "needs": list(agent.get("needs") or []),
                "available": bool(agent.get("available")),
                "service_id": service.get("id"),
                "instructions_md": service.get("behavior_markdown") or "",
                "instructions_source": service.get("behavior_source") or "",
                "model_explicit": bool(agent.get("model_explicit")),
                # Baseline values let graph_to_service_patch distinguish an
                # actual inspector edit from resolved display metadata. This
                # is especially important for model/tier: every loaded node
                # has both, but an unrelated save must not pin either one.
                "_service_original": editable,
            },
        }

    # Prefer neutral task_template (discipline brief without project names) over
    # the short marketing summary when the caller did not supply a live goal.
    default_goal = (
        goal_text
        or service.get("task_template")
        or service.get("summary")
        or service.get("label")
        or "Describe the task"
    )
    goal = new_node(
        "goal",
        30,
        center_y,
        {
            "label": "Task / goal",
            "text": default_goal,
            "service_id": service.get("id"),
        },
    )
    goal["id"] = f"{service_id}-goal"

    # Memory node: reuses the same three-tier scope/action model as the freeform
    # canvas (see resolve_memory_namespace/memory_op_from_node) — a preset that
    # saves this node opts its lead call into that pool; deleting it opts out.
    memory_cfg = {**_DEFAULT_DATA["memory"], **(service.get("memory") or {})}
    memory_node = new_node(
        "memory",
        100,
        center_y + 90,
        {**memory_cfg, "label": "Cross-project memory", "service_id": service.get("id")},
    )
    memory_node["id"] = f"{service_id}-memory"

    # Lead's real fallback chain (primary -> ... -> local-GPU fallback), made
    # visible and rewirable: see _resolve_agent/_build_display_chain in services.py.
    raw_chain = (lead or {}).get("fallback_chain") or []
    # Normally _resolve_agent already returns list[dict] here (_normalize_chain),
    # but tolerate a direct caller passing catalog-shaped list[str] too, rather
    # than silently dropping every entry down to just the single winning model.
    chain = []
    for link in raw_chain:
        if isinstance(link, dict) and link.get("model"):
            chain.append(link)
        elif isinstance(link, str) and link:
            chain.append({"model": link, "tier": None})
    # No authored chain in the catalog: `chain` here is either empty or
    # `_build_display_chain`'s live auto-ranked preview (see _resolve_agent).
    # Either way it's synthetic/display-only — graph_to_service_patch must not
    # save it back as a real chain (that would freeze the current auto-ranking
    # into the catalog on any unrelated save, and shadow a plain pin_model
    # edit on the lead).
    synthetic = not bool(lead and lead.get("chain_authored"))
    if synthetic and not chain and lead and lead.get("model"):
        chain = [{"model": lead.get("model"), "tier": lead.get("tier")}]
    route_nodes = []
    route_x = 130
    for index, link in enumerate(chain):
        is_local_last = link.get("tier") == "local" and index == len(chain) - 1
        rn = new_node(
            "route",
            route_x,
            center_y - 90,
            {
                "model": link.get("model"),
                "tier": link.get("tier"),
                "label": "Local GPU fallback" if is_local_last else f"Route {index + 1}",
                "service_id": service.get("id"),
                "synthetic": synthetic,
            },
        )
        rn["id"] = f"{service_id}-route-{index + 1}"
        route_nodes.append(rn)
        route_x += 110
    shift = len(route_nodes) * 110

    lead_node = agent_node(lead, f"{service_id}-lead", "master", 180 + shift, center_y, "Lead")
    worker_nodes = [
        agent_node(agent, f"{service_id}-worker-{index + 1}", "worker", 370 + shift, 45 + index * 130, f"Worker {index + 1}")
        for index, agent in enumerate(workers)
    ]
    reviewer_node = agent_node(reviewer, f"{service_id}-review", "analyser", 570 + shift, center_y, "Review")
    synthesis_node = agent_node(lead, f"{service_id}-synthesis", "master", 760 + shift, center_y, "Final synthesis")
    synthesis_node["data"]["label"] = "Final synthesis"
    synthesis_node["data"]["role"] = "synthesizer"
    output = new_node("output", 930 + shift, center_y, {"label": "Final answer", "service_id": service.get("id")})
    output["id"] = f"{service_id}-output"

    if not worker_nodes:
        worker_nodes = [agent_node(None, f"{service_id}-worker-1", "worker", 370 + shift, center_y, "Unresolved worker")]
    nodes = [goal, memory_node, *route_nodes, lead_node, *worker_nodes, reviewer_node, synthesis_node, output]
    edges = []

    def connect(source: dict[str, Any], target: dict[str, Any], kind: str = "data") -> None:
        edges.append(
            {
                "id": f"e-{source['id']}-{target['id']}",
                "from": source["id"],
                "to": target["id"],
                "kind": kind if kind in EDGE_KINDS else "data",
            }
        )

    connect(goal, memory_node)
    chain_entry = route_nodes[0] if route_nodes else lead_node
    connect(memory_node, chain_entry)
    for a, b in zip(route_nodes, route_nodes[1:]):
        connect(a, b)
    if route_nodes:
        connect(route_nodes[-1], lead_node)
    # Fan-out: lead → each worker; fan-in: each worker → reviewer
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
    order = ["goal", "master", "analyser", "worker", "tester", "private", "memory", "slash", "output"]
    buckets: dict[str, list] = {t: [] for t in order}
    for n in nodes:
        t = n.get("type")
        if t in buckets:
            buckets[t].append(n)
        elif t:
            # unknown types appended after workers
            buckets.setdefault("worker", []).append(n)
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
        "tester → private (local GPU + PDF/text folder) → memory → slash → output",
        "pass-through nodes (memory/slash/output): context and side effects only",
    ]
    return {"nodes": chain if graph is None else nodes, "edges": edges, "practices": practices}


def graph_to_pipeline(graph: dict[str, Any]) -> dict[str, Any]:
    """Convert node graph to aetherstack.pipeline.v1 stages (multi-parent topo; feedback separate)."""
    nodes = {n["id"]: n for n in graph.get("nodes") or [] if n.get("id")}
    layout = topo_order(graph)
    ordered = layout["order"]
    incoming = layout["incoming"]
    outgoing = layout["outgoing"]
    feedback_edges = layout["feedback_edges"]

    stages = []
    memory_ops: list[dict[str, Any]] = []
    slash_cmds = ["/done all", "/compact"]
    goal_text = ""
    for nid in ordered:
        n = nodes.get(nid)
        if not n:
            continue
        t = n.get("type")
        d = n.get("data") or {}
        if t == "goal":
            goal_text = d.get("text") or ""
            continue
        if t == "slash":
            slash_cmds = d.get("commands") or slash_cmds
            continue
        if t == "memory":
            memory_ops.append(memory_op_from_node(n, graph))
            continue
        if t == "output":
            continue
        if t == "route":
            continue
        role = d.get("role") or ROLE_MAP.get(t, t)
        if t == "private":
            globs = d.get("input_globs") or list(DEFAULT_PRIVATE_GLOBS)
            if isinstance(globs, str):
                globs = [g.strip() for g in globs.split(",") if g.strip()]
            stage = {
                "id": n.get("id"),
                "label": d.get("label") or NODE_TYPES["private"]["label"],
                "role": "private_local",
                "purpose": d.get("purpose")
                or "Local GPU private inference over PDF/text folder corpus",
                "select": {
                    "tier": "local",
                    "strategy": d.get("strategy") or "local_first",
                    "max_cost": d.get("max_cost") or "low",
                    "model": d.get("model") or "local-default",
                },
                "prefer_models": [d.get("model") or "local-default"],
                "prefer_makers": [],
                "needs": d.get("needs") or ["local", "gpu", "chat", "private"],
                "private": True,
                "gpu_only": True if d.get("gpu_only", True) else False,
                "private_vault": True if d.get("private_vault", True) else False,
                "input_folder": str(d.get("input_folder") or "")[:2000],
                "input_globs": list(globs)[:32],
                "ack": False,
                "gate": bool(d.get("gate")),
                "parallel": 1,
                "behavior_markdown": str(d.get("instructions_md") or "")[:100_000],
                "behavior_source": str(d.get("instructions_source") or "")[:500],
                "pass_through": False,
                "workspace_write": bool(d.get("workspace_write")),
                "inputs_from": list(incoming.get(nid) or []),
                "outputs_to": list(outgoing.get(nid) or []),
            }
            stages.append(stage)
            continue
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
            "pass_through": bool(NODE_TYPES.get(t, {}).get("pass_through")),
            "workspace_write": bool(d.get("workspace_write")),
            # Multi-wire topology (fan-in / fan-out)
            "inputs_from": list(incoming.get(nid) or []),
            "outputs_to": list(outgoing.get(nid) or []),
        }
        # clean empty select keys
        stage["select"] = {k: v for k, v in stage["select"].items() if v not in (None, "")}
        stages.append(stage)

    tags = ["from-graph", "visual"]
    if graph.get("recursive") or feedback_edges:
        tags.append("recursive")

    return {
        "schema": "aetherstack.pipeline.v1",
        "id": graph.get("id") or f"from-graph-{uuid.uuid4().hex[:6]}",
        "title": graph.get("title") or "From node graph",
        "description": f"Converted from graph; goal={goal_text[:120]}",
        "tags": tags,
        "hw_weight": graph.get("hw_weight") or "medium",
        "token_saver": bool(graph.get("token_saver", False)),
        "mode": "multi_agent",
        "stages": stages,
        "memory_ops": memory_ops,
        "edges": layout["data_edges"],
        "feedback_edges": feedback_edges,
        "recursive": bool(graph.get("recursive")),
        "max_iterations": int(graph.get("max_iterations") or DEFAULT_MAX_ITERATIONS),
        "has_data_cycle": layout["has_data_cycle"],
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


def graph_to_service_patch(graph: dict[str, Any]) -> dict[str, Any]:
    """Extract role edits (pinned model, needs, strategy, max_cost), the memory
    node's tier/action config, and the wired fallback-chain order from a
    service-bound graph (see service_to_graph) so they can be written back into
    the matching service_catalog.yaml entry."""
    service_id = graph.get("service_id")
    if not service_id:
        raise ValueError("graph is not bound to a service (missing service_id)")

    def role_patch(node: dict[str, Any] | None) -> dict[str, Any]:
        d = (node or {}).get("data") or {}
        patch: dict[str, Any] = {}
        original = d.get("_service_original")
        fields = {
            "pin_model": "model",
            "needs": "needs",
            "strategy": "strategy",
            "max_cost": "max_cost",
            "tier": "tier",
        }
        if isinstance(original, dict):
            edited = set(d.get("edited_fields") or [])
            if d.get("model_explicit") and d.get("model") != original.get("model"):
                edited.add("model")
            for catalog_key, data_key in fields.items():
                current = d.get(data_key)
                before = original.get(data_key)
                if data_key in edited and current != before:
                    # None means delete this authored override. An empty needs
                    # list has the same meaning: fall back to the catalog/runtime
                    # default rather than persisting a silently ineffective [].
                    patch[catalog_key] = None if current in (None, "") or (data_key == "needs" and current == []) else current
        else:
            # Backward-compatible boundary for service graphs created before
            # _service_original existed. Only explicit UI intent is safe to
            # persist; resolved values must remain display-only.
            edited = set(d.get("edited_fields") or [])
            if d.get("model_explicit"):
                edited.add("model")
            for catalog_key, data_key in fields.items():
                if data_key in edited:
                    current = d.get(data_key)
                    patch[catalog_key] = None if current in (None, "") or (data_key == "needs" and current == []) else current
        return patch

    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    lead = nodes.get(f"{graph.get('id')}-lead")
    reviewer = nodes.get(f"{graph.get('id')}-review")
    memory_node = nodes.get(f"{graph.get('id')}-memory")
    workers = sorted(
        (n for nid, n in nodes.items() if nid.startswith(f"{graph.get('id')}-worker-")),
        key=lambda n: (
            (0, int(n["id"].rsplit("-", 1)[-1]))
            if n["id"].rsplit("-", 1)[-1].isdigit()
            else (1, n["id"])
        ),
    )
    # Note: a node's `instructions_md` is the long external behavior-profile
    # markdown (profiles/services/<id>.md via load_service_profile), not the
    # catalog's short `instructions:` field — the two are unrelated text, and
    # there is currently no write-back path for profile-markdown edits made in
    # the inspector, so this patch intentionally leaves both alone rather than
    # overwriting the wrong field.

    patch: dict[str, Any] = {"id": service_id}
    lead_patch = role_patch(lead)
    # Product rule: an exact lead-model choice replaces authored routing. If
    # both were persisted, _resolve_agent's route chain would shadow the pin
    # and the model selector would appear to have done nothing.
    lead_pin_changed = "pin_model" in lead_patch and lead_patch["pin_model"] is not None
    if lead_patch:
        patch["lead"] = lead_patch
    reviewer_patch = role_patch(reviewer)
    if reviewer_patch:
        patch["reviewer"] = reviewer_patch
    if workers:
        patch["workstreams"] = [role_patch(w) for w in workers]

    # Memory node uses the same scope/action/project_id/namespace fields as the
    # freeform canvas (MEMORY_SCOPES/MEMORY_ACTIONS) — deleting the node from
    # this preset's graph and saving means the preset stops opting into the pool.
    if memory_node is not None:
        d = memory_node.get("data") or {}
        scope = (d.get("scope") or "tree").strip().lower()
        if scope not in MEMORY_SCOPES:
            scope = "tree"
        action = (d.get("action") or "search").strip().lower()
        if action not in MEMORY_ACTIONS:
            action = "search"
        patch["memory"] = {
            "scope": scope,
            "action": action,
            "project_id": d.get("project_id") or None,
            "namespace": d.get("namespace") or None,
        }
    else:
        patch["memory"] = None

    # Walk the wired edges (not node ids) starting from goal, so reordering or
    # rewiring the route chain on the canvas is what changes the saved fallback
    # order — not the original node layout. Deliberately does NOT require the
    # memory node: deleting memory (to opt the preset out of it) must not also
    # silently stop route edits from saving.
    outgoing: dict[str, list[str]] = {}
    for e in graph.get("edges") or []:
        if e.get("kind", "data") != "data":
            continue
        outgoing.setdefault(e.get("from"), []).append(e.get("to"))
    goal_node = nodes.get(f"{graph.get('id')}-goal")
    lead_id = f"{graph.get('id')}-lead"
    chain_models: list[str] = []
    cursor = goal_node["id"] if goal_node is not None else None
    seen: set[str] = set()
    while cursor is not None and cursor != lead_id:
        candidates = [
            nid
            for nid in outgoing.get(cursor, [])
            if nid not in seen
            and nid in nodes
            and (nid == lead_id or nodes[nid].get("type") in ("memory", "route"))
        ]
        if len(candidates) > 1:
            raise ValueError("service route is ambiguous: each goal/memory/route node must have one path to lead")
        nxt = candidates[0] if candidates else None
        if nxt is None:
            break
        seen.add(nxt)
        node = nodes[nxt]
        if node.get("type") == "route":
            d = node.get("data") or {}
            # A synthetic placeholder (service_to_graph's "no authored chain
            # yet, show the live-resolved model so the canvas isn't empty")
            # must not be saved back as a real one-entry chain — that would
            # fabricate a chain out of nothing on every save and bury a plain
            # pin_model edit on the lead under a spurious fallback_chain.
            if not d.get("synthetic") and d.get("model"):
                chain_models.append(d["model"])
        cursor = nxt
    if goal_node is not None and lead_id in nodes and cursor != lead_id:
        raise ValueError("service route is disconnected: wire goal through optional memory/routes to lead")
    # Always write the chain — including an explicit empty list — whenever this
    # is a real service graph (goal + lead both present): deleting every route
    # node and saving must clear the catalog's old chain, not leave it stuck.
    if goal_node is not None and lead_id in nodes:
        patch.setdefault("lead", {})
        patch["lead"]["fallback_chain"] = [] if lead_pin_changed else chain_models
    return patch


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
        "memory_ops": pipe.get("memory_ops") or [],
        "recursive": pipe.get("recursive"),
        "max_iterations": pipe.get("max_iterations"),
        "feedback_edges": pipe.get("feedback_edges") or [],
        "flow": " → ".join(
            f"{s.get('label') or s.get('stage_id')}({s.get('model')})" for s in stages_out
        ),
        "on_complete": pipe.get("on_complete"),
    }
