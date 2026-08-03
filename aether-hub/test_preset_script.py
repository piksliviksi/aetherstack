#!/usr/bin/env python3
"""Preset scripts: YAML -> real node graph -> execute_graph, and the reverse export."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from graph_exec import execute_graph  # noqa: E402
from preset_script import PresetScriptError, graph_to_preset_script, preset_script_to_graph  # noqa: E402


SCRIPT = """
title: Backend + Frontend build
goal: Ship the login page
master:
  model: claude-cli
  prompt: Plan the work and delegate to workers.
workers:
  - label: Backend
    model: local-default
    prompt: Implement the backend change.
  - label: Frontend
    model: local-default
    prompt: Implement the UI change.
audit:
  model: claude-cli
  prompt: Check the work for correctness.
tester:
  model: local-default
  prompt: Run and verify the tests.
"""


def _snapshot() -> dict:
    return {
        "models": {
            "claude-cli": {"available": True, "executor": "host_cli", "tier": "subscription", "capabilities": ["chat", "code", "reason"]},
            "local-default": {"available": True, "tier": "local", "provider": "ollama", "capabilities": ["chat", "code"]},
        }
    }


def _completion(calls):
    def run(call, messages):
        calls.append({"model": call["model"], "role": call.get("role")})
        return {
            "model": call["model"],
            "content": f"Observed output from {call['model']}: repository path src/example.py was checked and verification passed with a reproducible test command.",
            "usage": {"total_tokens": 4},
        }

    return run


def test_script_builds_the_expected_node_shape() -> None:
    graph = preset_script_to_graph(SCRIPT)
    types = [n["type"] for n in graph["nodes"]]
    assert types == ["goal", "master", "worker", "worker", "analyser", "tester", "output"]
    workers = [n for n in graph["nodes"] if n["type"] == "worker"]
    assert [w["data"]["label"] for w in workers] == ["Backend", "Frontend"]
    assert graph["nodes"][1]["data"]["instructions_md"] == "Plan the work and delegate to workers."


def test_script_fans_out_master_to_every_worker_and_into_audit() -> None:
    graph = preset_script_to_graph(SCRIPT)
    master = next(n for n in graph["nodes"] if n["type"] == "master")
    workers = [n for n in graph["nodes"] if n["type"] == "worker"]
    audit = next(n for n in graph["nodes"] if n["type"] == "analyser")
    edges = graph["edges"]
    for worker in workers:
        assert {"from": master["id"], "to": worker["id"]} in [{"from": e["from"], "to": e["to"]} for e in edges]
        assert {"from": worker["id"], "to": audit["id"]} in [{"from": e["from"], "to": e["to"]} for e in edges]


def test_scripted_preset_actually_runs() -> None:
    calls = []
    graph = preset_script_to_graph(SCRIPT)
    result = execute_graph(graph, _snapshot(), {"goal": "override goal"}, completion=_completion(calls))
    assert result["ok"] is True
    models_called = {c["model"] for c in calls}
    assert models_called == {"claude-cli", "local-default"}
    # master, 2 workers, audit, tester = 5 calls
    assert len(calls) == 5


def test_a_master_with_no_workers_gets_a_default_one() -> None:
    graph = preset_script_to_graph("title: Solo\nmaster:\n  prompt: Do it all.\n")
    assert [n["type"] for n in graph["nodes"]].count("worker") == 1


def test_parallel_entry_becomes_a_parallel_node() -> None:
    script = "title: Survey\nparallel:\n  - label: Survey\n    branches: 4\n    prompt: Investigate.\n"
    graph = preset_script_to_graph(script)
    parallel_node = next(n for n in graph["nodes"] if n["type"] == "parallel")
    assert parallel_node["data"]["parallel"] == 4


def test_export_round_trips_the_shape() -> None:
    graph = preset_script_to_graph(SCRIPT)
    exported = graph_to_preset_script(graph)
    reimported = preset_script_to_graph(exported)
    assert [n["type"] for n in reimported["nodes"]] == [n["type"] for n in graph["nodes"]]
    workers = [n["data"]["label"] for n in reimported["nodes"] if n["type"] == "worker"]
    assert workers == ["Backend", "Frontend"]


def test_empty_script_is_rejected() -> None:
    with pytest.raises(PresetScriptError, match="empty"):
        preset_script_to_graph("")


def test_malformed_yaml_is_a_script_error() -> None:
    with pytest.raises(PresetScriptError, match="invalid preset script YAML"):
        preset_script_to_graph("title: [unterminated")


def test_workers_must_be_a_list() -> None:
    with pytest.raises(PresetScriptError, match="'workers' must be a list"):
        preset_script_to_graph("workers: not-a-list\n")


def test_too_many_branches_is_rejected() -> None:
    workers = "\n".join(f"  - label: W{i}\n    prompt: x" for i in range(20))
    with pytest.raises(PresetScriptError, match="more than"):
        preset_script_to_graph(f"workers:\n{workers}\n")


def test_a_non_numeric_branches_value_raises_a_clean_script_error_not_a_bare_exception() -> None:
    # Previously this raised a bare ValueError, which server.py's route only
    # catches PresetScriptError for - the connection would drop with no
    # response at all instead of a 400.
    script = "parallel:\n  - label: Survey\n    branches: three\n    prompt: go\n"
    with pytest.raises(PresetScriptError, match="branches"):
        preset_script_to_graph(script)


def test_a_non_numeric_worker_parallel_value_raises_a_clean_script_error() -> None:
    script = "workers:\n  - label: W\n    parallel: not-a-number\n    prompt: go\n"
    with pytest.raises(PresetScriptError, match="parallel"):
        preset_script_to_graph(script)


def test_branches_above_the_execution_cap_is_clamped_not_silently_wrong() -> None:
    script = "parallel:\n  - label: Survey\n    branches: 40\n    prompt: go\n"
    graph = preset_script_to_graph(script)
    node = next(n for n in graph["nodes"] if n["type"] == "parallel")
    # graph_exec.py only ever runs MAX_PARALLEL_BRANCHES (8) branches - what's
    # saved/shown must match what will actually execute.
    assert node["data"]["parallel"] == 8


def test_worker_parallel_round_trips_through_export_and_reimport() -> None:
    script = "workers:\n  - label: Fan\n    parallel: 4\n    prompt: go\n"
    graph = preset_script_to_graph(script)
    exported = graph_to_preset_script(graph)
    reimported = preset_script_to_graph(exported)
    worker = next(n for n in reimported["nodes"] if n["type"] == "worker")
    assert worker["data"]["parallel"] == 4
