#!/usr/bin/env python3
"""Graph execution: stage order, output threading, and Memory-node read/write."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import gdpr  # noqa: E402
from graph_exec import MAX_STAGE_OUTPUT_CHARS, _join_upstream_blocks, execute_graph  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_gdpr_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(gdpr, "GDPR_SETTINGS_FILE", tmp_path / "gdpr_settings.json")
    gdpr._consented_sessions.clear()
    yield
    gdpr._consented_sessions.clear()


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

    def upsert_vector(self, text, namespace="default", meta=None, id=None, embedding=None, ttl_seconds=None):
        self.written.append({"text": text, "namespace": namespace, "meta": meta or {}, "ttl_seconds": ttl_seconds})
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
        calls.append({"model": call["model"], "messages": messages, "workspace_write": call.get("workspace_write", False)})
        return {
            "model": call["model"],
            "content": f"Observed output from {call['model']}: repository path src/example.py was checked and verification passed. The result includes concrete evidence and a reproducible test command for the next stage.",
            "usage": {"total_tokens": 10},
        }

    return run


def test_upstream_truncation_keeps_block_boundaries() -> None:
    blocks = [
        ("stage-a", "A" * (MAX_STAGE_OUTPUT_CHARS // 2 + 100)),
        ("stage-b", "B" * (MAX_STAGE_OUTPUT_CHARS // 2 + 100)),
    ]
    joined = _join_upstream_blocks(blocks)
    assert len(joined) <= MAX_STAGE_OUTPUT_CHARS
    assert joined.lstrip().startswith("[")
    # the most recent block (stage-b) must survive whole with its header intact
    assert "[stage-b]\n" + "B" * (MAX_STAGE_OUTPUT_CHARS // 2 + 100) in joined


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
    assert "Observed output from claude-cli" in worker_user
    assert result["answer"].startswith("Observed output from local-default")
    assert result["usage"]["total_tokens"] == 20
    assert result["stage_count"] == 2
    assert "Do not return intent-to-work text" in calls[0]["messages"][0]["content"]


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
    assert "Observed output from local-default" in memory.written[0]["text"]
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


def test_a_failing_upstream_stage_blocks_dependent_work() -> None:
    def flaky(call, messages):
        if call["model"] == "claude-cli":
            raise RuntimeError("rate limited")
        return {"model": call["model"], "content": "Observed recovery with concrete test output and a referenced path.", "usage": {}}

    with pytest.raises(RuntimeError, match="every stage failed"):
        execute_graph(_graph(with_memory=False), _snapshot(), {"goal": "x"}, completion=flaky)


def test_graph_retries_and_rejects_intent_only_stage_output() -> None:
    calls = []

    def intent_only(call, messages):
        calls.append(call)
        return {"model": call["model"], "content": "I will inspect this and report back.", "usage": {}}

    with pytest.raises(RuntimeError, match="every stage failed"):
        execute_graph(_graph(with_memory=False), _snapshot(), {"goal": "x"}, completion=intent_only)
    assert len(calls) == 2


def test_graph_does_not_return_an_earlier_stage_when_output_path_fails() -> None:
    attempts = {"claude-cli": 0, "local-default": 0}
    graph = _graph(with_memory=False)
    graph["nodes"].append({"id": "out", "type": "output", "data": {"label": "Output"}})
    graph["edges"].append({"id": "e-out", "from": "w1", "to": "out", "kind": "data"})

    def partial(call, messages):
        attempts[call["model"]] += 1
        if call["model"] == "claude-cli":
            return {
                "model": call["model"],
                "content": "Observed repository evidence in src/example.py. The check ran successfully and produced a reproducible result for downstream review.",
                "usage": {},
            }
        return {"model": call["model"], "content": "I will implement this after reviewing it.", "usage": {}}

    with pytest.raises(RuntimeError, match="workflow output stage failed"):
        execute_graph(graph, _snapshot(), {"goal": "x"}, completion=partial)
    assert attempts["local-default"] == 2


def test_graph_passes_workspace_write_only_for_opted_in_stage() -> None:
    graph = _graph(with_memory=False)
    graph["nodes"][1]["data"]["workspace_write"] = False
    graph["nodes"][2]["data"]["workspace_write"] = True
    calls = []
    execute_graph(
        graph,
        _snapshot(),
        {"goal": "build", "_workspace_write_authorized": True},
        completion=_completion(calls),
    )
    assert calls[0]["workspace_write"] is False
    assert calls[1]["workspace_write"] is True


def test_graph_rejects_unauthorized_workspace_write() -> None:
    graph = _graph(with_memory=False)
    graph["nodes"][1]["data"]["workspace_write"] = True
    with pytest.raises(PermissionError, match="trusted local authorization"):
        execute_graph(graph, _snapshot(), {"goal": "build"}, completion=_completion([]))


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


def _snapshot_multi() -> dict:
    return {
        "models": {
            name: {
                "available": True,
                "tier": "cloud",
                "provider": name,
                "capabilities": ["chat", "code"],
            }
            for name in ("model-a", "model-b", "model-c")
        }
    }


def _parallel_graph() -> dict:
    return {
        "id": "test-parallel",
        "title": "Parallel",
        "nodes": [
            {"id": "g1", "type": "goal", "data": {"text": "survey the options"}},
            {"id": "p1", "type": "worker", "data": {"label": "Fan out", "parallel": 3}},
        ],
        "edges": [{"id": "e1", "from": "g1", "to": "p1"}],
    }


def test_parallel_node_fans_out_to_distinct_models_and_combines_output() -> None:
    calls = []
    result = execute_graph(
        _parallel_graph(),
        _snapshot_multi(),
        {"goal": "survey the options"},
        completion=_completion(calls),
    )
    assert result["ok"] is True
    used_models = {c["model"] for c in calls}
    assert len(used_models) == 3, "each parallel branch should use a distinct model"
    for model in used_models:
        assert f"[{model}]" in result["answer"]
    assert result["steps"][0]["models"] and len(result["steps"][0]["models"]) == 3


def test_parallel_node_combines_whatever_branches_succeed() -> None:
    def flaky(call, messages):
        if call["model"] == "model-b":
            raise RuntimeError("no capacity")
        return {
            "model": call["model"],
            "content": f"Observed output from {call['model']}: repository path src/example.py was checked and verification passed with a reproducible test command.",
            "usage": {"total_tokens": 5},
        }

    result = execute_graph(
        _parallel_graph(),
        _snapshot_multi(),
        {"goal": "survey the options"},
        completion=flaky,
    )
    assert result["ok"] is True
    assert "[model-b]" not in result["answer"]
    assert result["steps"][0]["degraded"] is True


def test_cancel_check_stops_a_run_before_it_starts_the_next_stage() -> None:
    calls = []
    cancelled_after_first = {"n": 0}

    def cancel_check() -> bool:
        cancelled_after_first["n"] += 1
        # cancel_check() is consulted before each stage (and once before memory
        # read); this returns False for the first two checks so stage 0 runs,
        # then True so stage 1 never starts.
        return cancelled_after_first["n"] > 2

    with pytest.raises(Exception, match="cancelled"):
        execute_graph(
            _graph(with_memory=False),
            _snapshot(),
            {"goal": "build the thing"},
            completion=_completion(calls),
            cancel_check=cancel_check,
        )
    # the first stage was allowed to run; the second was cut off by cancellation
    assert len(calls) == 1


def test_node_script_can_skip_a_stage() -> None:
    calls = []
    graph = _graph(with_memory=False)
    graph["nodes"][2]["data"]["script"] = "rules:\n  - if: true\n    then: { skip: true }\n"
    result = execute_graph(graph, _snapshot(), {"goal": "build the thing"}, completion=_completion(calls))
    assert result["ok"] is True
    assert [c["model"] for c in calls] == ["claude-cli"]
    skipped = [s for s in result["steps"] if s.get("stage_id") == "w1"]
    assert skipped and skipped[0].get("skipped") is True


def test_node_script_can_override_the_model() -> None:
    calls = []
    graph = _graph(with_memory=False)
    graph["nodes"][2]["data"]["script"] = (
        'rules:\n  - if: contains(upstream, "claude-cli")\n    then: { set_model: local-default }\n'
    )
    result = execute_graph(graph, _snapshot(), {"goal": "build the thing"}, completion=_completion(calls))
    assert result["ok"] is True
    assert calls[1]["model"] == "local-default"


def test_node_script_can_append_a_note_to_the_prompt() -> None:
    calls = []
    graph = _graph(with_memory=False)
    graph["nodes"][2]["data"]["script"] = 'rules:\n  - if: true\n    then: { note: "be extra terse" }\n'
    execute_graph(graph, _snapshot(), {"goal": "build the thing"}, completion=_completion(calls))
    assert any("be extra terse" in m.get("content", "") for m in calls[1]["messages"])


def test_a_broken_node_script_fails_only_its_own_stage() -> None:
    calls = []
    graph = _graph(with_memory=False)
    graph["nodes"][2]["data"]["script"] = "rules: not-a-list"
    result = execute_graph(graph, _snapshot(), {"goal": "build the thing"}, completion=_completion(calls))
    # the master stage still ran and produced the answer; only the worker stage,
    # whose script is broken, is marked with a script error
    assert result["ok"] is True
    worker_step = next(s for s in result["steps"] if s.get("stage_id") == "w1")
    assert "script error" in (worker_step.get("error") or "")


def test_gdpr_mode_blocks_a_graph_stage_from_resolving_to_a_cloud_model() -> None:
    gdpr.set_settings({"enabled": True, "require_cloud_consent": True})
    calls = []
    result = execute_graph(
        _graph(with_memory=False),
        _snapshot(),
        {"goal": "build the thing"},
        completion=_completion(calls),
        session_id="gdpr-graph-test",
    )
    # The master stage is pinned to claude-cli (subscription/cloud), but with
    # consent missing _pick_for_stage's own fallback scoring picks the next
    # best *available* candidate - local-default is still in `needs`' overlap
    # (chat) even though it lacks "reason" - so the run still completes, just
    # without ever calling the blocked cloud model.
    assert result["ok"] is True
    models_called = {c["model"] for c in calls}
    assert "claude-cli" not in models_called
    assert models_called == {"local-default"}


def test_gdpr_mode_allows_the_cloud_model_once_consent_is_recorded() -> None:
    gdpr.set_settings({"enabled": True, "require_cloud_consent": True})
    gdpr.record_consent("gdpr-graph-test")
    calls = []
    result = execute_graph(
        _graph(with_memory=False),
        _snapshot(),
        {"goal": "build the thing"},
        completion=_completion(calls),
        session_id="gdpr-graph-test",
    )
    assert result["ok"] is True
    assert "claude-cli" in [c["model"] for c in calls]


def test_node_script_set_model_is_rejected_when_gdpr_blocks_the_target() -> None:
    gdpr.set_settings({"enabled": True, "require_cloud_consent": True})
    graph = _graph(with_memory=False)
    # Master resolves locally so the worker actually gets to run; only the
    # worker's script tries (and should fail) to force a blocked cloud model.
    graph["nodes"][1]["data"]["model"] = "local-default"
    graph["nodes"][2]["data"]["script"] = 'rules:\n  - if: true\n    then: { set_model: claude-cli }\n'
    result = execute_graph(
        graph,
        _snapshot(),
        {"goal": "build the thing"},
        completion=_completion([]),
        session_id="gdpr-graph-test-2",
    )
    worker_step = next(s for s in result["steps"] if s.get("stage_id") == "w1")
    assert "not an available model" in (worker_step.get("error") or "")


def test_memory_node_writes_get_an_expiring_ttl_and_session_id_tag_under_gdpr_mode() -> None:
    gdpr.set_settings({"enabled": True, "retention_days": 14})
    memory = FakeMemory()
    execute_graph(
        _graph(with_memory=True),
        _snapshot(),
        {"goal": "build the thing"},
        completion=_completion([]),
        memory=memory,
        session_id="gdpr-retention-test",
    )
    assert memory.written, "expected the Memory store node to write"
    write = memory.written[0]
    assert write["ttl_seconds"] == 14 * 86400
    assert write["meta"]["session_id"] == "gdpr-retention-test"


def test_memory_node_writes_have_no_ttl_when_gdpr_mode_is_off() -> None:
    memory = FakeMemory()
    execute_graph(
        _graph(with_memory=True),
        _snapshot(),
        {"goal": "build the thing"},
        completion=_completion([]),
        memory=memory,
        session_id="normal-test",
    )
    assert memory.written and memory.written[0]["ttl_seconds"] is None
