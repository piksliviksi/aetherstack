#!/usr/bin/env python3
"""
E2E exercise of node graph + memory tiers + inference on:
  "How do radio waves penetrate stone?"

- Builds a decision tree with goal → lead → worker → memory(search tree) →
  memory(store tree) → memory(store project) → output
- Stores/searches tree + project namespaces (memory node semantics)
- Runs Hub service inference (chat path) with local fallback
- Writes a chat-ready result file and Hub session for VS Code chat context
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HUB = "http://127.0.0.1:8766"
LITELLM = "http://127.0.0.1:4000/v1"
API_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
if not API_KEY:
    raise RuntimeError("LITELLM_MASTER_KEY is required")
GRAPH_ID = "test-radio-stone"
PROJECT_ID = "lab-rf-stone"
SESSION_ID = "vscode-chat-radio-stone"
GOAL = (
    "How do radio waves penetrate stone? Explain skin depth, frequency dependence, "
    "attenuation in rock/concrete, and practical implications for RF through walls "
    "or caves. Keep it accurate and concise (about 250-400 words)."
)
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".aetherstack" / "e2e-radio-stone-result.md"
sys.path.insert(0, str(ROOT / "aether-hub"))
try:
    from graph import graph_to_pipeline, resolve_memory_namespace, memory_op_from_node  # noqa: E402
except ImportError:
    graph_to_pipeline = None  # type: ignore
    resolve_memory_namespace = None  # type: ignore
    memory_op_from_node = None  # type: ignore


def http(method: str, url: str, body: dict | None = None, timeout: float = 180) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"{method} {url} -> {e.code}: {err}") from e


def chat_local(prompt: str, model: str = "local-default", max_tokens: int = 700) -> str:
    d = http(
        "POST",
        f"{LITELLM}/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        },
        timeout=300,
    )
    return ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def mem_upsert(namespace: str, text: str, meta: dict | None = None) -> dict:
    return http(
        "POST",
        f"{HUB}/api/memory/vectors",
        {"namespace": namespace, "text": text, "meta": meta or {}},
    )


def mem_search(namespace: str, query: str, top_k: int = 5) -> dict:
    return http(
        "POST",
        f"{HUB}/api/memory/search",
        {"namespace": namespace, "query": query, "top_k": top_k},
    )


def session_msg(role: str, content: str) -> dict:
    return http(
        "POST",
        f"{HUB}/api/memory/sessions/{SESSION_ID}/messages",
        {"role": role, "content": content, "index": True},
    )


def build_graph() -> dict:
    """Wire multi-node tree with fan-in/out + memory tiers (canvas schema)."""
    nodes = [
        {
            "id": "n_goal",
            "type": "goal",
            "x": 40,
            "y": 140,
            "data": {
                "label": "Goal",
                "text": GOAL,
            },
        },
        {
            "id": "n_lead",
            "type": "master",
            "x": 260,
            "y": 120,
            "data": {
                "label": "Lead RF",
                "role": "mastermind",
                "tier": "local",
                "strategy": "local_first",
                "model": "local-default",
                "max_cost": "low",
            },
        },
        {
            "id": "n_worker",
            "type": "worker",
            "x": 480,
            "y": 80,
            "data": {
                "label": "Physics worker",
                "role": "builder",
                "tier": "local",
                "strategy": "local_first",
                "model": "local-default",
                "max_cost": "low",
                "parallel": 1,
            },
        },
        {
            "id": "n_review",
            "type": "analyser",
            "x": 480,
            "y": 200,
            "data": {
                "label": "Reviewer",
                "role": "critic",
                "tier": "local",
                "strategy": "local_first",
                "model": "local-default",
                "gate": True,
                "max_cost": "low",
            },
        },
        {
            "id": "n_mem_search",
            "type": "memory",
            "x": 700,
            "y": 60,
            "data": {
                "label": "Tree recall",
                "scope": "tree",
                "action": "search",
            },
        },
        {
            "id": "n_mem_store_tree",
            "type": "memory",
            "x": 700,
            "y": 160,
            "data": {
                "label": "Tree store",
                "scope": "tree",
                "action": "store",
            },
        },
        {
            "id": "n_mem_store_proj",
            "type": "memory",
            "x": 700,
            "y": 260,
            "data": {
                "label": "Project store",
                "scope": "project",
                "action": "store",
                "project_id": PROJECT_ID,
            },
        },
        {
            "id": "n_out",
            "type": "output",
            "x": 920,
            "y": 160,
            "data": {"label": "Final answer"},
        },
    ]
    # Fan-out lead→worker+review; fan-in both→mem_search; then store tiers → output
    edges = [
        {"id": "e1", "from": "n_goal", "to": "n_lead", "kind": "data"},
        {"id": "e2", "from": "n_lead", "to": "n_worker", "kind": "data"},
        {"id": "e3", "from": "n_lead", "to": "n_review", "kind": "data"},
        {"id": "e4", "from": "n_worker", "to": "n_mem_search", "kind": "data"},
        {"id": "e5", "from": "n_review", "to": "n_mem_search", "kind": "data"},
        {"id": "e6", "from": "n_mem_search", "to": "n_mem_store_tree", "kind": "data"},
        {"id": "e7", "from": "n_mem_store_tree", "to": "n_mem_store_proj", "kind": "data"},
        {"id": "e8", "from": "n_mem_store_proj", "to": "n_out", "kind": "data"},
    ]
    return {
        "schema": "aetherstack.graph.v1",
        "id": GRAPH_ID,
        "title": "Radio waves through stone — memory E2E",
        "project_id": PROJECT_ID,
        "recursive": False,
        "nodes": nodes,
        "edges": edges,
    }


def main() -> int:
    print("=== E2E radio-through-stone graph + memory + inference ===\n")
    health = http("GET", f"{HUB}/api/health", timeout=10)
    print("hub", health.get("ok"), "memory", (health.get("memory") or {}).get("backend"))

    graph = build_graph()
    try:
        saved = http("POST", f"{HUB}/api/graphs", graph, timeout=30)
        print("graph saved", saved.get("id") or GRAPH_ID)
    except Exception as e:
        print("graph save soft-fail (hub may be older image):", e)

    # Prefer in-repo graph.py (new memory tiers / multi-wire). Live Docker Hub may lag until 0.3.15 runtime.
    if graph_to_pipeline is not None:
        pipe = graph_to_pipeline(graph)
        print("pipeline via local graph.py (new node logic)")
    else:
        pipe = http("POST", f"{HUB}/api/graphs/to-pipeline", {"graph": graph}, timeout=30)
        print("pipeline via hub API")
    mem_ops = list(pipe.get("memory_ops") or [])
    if not mem_ops and memory_op_from_node is not None:
        mem_ops = [
            memory_op_from_node(n, graph)
            for n in graph.get("nodes") or []
            if n.get("type") == "memory"
        ]
    if not mem_ops and resolve_memory_namespace is not None:
        mem_ops = [
            {
                "scope": "tree",
                "action": "search",
                "namespace": resolve_memory_namespace(scope="tree", graph_id=GRAPH_ID),
            },
            {
                "scope": "tree",
                "action": "store",
                "namespace": resolve_memory_namespace(scope="tree", graph_id=GRAPH_ID),
            },
            {
                "scope": "project",
                "action": "store",
                "namespace": resolve_memory_namespace(scope="project", project_id=PROJECT_ID),
            },
        ]
    print("memory_ops", json.dumps(mem_ops, indent=2))
    stages = pipe.get("stages") or []
    print(
        "stages",
        [
            (s.get("id"), s.get("role"), s.get("inputs_from") or [], s.get("outputs_to") or [])
            for s in stages
        ],
    )
    # Multi-wire: lead fans out to worker + review
    lead = next((s for s in stages if s.get("id") == "n_lead"), None)
    if lead:
        outs = set(lead.get("outputs_to") or [])
        print("lead fan-out", outs)
        assert "n_worker" in outs and "n_review" in outs, "expected fan-out from lead to worker+review"
    assert any(m.get("scope") == "tree" for m in mem_ops), "expected tree memory op"
    assert any(m.get("scope") == "project" for m in mem_ops), "expected project memory op"
    tree_ns = next(m["namespace"] for m in mem_ops if m["scope"] == "tree")
    proj_ns = next(m["namespace"] for m in mem_ops if m["scope"] == "project")
    print("resolved namespaces", tree_ns, proj_ns)
    assert tree_ns == f"tree:{GRAPH_ID}", tree_ns
    assert proj_ns == f"project:{PROJECT_ID}", proj_ns

    # Seed tree memory (what a prior node in this decision tree would have stored)
    seed = (
        "RF note for this tree: EM waves attenuate in conductive media; skin depth δ≈√(2/ωμσ). "
        "Higher frequency → less penetration in stone/concrete. Dry rock is more dielectric; "
        "wet rock with dissolved ions is lossier. HF/VHF penetrate better than GHz Wi‑Fi."
    )
    up = mem_upsert(tree_ns, seed, {"kind": "tree_seed", "graph": GRAPH_ID, "node": "n_mem_store_tree"})
    print("tree store", up.get("id"), "ns", tree_ns)

    # Memory search node: load tree context for later agents
    search = mem_search(tree_ns, "radio waves stone penetration frequency skin depth", top_k=3)
    hits = search.get("hits") or []
    print("tree search hits", len(hits), "top_score", (hits[0].get("score") if hits else None))
    assert hits, "tree memory search returned no hits"
    tree_context = "\n".join(h.get("text") or "" for h in hits)

    # Pass-through inference chain (simulates node sequence with local GPU/CPU model)
    print("\n--- node inference: lead ---")
    lead = chat_local(
        f"You are the lead agent on a node graph.\nGoal:\n{GOAL}\n\n"
        f"Tree memory (search node):\n{tree_context}\n\n"
        "Write a short plan (bullets) for answering the goal.",
        max_tokens=350,
    )
    print(lead[:400], "...\n" if len(lead) > 400 else "\n")

    print("--- node inference: worker ---")
    worker = chat_local(
        f"You are the physics worker node.\nGoal:\n{GOAL}\n\nLead plan:\n{lead}\n\n"
        f"Tree memory:\n{tree_context}\n\n"
        "Write the technical substance: mechanisms, formulas where useful, frequency bands, "
        "stone/concrete examples. No intro fluff.",
        max_tokens=700,
    )
    print(worker[:400], "...\n" if len(worker) > 400 else "\n")

    print("--- node inference: reviewer ---")
    review = chat_local(
        f"You are the reviewer node. Critique accuracy of the worker draft for RF through stone. "
        f"List any fixes, then a corrected short synthesis.\n\nWorker draft:\n{worker}",
        max_tokens=500,
    )
    print(review[:400], "...\n" if len(review) > 400 else "\n")

    print("--- final synthesis ---")
    final = chat_local(
        f"Answer the user goal directly for AetherStack Chat. No agent/process talk.\n\n"
        f"Goal:\n{GOAL}\n\nMaterial:\n{worker}\n\nReview notes:\n{review}\n",
        max_tokens=800,
    )
    print(final[:600], "...\n" if len(final) > 600 else "\n")
    assert len(final.strip()) > 80, "final answer too short"

    # Memory store nodes: write sequence output to tree + project pools
    tree_doc = f"[graph={GRAPH_ID} step=final]\n{final}"
    proj_doc = f"[project={PROJECT_ID} topic=rf-stone]\n{final}"
    t2 = mem_upsert(tree_ns, tree_doc, {"kind": "tree_store", "action": "store", "node": "n_mem_store_tree"})
    p2 = mem_upsert(proj_ns, proj_doc, {"kind": "project_store", "action": "store", "node": "n_mem_store_proj"})
    print("stored tree", t2.get("id"), "project", p2.get("id"))

    # Verify project-tier recall (other decision trees in same project)
    proj_hits = mem_search(proj_ns, "how radio waves go through rock and concrete", top_k=3)
    print("project search hits", len(proj_hits.get("hits") or []))
    assert proj_hits.get("hits"), "project memory search empty"

    # Optional: Hub research service (same path VS Code chat uses) — may use host CLIs
    service_result = None
    print("\n--- Hub service run (research / chat path) ---")
    try:
        service_result = http(
            "POST",
            f"{HUB}/api/services/research/run",
            {
                "goal": GOAL,
                "lean_mode": "strict",
                "token_saver": True,
                "history": [
                    {"role": "user", "content": "Use local models if cloud/CLI unavailable."},
                    {"role": "assistant", "content": final[:1500]},
                ],
                "session_id": SESSION_ID,
            },
            timeout=240,
        )
        print(
            "service ok",
            service_result.get("ok"),
            "model",
            service_result.get("model"),
            "answer_len",
            len(service_result.get("answer") or ""),
        )
        if service_result.get("answer"):
            final = service_result["answer"]
            mem_upsert(tree_ns, f"[service-research]\n{final}", {"kind": "service_answer"})
    except Exception as e:
        print("service run skipped/failed (local chain already produced answer):", e)

    # Session history for chat continuity
    session_msg("user", GOAL)
    session_msg("assistant", final)
    session_msg(
        "user",
        f"[system-test] Graph {GRAPH_ID} memory ops tree={tree_ns} project={proj_ns} completed.",
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    report = f"""# Radio waves through stone — AetherStack node E2E

**Graph:** `{GRAPH_ID}` · **Project:** `{PROJECT_ID}` · **Session:** `{SESSION_ID}`

## Decision tree (wired)

```
goal → lead ─┬→ worker ─┐
             └→ review ─┴→ memory(search tree) → memory(store tree) → memory(store project) → output
```

Memory namespaces:
- tree: `{tree_ns}`
- project: `{proj_ns}`

## Final answer (for AetherStack Chat)

{final}

## Service path

{json.dumps({k: service_result.get(k) for k in ('ok','model','service_id','usage')}, indent=2) if service_result else "local multi-node chain only (research service not used)"}

## How to view in VS Code Chat

1. Command Palette → **AetherStack: Show Chat View** (or open Chat panel).
2. Preset: **Research** (or Auto).
3. Paste or ask: `{GOAL[:80]}…`
4. Optional: Hub session id `{SESSION_ID}` already has this turn in Redis session memory.

Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}
"""
    OUT.write_text(report, encoding="utf-8")
    print("\nWrote", OUT)
    print("\n=== PASS ===")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("FAIL:", exc, file=sys.stderr)
        raise
