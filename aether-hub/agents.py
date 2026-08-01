"""
Agent modes: inline vs multi-agent, optional token saver,
role assignment (mastermind / supervisor / worker) by price, tier, maker, or model.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from matrix import route as matrix_route
from matrix import tiers_match

ROOT = Path(__file__).resolve().parent
MODES_PATH = Path(os.environ.get("AETHER_AGENT_MODES_PATH", str(ROOT / "agent_modes.yaml")))

# In-process runtime state (also mirrored to Redis by server when possible)
_runtime: dict[str, Any] = {
    "mode": "inline",
    "token_saver": False,
    "lean_mode": "off",
    "service": None,
    "role_overrides": {},  # role -> {model, maker, tier, strategy, max_cost}
    "preset": None,
    "updated_at": None,
}


def load_modes_config(path: Path | None = None) -> dict[str, Any]:
    p = path or MODES_PATH
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("invalid agent_modes.yaml")
    return data


def get_runtime() -> dict[str, Any]:
    return copy.deepcopy(_runtime)


def apply_runtime_update(patch: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Update mode / token_saver / role pins / preset."""
    global _runtime
    cfg = cfg or load_modes_config()
    if "preset" in patch and patch["preset"]:
        name = str(patch["preset"])
        presets = cfg.get("presets") or {}
        if name not in presets:
            raise ValueError(f"unknown preset: {name}. known={list(presets)}")
        _apply_preset(presets[name], name)
    if "mode" in patch and patch["mode"] is not None:
        mode = str(patch["mode"]).lower().replace("-", "_")
        if mode in ("multi", "multiagent", "agents"):
            mode = "multi_agent"
        if mode not in ("inline", "multi_agent"):
            raise ValueError("mode must be inline or multi_agent")
        _runtime["mode"] = mode
    if "token_saver" in patch and patch["token_saver"] is not None:
        _runtime["token_saver"] = bool(patch["token_saver"])
    if "lean_mode" in patch and patch["lean_mode"] is not None:
        lean_mode = str(patch["lean_mode"]).lower().replace("-", "_")
        if lean_mode not in ("off", "balanced", "strict"):
            raise ValueError("lean_mode must be off, balanced, or strict")
        _runtime["lean_mode"] = lean_mode
    if "service" in patch:
        _runtime["service"] = str(patch["service"])[:80] if patch["service"] else None
    if "role_overrides" in patch and isinstance(patch["role_overrides"], dict):
        for role, ov in patch["role_overrides"].items():
            if not isinstance(ov, dict):
                continue
            cur = _runtime["role_overrides"].setdefault(role, {})
            for k in ("model", "maker", "tier", "strategy", "max_cost", "prefer"):
                if k in ov:
                    cur[k] = ov[k]
    if patch.get("clear_overrides"):
        _runtime["role_overrides"] = {}
    _runtime["updated_at"] = time.time()
    return get_runtime()


def _apply_preset(preset: dict[str, Any], name: str) -> None:
    _runtime["preset"] = name
    if "mode" in preset:
        _runtime["mode"] = preset["mode"]
    if "token_saver" in preset:
        _runtime["token_saver"] = bool(preset["token_saver"])
    roles = preset.get("roles") or {}
    for role, body in roles.items():
        sel = (body or {}).get("select") or body or {}
        _runtime["role_overrides"][role] = {
            k: sel.get(k)
            for k in ("model", "maker", "tier", "strategy", "max_cost", "prefer")
            if sel.get(k) is not None
        }


