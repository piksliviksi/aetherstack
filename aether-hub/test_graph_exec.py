#!/usr/bin/env python3
"""Graph execution: stage order, output threading, and Memory-node read/write."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from graph_exec import execute_graph  # noqa: E402


class FakeMemory:
    """Minimal MemoryStore stand-in that records what the graph did."""

    def __init__(self, hits=None):
        self.hits = hits or []
        self.written = []
        self.messages = []
        self.searched = []

    def search(self, query, namespace="default", top_k=5):
        self.searched.append({"query": query, "namespace": namespace})
        return {"hits": self.hits}

    def upsert_vector(self, text, namespace="default", meta=None, id=None, embedding=None):
        self.written.append({"text": text, "namespace": namespace, "meta": meta or {}})
        return {"id": f"vec-{len(self.written)}", "namespace": namespace, "dim": 3}

    def append_message(self, session_id, role, content, meta=None):
        self.messages.append({"session_id": session_id, "role": role, "content": content})


def _snapshot() -> dict:
    return {
        "models": {
            "claude-cli": {
                "available": True,
                "executor": "host_cli",
                "tier": "subscription",
                "provider": "anthropic",
                "capabilities": ["chat", "code", "reason"],
            },
            "local-default": {
                "available": True,
                "tier": "local",
                "provider": "ollama",
                "capabilities": ["chat", "code"],
            },
        }
    }


def _graph(with_memory=True) -> dict:
    nodes = [
        {"id": "g1", "type": "goal", "data": {"text": "build the thing"}},
        {"id": "m1", "type": "master", "data": {"label": "Plan", "model": "claude-cli"}},
        {"id": "w1", "type": "worker", "data": {"label": "Build", "model": "local-default"}},
    ]
    edges = [
        {"id": "e1", "from": "g1", "to": "m1"},
        {"id": "e2", "from": "m1", "to": "w1"},
    ]
    if with_memory:
        nodes.append(
            {
                "id": "mem1",
                "type": "memory",
                "data": {"label": "Pool", "scope": "tree", "action": "search"},
            }
        )
        nodes.append(
            {
                "id": "mem2",
                "type": "memory",
                "data": {"label": "Pool", "scope": "tree", "action": "store"},
            }
        )
        edges.append({"id": "e3", "from": "w1", "to": "mem2"})
    return {"id": "test-graph", "title": "Test", "nodes": nodes, "edges": edges}


def _completion(calls):
    def run(call, messages):
        calls.append({"model": call["model"], "messages": messages})
        return {
            "model": call["model"],
            "content": f"output from {call['model']}",
            "usage": {"total_tokens": 10},
        }

    return run


def test_stages_run_in_order_and_thread_their_output() -> None:
    calls = []
    result = execute_graph(
        _graph(with_memory=False),
        _snapshot(),
        {"goal": "build the thing"},
        completion=_completion(calls),
    )
    assert result["ok"] is True
    assert [c["model"] for c in calls] == ["claude-cli", "local-default"]
    # the worker sees the master's output threaded in
    worker_user = calls[1]["messages"][-1]["content"]
    assert "output from claude-cli" in worker_user
    assert result["answer"] == "output from local-default"
    assert result["usage"]["total_tokens"] == 20
    assert result["stage_count"] == 2


def test_memory_nodes_actually_read_and_write() -> None:
    """The regression this module exists for: memory_ops used to be inert."""
    memory = FakeMemory(hits=[{"text": "earlier decision: use postgres"}])
    calls = []
    result = execute_graph(
        _graph(with_memory=True),
        _snapshot(),
        {"goal": "build the thing"},
        completion=_completion(calls),
        memory=memory,
        session_id="sess-1",
    )
    # search node ran, and its hit reached the first stage's prompt
    assert memory.searched, "expected the Memory search node to run"
    assert "use postgres" in calls[0]["messages"][-1]["content"]
    assert result["memory_context_chars"] > 0
    # store node ran
    assert memory.written, "expected the Memory store node to write"
    assert "output from local-default" in memory.written[0]["text"]
    assert result["memory_written"][0]["namespace"] == memory.written[0]["namespace"]
    # and the turn landed in the shared session pool Auto mode reads
    assert [m["role"] for m in memory.messages] == ["user", "assistant"]
    assert memory.messages[0]["session_id"] == "sess-1"


def test_graph_without_memory_nodes_still_runs() -> None:
    memory = FakeMemory()
    result = execute_graph(
        _graph(with_memory=False),
        _snapshot(),
        {"goal": "x"},
        completion=_completion([]),
        memory=memory,
        session_id="sess-2",
    )
    assert result["ok"] is True
    assert memory.written == []
    assert result["memory_context_chars"] == 0


def test_a_failing_stage_does_not_abort_the_run() -> None:
    def flaky(call, messages):
        if call["model"] == "claude-cli":
            raise RuntimeError("rate limited")
        return {"model": call["model"], "content": "recovered", "usage": {}}

    result = execute_graph(
        _graph(with_memory=False), _snapshot(), {"goal": "x"}, completion=flaky
    )
    assert result["answer"] == "recovered"
    errors = [s for s in result["steps"] if s.get("error")]
    assert len(errors) == 1
    assert "rate limited" in errors[0]["error"]


def test_every_stage_failing_raises() -> None:
    def dead(call, messages):
        raise RuntimeError("no capacity")

    with pytest.raises(RuntimeError, match="every stage failed"):
        execute_graph(_graph(with_memory=False), _snapshot(), {"goal": "x"}, completion=dead)


def test_goal_is_required() -> None:
    graph = _graph(with_memory=False)
    graph["nodes"][0]["data"]["text"] = ""
    with pytest.raises(ValueError, match="goal is required"):
        execute_graph(graph, _snapshot(), {}, completion=_completion([]))


def test_graph_with_no_runnable_stages_raises() -> None:
    empty = {"id": "g", "nodes": [{"id": "g1", "type": "goal", "data": {"text": "hi"}}], "edges": []}
    with pytest.raises(ValueError, match="no runnable stages"):
        execute_graph(empty, _snapshot(), {"goal": "hi"}, completion=_completion([]))
