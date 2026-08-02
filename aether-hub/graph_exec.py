#!/usr/bin/env python3
"""
Run a node graph: the execution half of the canvas.

`graph.py` compiles a graph into an `aetherstack.pipeline.v1` descriptor with
resolved `memory_ops`. Until this module existed, nothing consumed either — the
canvas could draw and plan a tree but never run one, and its Memory nodes were
inert descriptors. This executes the compiled stages in topological order,
threads each stage's output into its downstream stages, and performs the
memory reads and writes the Memory nodes asked for.

The memory pool is the same one Auto mode uses (`MemoryStore`), so a tree can
pick up work an Auto session started and vice versa.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from graph import graph_to_pipeline
from memory import MemoryStore
from pipelines import _pick_for_stage
from services import _chat_completion, worker_output_needs_correction

MAX_STAGE_OUTPUT_CHARS = 20_000
MAX_CONTEXT_CHARS = 12_000
MAX_STAGES = 40


class GraphExecutionError(RuntimeError):
    """A failed workflow with node-level diagnostics safe to return to the UI."""

    def __init__(self, message: str, steps: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.steps = steps


def _emit(on_status: Callable[[dict[str, Any]], None] | None, phase: str, **fields: Any) -> None:
    if on_status is None:
        return
    try:
        on_status({"phase": phase, **fields})
    except Exception:
        pass


def _memory_reads(
    memory: MemoryStore | None,
    memory_ops: list[dict[str, Any]],
    goal: str,
) -> str:
    """Run every `search` Memory node and return their hits as one context block."""
    if memory is None or not goal:
        return ""
    chunks: list[str] = []
    used = 0
    for op in memory_ops:
        if op.get("action") != "search":
            continue
        try:
            found = memory.search(goal, namespace=op.get("namespace") or "default", top_k=5)
        except Exception:
            continue
        lines = [
            str(hit.get("text") or "").strip()
            for hit in (found.get("hits") or [])
            if str(hit.get("text") or "").strip()
        ]
        if not lines:
            continue
        block = f"### {op.get('label') or 'Memory'} ({op.get('scope')})\n" + "\n".join(lines)
        block = block[: MAX_CONTEXT_CHARS - used]
        if not block.strip():
            break
        chunks.append(block)
        used += len(block)
        if used >= MAX_CONTEXT_CHARS:
            break
    return "\n\n".join(chunks)


def _memory_writes(
    memory: MemoryStore | None,
    memory_ops: list[dict[str, Any]],
    goal: str,
    answer: str,
) -> list[dict[str, Any]]:
    """Run every `store` Memory node against the shared pool."""
    if memory is None or not answer:
        return []
    written: list[dict[str, Any]] = []
    for op in memory_ops:
        if op.get("action") != "store":
            continue
        try:
            result = memory.upsert_vector(
                f"Goal: {goal}\n\n{answer}"[:MAX_STAGE_OUTPUT_CHARS],
                namespace=op.get("namespace") or "default",
                meta={"source": "graph", "scope": op.get("scope"), "node_id": op.get("node_id")},
            )
            written.append({"node_id": op.get("node_id"), **result})
        except Exception as exc:  # a full pool must not lose the answer
            written.append({"node_id": op.get("node_id"), "error": str(exc)[:200]})
    return written


def _stage_messages(
    stage: dict[str, Any],
    goal: str,
    context: str,
    upstream: str,
) -> list[dict[str, Any]]:
    behavior = str(stage.get("behavior_markdown") or "").strip()
    system = behavior or (
        f"You are the {stage.get('role') or 'worker'} stage of a multi-model pipeline. "
        f"{stage.get('purpose') or ''} Answer only your part of the task, concretely."
    )
    role = str(stage.get("role") or "worker").lower()
    quality = (
        "Complete this stage now. Do not return intent-to-work text. Ground material claims in file paths, symbols, "
        "commands and observed output, source links, or clearly labelled assumptions. Preserve useful upstream evidence "
        "and identify any contradiction you find."
    )
    if role in {"critic", "reviewer", "analyser", "supervisor"}:
        quality += (
            " Be skeptical: identify unsupported claims, weak decisions, regressions, and missing verification; rank them "
            "and provide exact corrections for the next stage."
        )
    system = f"{system}\n\n{quality}"
    user = [f"Goal:\n{goal}"]
    if context:
        user.append(f"Relevant prior work from shared memory:\n{context}")
    if upstream:
        user.append(f"Output of the previous stage(s):\n{upstream}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user)},
    ]


def execute_graph(
    graph: dict[str, Any],
    snapshot: dict[str, Any],
    event: dict[str, Any] | None = None,
    completion: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]] | None = None,
    memory: MemoryStore | None = None,
    session_id: str | None = None,
    on_status: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute a node graph stage by stage against the shared memory pool."""
    event = dict(event or {})
    pipe = graph_to_pipeline(graph)
    goal = str(event.get("goal") or event.get("prompt") or pipe.get("goal_default") or "").strip()
    if not goal:
        raise ValueError("goal is required")
    if len(goal) > 100_000:
        raise ValueError("goal exceeds 100000 characters")

    stages = [s for s in (pipe.get("stages") or []) if not s.get("pass_through")]
    if not stages:
        raise ValueError("graph has no runnable stages")
    if len(stages) > MAX_STAGES:
        raise ValueError(f"graph has {len(stages)} stages; limit is {MAX_STAGES}")
    if any(stage.get("workspace_write") for stage in stages) and not event.get("_workspace_write_authorized"):
        raise PermissionError("workspace-write execution requires trusted local authorization")

    memory_ops = pipe.get("memory_ops") or []
    completion = completion or _chat_completion
    started = time.time()

    _emit(on_status, "memory_read", label="Reading shared memory…")
    context = _memory_reads(memory, memory_ops, goal)

    outputs: dict[str, str] = {}
    steps: list[dict[str, Any]] = []
    usage_items: list[dict[str, Any]] = []
    stage_ids = {str(stage.get("id")) for stage in stages if stage.get("id")}

    for index, stage in enumerate(stages):
        resolved = _pick_for_stage(snapshot, stage)
        model = resolved.get("model")
        label = stage.get("label") or stage.get("role") or stage.get("id")
        if not model or not resolved.get("available", True):
            steps.append(
                {
                    "stage_id": stage.get("id"),
                    "label": label,
                    "role": stage.get("role"),
                    "model": model,
                    "error": "no available model for this stage",
                }
            )
            continue
        required_stage_inputs = [
            source for source in (stage.get("inputs_from") or []) if source in stage_ids
        ]
        if required_stage_inputs and not any(source in outputs for source in required_stage_inputs):
            steps.append(
                {
                    "stage_id": stage.get("id"),
                    "label": label,
                    "role": stage.get("role"),
                    "model": model,
                    "error": "no successful upstream stage output",
                }
            )
            continue
        _emit(
            on_status,
            "stage",
            model=model,
            label=f"{label} · {model}",
            index=index,
            total=len(stages),
        )
        upstream = "\n\n".join(
            f"[{outputs_id}]\n{outputs[outputs_id]}"
            for outputs_id in (stage.get("inputs_from") or [])
            if outputs_id in outputs
        )[-MAX_STAGE_OUTPUT_CHARS:]
        messages = _stage_messages(stage, goal, context, upstream)
        call = {
            "model": model,
            "max_tokens": int(event.get("max_tokens") or 2000),
            "role": stage.get("role") or "worker",
            "workspace_write": bool(stage.get("workspace_write")),
        }
        try:
            result = completion(call, messages)
            first_usage = result.get("usage") or {}
            if worker_output_needs_correction(result.get("content")):
                retry_messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "The stage response was intent-only or unsupported. Perform the bounded work now and replace "
                            "it with concrete evidence-backed findings. If this is an implementation stage, make the "
                            "allowed workspace edits and report changed paths plus verification output."
                        ),
                    },
                ]
                result = completion(call, retry_messages)
                retry_usage = result.get("usage") or {}
                result["usage"] = {
                    key: int(first_usage.get(key) or 0) + int(retry_usage.get(key) or 0)
                    for key in set(first_usage) | set(retry_usage)
                }
                if worker_output_needs_correction(result.get("content")):
                    raise RuntimeError("stage output rejected after two intent-only or unsupported responses")
            text = str(result.get("content") or "").strip()
            outputs[stage.get("id")] = text[:MAX_STAGE_OUTPUT_CHARS]
            usage_items.append(result.get("usage") or {})
            steps.append(
                {
                    "stage_id": stage.get("id"),
                    "label": label,
                    "role": stage.get("role"),
                    "model": model,
                    "content": text,
                }
            )
        except Exception as exc:
            steps.append(
                {
                    "stage_id": stage.get("id"),
                    "label": label,
                    "role": stage.get("role"),
                    "model": model,
                    "error": str(exc)[:500],
                }
            )

    answered = [step for step in steps if step.get("content")]
    if not answered:
        raise GraphExecutionError("every stage failed; see steps for detail", steps)
    node_types = {str(node.get("id")): node.get("type") for node in (graph.get("nodes") or []) if node.get("id")}
    output_sources = {
        str(edge.get("from"))
        for edge in (graph.get("edges") or [])
        if edge.get("kind", "data") == "data" and node_types.get(str(edge.get("to"))) == "output"
    }
    if output_sources:
        terminal_answers = [step for step in answered if str(step.get("stage_id")) in output_sources]
        if not terminal_answers:
            raise GraphExecutionError("workflow output stage failed; see steps for detail", steps)
        answer_step = terminal_answers[-1]
    else:
        answer_step = answered[-1]
    answer = answer_step["content"]

    _emit(on_status, "memory_write", label="Writing shared memory…")
    written = _memory_writes(memory, memory_ops, goal, answer)
    if memory is not None and session_id:
        # Same pool Auto mode reads, so a later model resumes this work.
        try:
            memory.append_message(session_id, "user", goal, meta={"graph": pipe.get("id")})
            memory.append_message(
                session_id,
                "assistant",
                answer,
                meta={"graph": pipe.get("id"), "model": answer_step.get("model")},
            )
        except Exception:
            pass

    usage = {
        key: sum(int(item.get(key) or 0) for item in usage_items)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    return {
        "ok": True,
        "graph_id": graph.get("id"),
        "pipeline_id": pipe.get("id"),
        "goal": goal,
        "answer": answer,
        "model": answer_step.get("model"),
        "steps": steps,
        "stage_count": len(stages),
        "memory_context_chars": len(context),
        "memory_written": written,
        "usage": usage,
        "elapsed_ms": int((time.time() - started) * 1000),
    }