def init_runtime_from_config(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_modes_config()
    d = cfg.get("defaults") or {}
    _runtime["mode"] = d.get("mode") or "inline"
    _runtime["token_saver"] = bool(d.get("token_saver", False))
    _runtime["lean_mode"] = str(d.get("lean_mode") or "off")
    _runtime["service"] = None
    _runtime["role_overrides"] = {}
    _runtime["preset"] = None
    _runtime["updated_at"] = time.time()
    return get_runtime()


def cost_rank(cost: Any, cfg: dict[str, Any]) -> int:
    ranks = cfg.get("cost_rank") or {}
    if cost in ranks:
        return int(ranks[cost])
    return int(ranks.get(str(cost), 2))


def _model_matches_filters(name: str, meta: dict[str, Any], sel: dict[str, Any]) -> bool:
    if sel.get("model"):
        want = str(sel["model"]).strip()
        if name != want and meta.get("backend") != want:
            return False
    if sel.get("maker"):
        if str(meta.get("provider") or "").lower() != str(sel["maker"]).lower():
            return False
    if sel.get("tier"):
        # host_cli / subscription are aliases for authenticated host CLI seats
        if not tiers_match(meta, sel["tier"]):
            return False
    return True


def pick_model_for_role(
    snapshot: dict[str, Any],
    role: str,
    cfg: dict[str, Any] | None = None,
    need_override: list[str] | None = None,
) -> dict[str, Any]:
    """Pick a model for mastermind | supervisor | worker | inline."""
    cfg = cfg or load_modes_config()
    roles = cfg.get("roles") or {}
    role_cfg = copy.deepcopy(roles.get(role) or roles.get("inline") or {})
    # Merge runtime overrides
    ov = (_runtime.get("role_overrides") or {}).get(role) or {}
    sel = dict(role_cfg.get("select") or {})
    sel.update({k: v for k, v in ov.items() if v is not None})
    prefer = ov.get("prefer") or role_cfg.get("prefer") or "auto"
    needs = need_override or list(role_cfg.get("needs") or ["chat"])

    # Token saver biases workers toward cheap/local
    if _runtime.get("token_saver"):
        ts = cfg.get("token_saver") or {}
        if role == "worker" or role == "inline":
            if ts.get("prefer_local"):
                prefer = "local"
            if ts.get("prefer_cheap") and "cheap" not in needs:
                needs = list(needs) + ["cheap"]
            if ts.get("route_need") and role == "inline":
                needs = list(ts["route_need"])

    models: dict[str, Any] = snapshot.get("models") or {}
    strategy = (sel.get("strategy") or "best_score").lower()

    # Hard pin by model name
    if sel.get("model"):
        mname = str(sel["model"])
        meta = models.get(mname)
        if meta and meta.get("available"):
            return _pick_result(role, mname, meta, strategy, "pinned_model", needs, prefer)
        return {
            "role": role,
            "model": mname,
            "available": False,
            "error": f"pinned model {mname!r} unavailable",
            "needs": needs,
        }

    candidates: list[tuple[float, str, dict]] = []
    max_cost = sel.get("max_cost")
    max_r = cost_rank(max_cost, cfg) if max_cost is not None else 99

    for name, meta in models.items():
        if not meta.get("available"):
            continue
        if not _model_matches_filters(name, meta, sel):
            continue
        if cost_rank(meta.get("cost", "medium"), cfg) > max_r:
            continue
        # capability soft filter
        caps = set(meta.get("capabilities") or [])
        need_set = set(needs)
        if need_set and not (need_set & caps) and strategy != "by_model":
            continue
        score = 0.0
        if strategy == "cheapest":
            score = 100.0 - 20.0 * cost_rank(meta.get("cost", "medium"), cfg)
            if meta.get("tier") == "local":
                score += 15
        elif strategy == "by_maker":
            score = 50.0
        elif strategy == "by_tier":
            score = 50.0
        else:  # best_score — reuse matrix route ranking light
            from matrix import _score_model

            score = _score_model(meta, need_set, prefer)
        candidates.append((score, name, meta))

    candidates.sort(key=lambda x: x[0], reverse=True)
    if not candidates:
        # Fallback to matrix route
        r = matrix_route(snapshot, need=needs, prefer=prefer)
        primary = r.get("primary") or {}
        return {
            "role": role,
            "model": primary.get("model"),
            "available": bool(primary.get("available", True) and primary.get("model")),
            "tier": primary.get("tier"),
            "provider": (models.get(primary.get("model") or "") or {}).get("provider"),
            "strategy": strategy,
            "selection": "matrix_fallback",
            "needs": needs,
            "prefer": prefer,
            "hint": r.get("hint"),
            "offline_plan": r.get("offline_plan"),
        }

    score, name, meta = candidates[0]
    return _pick_result(role, name, meta, strategy, "selected", needs, prefer, score)


def _pick_result(
    role: str,
    name: str,
    meta: dict,
    strategy: str,
    selection: str,
    needs: list,
    prefer: str,
    score: float | None = None,
) -> dict[str, Any]:
    return {
        "role": role,
        "model": name,
        "available": True,
        "tier": meta.get("tier"),
        "provider": meta.get("provider"),
        "backend": meta.get("backend"),
        "cost": meta.get("cost"),
        "latency": meta.get("latency"),
        "capabilities": meta.get("capabilities"),
        "strategy": strategy,
        "selection": selection,
        "needs": needs,
        "prefer": prefer,
        "score": score,
    }


def token_saver_apply(text: str, role: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Optional compression / caps when token_saver is on."""
    cfg = cfg or load_modes_config()
    if not _runtime.get("token_saver"):
        return {
            "enabled": False,
            "text": text,
            "max_tokens": None,
            "original_chars": len(text or ""),
            "final_chars": len(text or ""),
        }
    ts = cfg.get("token_saver") or {}
    original = text or ""
    out = original
    if ts.get("compress_input") and len(out) > (
        int(ts.get("compress_keep_head") or 2000) + int(ts.get("compress_keep_tail") or 1000) + 64
    ):
        head = int(ts.get("compress_keep_head") or 2000)
        tail = int(ts.get("compress_keep_tail") or 1000)
        out = (
            out[:head]
            + f"\n\n…[token_saver truncated {len(original) - head - tail} chars]…\n\n"
            + out[-tail:]
        )
    role_caps = (ts.get("max_prompt_chars") or {}).get(role)
    if role_caps and len(out) > int(role_caps):
        out = out[: int(role_caps)] + "\n…[token_saver max_prompt_chars]"
    max_tok = (ts.get("max_tokens") or {}).get(role)
    return {
        "enabled": True,
        "text": out,
        "max_tokens": max_tok,
        "original_chars": len(original),
        "final_chars": len(out),
        "saved_chars": max(0, len(original) - len(out)),
    }


def lean_delivery_policy(mode: str | None) -> str:
    """Safe minimal-delivery policy inspired by Ponytail's YAGNI ladder."""
    normalized = str(mode or "off").lower()
    if normalized == "off":
        return ""
    common = (
        "Deliver only what the task requires. Reuse existing project code and platform primitives before adding abstractions, "
        "dependencies, files, or configuration. Do not add speculative features or explanatory padding. "
        "Never remove validation, error handling, security controls, accessibility, tests, or required observability to be shorter."
    )
    if normalized == "strict":
        return common + " Prefer the smallest readable patch and the shortest complete answer; justify every new layer."
    return common + " Keep the result concise, readable, and maintainable."


def plan_event(
    snapshot: dict[str, Any],
    event: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build an execution plan for one user event.

    event fields:
      goal / prompt: str
      mode: optional override inline|multi_agent
      token_saver: optional bool
      tasks: optional list[{id, description, need:[]}] for workers
      roles: optional {mastermind: {model|maker|tier|strategy}, ...}
      workers: optional int
    """
    cfg = cfg or load_modes_config()
    # Temporary overrides for this event only (do not mutate global unless requested)
    saved = get_runtime()
    try:
        if (
            event.get("mode") is not None
            or event.get("token_saver") is not None
            or event.get("lean_mode") is not None
            or event.get("service") is not None
            or event.get("roles")
        ):
            patch = {}
            if event.get("mode") is not None:
                patch["mode"] = event["mode"]
            if event.get("token_saver") is not None:
                patch["token_saver"] = event["token_saver"]
            if event.get("lean_mode") is not None:
                patch["lean_mode"] = event["lean_mode"]
            if event.get("service") is not None:
                patch["service"] = event["service"]
            if event.get("roles"):
                patch["role_overrides"] = event["roles"]
            apply_runtime_update(patch, cfg)

        mode = _runtime.get("mode") or "inline"
        saver_on = bool(_runtime.get("token_saver"))
        goal = event.get("goal") or event.get("prompt") or event.get("input") or ""
        service_instructions = str(event.get("service_instructions") or "")[:2000]
        lean_policy = lean_delivery_policy(_runtime.get("lean_mode"))
        policy_suffix = "\n\n".join(part for part in (service_instructions, lean_policy) if part)
        event_id = event.get("id") or str(uuid.uuid4())

        saver_goal = token_saver_apply(goal, "mastermind" if mode == "multi_agent" else "inline", cfg)

        if mode == "inline":
            pick = pick_model_for_role(snapshot, "inline", cfg)
            plan = {
                "event_id": event_id,
                "mode": "inline",
                "token_saver": saver_on,
                "goal": saver_goal,
                "agents": [
                    {
                        "agent_id": f"{event_id}-inline",
                        "role": "inline",
                        "model": pick.get("model"),
                        "provider": pick.get("provider"),
                        "tier": pick.get("tier"),
                        "available": pick.get("available"),
                        "task": "Handle entire event",
                        "input": saver_goal.get("text"),
                        "max_tokens": saver_goal.get("max_tokens"),
                        "selection": pick,
                    }
                ],
                "edges": [],
                "litellm_calls": [
                    {
                        "model": pick.get("model"),
                        "role": "inline",
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are the sole agent for this task."
                                + (f"\n\n{policy_suffix}" if policy_suffix else ""),
                            },
                            {"role": "user", "content": saver_goal.get("text")},
                        ],
                        "max_tokens": saver_goal.get("max_tokens"),
                    }
                ],
            }
            return plan

        # multi_agent
        master = pick_model_for_role(snapshot, "mastermind", cfg)
        super_ = pick_model_for_role(snapshot, "supervisor", cfg)
        worker_pick = pick_model_for_role(snapshot, "worker", cfg)

        role_cfg_w = (cfg.get("roles") or {}).get("worker") or {}
        n_workers = int(event.get("workers") or role_cfg_w.get("default_parallel") or 2)
        n_workers = max(1, min(n_workers, int(role_cfg_w.get("max_parallel") or 6)))

        tasks = event.get("tasks")
        if not tasks:
            # Auto-split into n generic worker tasks (mastermind would refine at runtime)
            tasks = [
                {
                    "id": f"t{i+1}",
                    "description": f"Subtask {i+1}/{n_workers} for: {saver_goal.get('text')[:200]}",
                    "need": ["chat", "code"] if "code" in (goal or "").lower() else ["chat"],
                }
                for i in range(n_workers)
            ]

        agents = []
        litellm_calls = []
        edges = []

        agents.append(
            {
                "agent_id": f"{event_id}-mastermind",
                "role": "mastermind",
                "model": master.get("model"),
                "provider": master.get("provider"),
                "tier": master.get("tier"),
                "available": master.get("available"),
                "task": "Orchestrate: plan, assign subtasks, synthesize final answer",
                "input": saver_goal.get("text"),
                "max_tokens": token_saver_apply("", "mastermind", cfg).get("max_tokens")
                if saver_on
                else (cfg.get("token_saver") or {}).get("max_tokens", {}).get("mastermind"),
                "selection": master,
            }
        )
        litellm_calls.append(
            {
                "model": master.get("model"),
                "role": "mastermind",
                "phase": "plan",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are the MASTERMIND orchestrator. Produce a short plan and "
                            "assign subtasks. Different worker models may execute them."
                            + (f"\n\n{policy_suffix}" if policy_suffix else "")
                        ),
                    },
                    {"role": "user", "content": saver_goal.get("text")},
                ],
                "max_tokens": agents[0].get("max_tokens"),
            }
        )

        for i, task in enumerate(tasks):
            # Allow per-task need / model pin
            t_need = task.get("need")
            task_pins = {
                k: task[k]
                for k in ("model", "maker", "tier", "strategy", "max_cost")
                if task.get(k) is not None
            }
            if task_pins:
                prev_worker = copy.deepcopy((_runtime.get("role_overrides") or {}).get("worker"))
                apply_runtime_update({"role_overrides": {"worker": task_pins}}, cfg)
                wp = pick_model_for_role(snapshot, "worker", cfg, need_override=t_need)
                if prev_worker:
                    apply_runtime_update({"role_overrides": {"worker": prev_worker}}, cfg)
                else:
                    _runtime.setdefault("role_overrides", {}).pop("worker", None)
            else:
                wp = (
                    pick_model_for_role(snapshot, "worker", cfg, need_override=t_need)
                    if t_need
                    else worker_pick
                )

            w_in = token_saver_apply(
                f"{task.get('description') or task}\n\nContext goal:\n{saver_goal.get('text')}",
                "worker",
                cfg,
            )
            aid = f"{event_id}-worker-{task.get('id') or i+1}"
            agents.append(
                {
                    "agent_id": aid,
                    "role": "worker",
                    "model": wp.get("model"),
                    "provider": wp.get("provider"),
                    "tier": wp.get("tier"),
                    "available": wp.get("available"),
                    "task": task.get("description") or str(task),
                    "task_id": task.get("id") or f"t{i+1}",
                    "input": w_in.get("text"),
                    "max_tokens": w_in.get("max_tokens"),
                    "selection": wp,
                }
            )
            edges.append({"from": f"{event_id}-mastermind", "to": aid, "kind": "assign"})
            litellm_calls.append(
                {
                    "model": wp.get("model"),
                    "role": "worker",
                    "phase": "work",
                    "task_id": task.get("id") or f"t{i+1}",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a WORKER agent. Do only your assigned subtask. Be concise."
                            + (f"\n\n{policy_suffix}" if policy_suffix else ""),
                        },
                        {"role": "user", "content": w_in.get("text")},
                    ],
                    "max_tokens": w_in.get("max_tokens"),
                }
            )
            edges.append({"from": aid, "to": f"{event_id}-supervisor", "kind": "submit"})

        s_in = token_saver_apply(
            f"Review worker outputs for goal:\n{saver_goal.get('text')}",
            "supervisor",
            cfg,
        )
        agents.append(
            {
                "agent_id": f"{event_id}-supervisor",
                "role": "supervisor",
                "model": super_.get("model"),
                "provider": super_.get("provider"),
                "tier": super_.get("tier"),
                "available": super_.get("available"),
                "task": "Supervise quality; request rework or approve synthesis",
                "input": s_in.get("text"),
                "max_tokens": s_in.get("max_tokens"),
                "selection": super_,
            }
        )
        edges.append({"from": f"{event_id}-supervisor", "to": f"{event_id}-mastermind", "kind": "report"})
        litellm_calls.append(
            {
                "model": super_.get("model"),
                "role": "supervisor",
                "phase": "review",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are the SUPERVISOR. Critique worker results; list issues or approve."
                        + (f"\n\n{policy_suffix}" if policy_suffix else ""),
                    },
                    {"role": "user", "content": s_in.get("text")},
                ],
                "max_tokens": s_in.get("max_tokens"),
            }
        )

        # Distinct makers in one event
        makers = sorted({a.get("provider") for a in agents if a.get("provider")})
        models_used = sorted({a.get("model") for a in agents if a.get("model")})

        return {
            "event_id": event_id,
            "mode": "multi_agent",
            "token_saver": saver_on,
            "lean_mode": _runtime.get("lean_mode"),
            "service_id": _runtime.get("service"),
            "goal": saver_goal,
            "agents": agents,
            "edges": edges,
            "makers_in_event": makers,
            "models_in_event": models_used,
            "litellm_calls": litellm_calls,
            "notes": [
                "Different roles may use different LLMs in one event.",
                "Execute litellm_calls via POST http://127.0.0.1:4000/v1/chat/completions",
                "Pin roles with POST /api/modes {role_overrides:{mastermind:{maker:'xai'}, worker:{tier:'local'}}}",
            ],
        }
    finally:
        # restore runtime if event had temporary overrides
        _runtime.clear()
        _runtime.update(saved)


def modes_status(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_modes_config()
    snap = snapshot or {"models": {}}
    runtime = get_runtime()
    resolved = {}
    for role in ("mastermind", "supervisor", "worker", "inline"):
        try:
            resolved[role] = pick_model_for_role(snap, role, cfg)
        except Exception as e:
            resolved[role] = {"role": role, "error": str(e)}
    return {
        "runtime": runtime,
        "defaults": cfg.get("defaults"),
        "token_saver_config": cfg.get("token_saver"),
        "lean_modes": ["off", "balanced", "strict"],
        "presets": list((cfg.get("presets") or {}).keys()),
        "roles": {
            k: {
                "description": v.get("description"),
                "needs": v.get("needs"),
                "prefer": v.get("prefer"),
                "select": v.get("select"),
            }
            for k, v in (cfg.get("roles") or {}).items()
        },
        "resolved_now": resolved,
        "how_to": {
            "enable_token_saver": {"token_saver": True},
            "multi_agent": {"mode": "multi_agent"},
            "inline": {"mode": "inline"},
            "pin_mastermind_xai": {"role_overrides": {"mastermind": {"maker": "xai"}}},
            "pin_worker_local_cheap": {
                "role_overrides": {"worker": {"tier": "local", "strategy": "cheapest"}}
            },
            "pin_by_model": {"role_overrides": {"supervisor": {"model": "claude-sonnet-4"}}},
            "preset_thrifty": {"preset": "thrifty"},
        },
    }
