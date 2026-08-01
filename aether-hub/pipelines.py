"""
Pipeline scripting: multi-stage LLM workflows (research → critique → build → test).
Upload/download .aether-pipeline.yaml|json; local voting/ranking (hw-heavy, quality).
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

from agents import pick_model_for_role, plan_event, apply_runtime_update
from matrix import _score_model, tiers_match

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
CATALOG = Path(os.environ.get("AETHER_PIPELINES_CATALOG", str(REPO / "pipelines" / "catalog")))
USER_DIR = Path(os.environ.get("AETHER_PIPELINES_USER", str(REPO / "pipelines" / "user")))
VOTES_PATH = Path(os.environ.get("AETHER_PIPELINES_VOTES", str(REPO / "pipelines" / "votes.json")))

SCHEMA = "aetherstack.pipeline.v1"

_votes_cache: dict[str, Any] | None = None
_user_scripts: dict[str, dict[str, Any]] = {}


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"invalid pipeline file: {path}")
    return data


def _normalize(p: dict[str, Any], source: str = "catalog") -> dict[str, Any]:
    out = copy.deepcopy(p)
    out["schema"] = out.get("schema") or SCHEMA
    out["id"] = out.get("id") or f"pipe-{uuid.uuid4().hex[:8]}"
    out["source"] = out.get("source") or source
    out.setdefault("tags", [])
    out.setdefault("hw_weight", "medium")
    out.setdefault("cost_weight", "medium")
    out.setdefault("stages", [])
    return out


def load_all_pipelines() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for base, src in ((CATALOG, "catalog"), (USER_DIR, "user")):
        if not base.is_dir():
            continue
        for fp in list(base.glob("*.aether-pipeline.yaml")) + list(
            base.glob("*.aether-pipeline.yml")
        ) + list(base.glob("*.aether-pipeline.json")) + list(base.glob("*.yaml")) + list(
            base.glob("*.json")
        ):
            if fp.name in ("votes.json", "README.md"):
                continue
            try:
                raw = _load_yaml_or_json(fp)
                if raw.get("schema") and not str(raw["schema"]).startswith("aetherstack.pipeline"):
                    continue
                if "stages" not in raw and "id" not in raw:
                    continue
                p = _normalize(raw, source=src)
                p["_file"] = str(fp)
                found[p["id"]] = p
            except Exception:
                continue
    for pid, p in _user_scripts.items():
        found[pid] = p
    return found


def get_pipeline(pid: str) -> dict[str, Any] | None:
    return load_all_pipelines().get(pid)


def load_votes() -> dict[str, Any]:
    global _votes_cache
    if _votes_cache is not None:
        return _votes_cache
    if VOTES_PATH.is_file():
        try:
            _votes_cache = json.loads(VOTES_PATH.read_text(encoding="utf-8"))
        except Exception:
            _votes_cache = {"scripts": {}}
    else:
        _votes_cache = {"scripts": {}}
    return _votes_cache


def save_votes() -> None:
    global _votes_cache
    data = load_votes()
    VOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    VOTES_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _votes_cache = data


def vote(
    pipeline_id: str,
    *,
    up: bool | None = None,
    down: bool | None = None,
    hw_flag: str | None = None,
    voter: str = "local",
) -> dict[str, Any]:
    """
    Simple local ranking. hw_flag: low|medium|high|extreme (user perception).
    """
    data = load_votes()
    scripts = data.setdefault("scripts", {})
    s = scripts.setdefault(
        pipeline_id,
        {"up": 0, "down": 0, "hw_votes": {}, "voters": {}},
    )
    key = f"{voter}:{pipeline_id}"
    prev = s.get("voters", {}).get(key)
    if up is True:
        if prev == "up":
            pass
        else:
            if prev == "down":
                s["down"] = max(0, int(s.get("down", 0)) - 1)
            s["up"] = int(s.get("up", 0)) + 1
            s.setdefault("voters", {})[key] = "up"
    if down is True:
        if prev == "down":
            pass
        else:
            if prev == "up":
                s["up"] = max(0, int(s.get("up", 0)) - 1)
            s["down"] = int(s.get("down", 0)) + 1
            s.setdefault("voters", {})[key] = "down"
    if hw_flag:
        hw = s.setdefault("hw_votes", {})
        hw[hw_flag] = int(hw.get(hw_flag, 0)) + 1
    s["score"] = int(s.get("up", 0)) - int(s.get("down", 0))
    s["updated_at"] = time.time()
    save_votes()
    return {"id": pipeline_id, **s}


def ranking() -> list[dict[str, Any]]:
    pipes = load_all_pipelines()
    votes = load_votes().get("scripts") or {}
    rows = []
    for pid, p in pipes.items():
        v = votes.get(pid) or {}
        rows.append(
            {
                "id": pid,
                "title": p.get("title"),
                "tags": p.get("tags"),
                "hw_weight": p.get("hw_weight"),
                "cost_weight": p.get("cost_weight"),
                "up": v.get("up", 0),
                "down": v.get("down", 0),
                "score": v.get("score", 0),
                "hw_votes": v.get("hw_votes") or {},
                "stages": len(p.get("stages") or []),
            }
        )
    rows.sort(key=lambda r: (-int(r.get("score") or 0), r.get("title") or ""))
    return rows


def list_pipelines() -> dict[str, Any]:
    pipes = load_all_pipelines()
    votes = load_votes().get("scripts") or {}
    items = []
    for pid, p in pipes.items():
        v = votes.get(pid) or {}
        items.append(
            {
                "id": pid,
                "title": p.get("title"),
                "description": p.get("description"),
                "tags": p.get("tags"),
                "hw_weight": p.get("hw_weight"),
                "cost_weight": p.get("cost_weight"),
                "token_saver": p.get("token_saver"),
                "stages": [
                    {
                        "id": s.get("id"),
                        "label": s.get("label"),
                        "role": s.get("role"),
                        "purpose": s.get("purpose"),
                    }
                    for s in (p.get("stages") or [])
                ],
                "votes": {
                    "up": v.get("up", 0),
                    "down": v.get("down", 0),
                    "score": v.get("score", 0),
                    "hw_votes": v.get("hw_votes") or {},
                },
                "source": p.get("source"),
                "_file": p.get("_file"),
            }
        )
    items.sort(key=lambda x: (-int((x.get("votes") or {}).get("score") or 0), x.get("title") or ""))
    return {
        "schema": SCHEMA,
        "count": len(items),
        "pipelines": items,
        "ranking": ranking(),
        "how_to": {
            "download": "GET /api/pipelines/{id}/export",
            "upload": "POST /api/pipelines/import",
            "vote": "POST /api/pipelines/{id}/vote {up:true|down:true, hw_flag:'high'}",
            "plan": "POST /api/pipelines/{id}/plan {goal:'...'}",
            "github": "https://github.com/piksliviksi/aetherstack/tree/main/pipelines/catalog",
        },
    }


def export_pipeline(pid: str) -> dict[str, Any]:
    p = get_pipeline(pid)
    if not p:
        raise ValueError(f"unknown pipeline: {pid}")
    out = {k: v for k, v in p.items() if not str(k).startswith("_")}
    out["schema"] = SCHEMA
    out["exported_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return out


def import_pipeline(raw: dict[str, Any] | str, *, persist: bool = True) -> dict[str, Any]:
    if isinstance(raw, str):
        data = yaml.safe_load(raw) if raw.strip().startswith("schema:") or "\n" in raw[:80] else json.loads(raw)
    else:
        data = dict(raw)
    if data.get("pipeline"):
        data = data["pipeline"]
    if data.get("schema") and not str(data["schema"]).startswith("aetherstack.pipeline"):
        raise ValueError(f"unsupported schema: {data.get('schema')}")
    p = _normalize(data, source="import")
    _user_scripts[p["id"]] = p
    if persist:
        USER_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in p["id"])
        fp = USER_DIR / f"{safe}.aether-pipeline.json"
        fp.write_text(json.dumps(export_pipeline(p["id"]) if get_pipeline(p["id"]) else p, indent=2) + "\n", encoding="utf-8")
        # write clean export
        clean = {k: v for k, v in p.items() if not str(k).startswith("_")}
        clean["schema"] = SCHEMA
        fp.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
        p["_file"] = str(fp)
    return {"ok": True, "id": p["id"], "pipeline": p}


def _pick_for_stage(snapshot: dict[str, Any], stage: dict[str, Any]) -> dict[str, Any]:
    """Resolve a model for a pipeline stage using prefer_models + select filters."""
    models = snapshot.get("models") or {}
    sel = dict(stage.get("select") or {})
    prefer_models = list(stage.get("prefer_models") or [])
    prefer_makers = [m.lower() for m in (stage.get("prefer_makers") or [])]
    needs = set(stage.get("needs") or ["chat"])

    # 1) prefer_models in order if available
    for name in prefer_models:
        meta = models.get(name)
        if meta and meta.get("available"):
            if sel.get("tier") and not tiers_match(meta, sel.get("tier")):
                continue
            if sel.get("maker") and str(meta.get("provider") or "").lower() != str(sel["maker"]).lower():
                continue
            return {
                "stage_id": stage.get("id"),
                "role": stage.get("role"),
                "model": name,
                "provider": meta.get("provider"),
                "tier": meta.get("tier"),
                "cost": meta.get("cost"),
                "available": True,
                "selection": "prefer_models",
            }

    # 2) score all available
    prefer = sel.get("prefer") or "auto"
    strategy = (sel.get("strategy") or "best_score").lower()
    candidates: list[tuple[float, str, dict]] = []
    for name, meta in models.items():
        if not meta.get("available"):
            continue
        if sel.get("tier") and not tiers_match(meta, sel.get("tier")):
            continue
        if sel.get("maker") and str(meta.get("provider") or "").lower() != str(sel["maker"]).lower():
            continue
        if prefer_makers and str(meta.get("provider") or "").lower() not in prefer_makers:
            # soft penalty later
            pass
        caps = set(meta.get("capabilities") or [])
        if needs and not (needs & caps):
            continue
        if strategy == "cheapest":
            rank = {
                "0": 0,
                0: 0,
                "low": 1,
                "account": 2,
                "medium": 2,
                "high": 3,
                "very_high": 4,
            }.get(meta.get("cost", "medium"), 2)
            score = 100.0 - 20.0 * rank
            if meta.get("tier") == "local":
                score += 10
        else:
            score = _score_model(meta, needs, prefer)
        if prefer_makers and str(meta.get("provider") or "").lower() in prefer_makers:
            score += 25
        if name in prefer_models:
            score += 40
        candidates.append((score, name, meta))
    candidates.sort(key=lambda x: x[0], reverse=True)
    if not candidates:
        # offline plan via role picker
        role_map = {
            "researcher": "mastermind",
            "critic": "supervisor",
            "builder": "worker",
            "tester": "worker",
        }
        role = role_map.get(stage.get("role") or "", "inline")
        # apply select as temporary override
        ov = {k: sel[k] for k in ("model", "maker", "tier", "strategy", "max_cost") if sel.get(k)}
        if ov:
            apply_runtime_update({"role_overrides": {role: ov}})
        pick = pick_model_for_role(snapshot, role, need_override=list(needs))
        return {
            "stage_id": stage.get("id"),
            "role": stage.get("role"),
            "model": pick.get("model"),
            "provider": pick.get("provider"),
            "available": pick.get("available"),
            "selection": "fallback_role_picker",
            "detail": pick,
        }

    score, name, meta = candidates[0]
    return {
        "stage_id": stage.get("id"),
        "role": stage.get("role"),
        "label": stage.get("label"),
        "purpose": stage.get("purpose"),
        "model": name,
        "provider": meta.get("provider"),
        "tier": meta.get("tier"),
        "cost": meta.get("cost"),
        "available": True,
        "score": score,
        "selection": strategy,
        "ack": bool(stage.get("ack")),
        "gate": bool(stage.get("gate")),
        "parallel": stage.get("parallel") or 1,
        "outputs": stage.get("outputs") or [],
    }


def plan_pipeline(
    pid: str,
    snapshot: dict[str, Any],
    *,
    goal: str = "",
    session_id: str = "default",
) -> dict[str, Any]:
    p = get_pipeline(pid)
    if not p:
        raise ValueError(f"unknown pipeline: {pid}")

    stages_out = []
    litellm_calls = []
    for stage in p.get("stages") or []:
        pick = _pick_for_stage(snapshot, stage)
        stages_out.append(pick)
        n = int(stage.get("parallel") or 1)
        behavior = str(stage.get("behavior_markdown") or "")[:100_000].strip()
        system_prompt = (
            f"You are the {stage.get('role')} in pipeline stage "
            f"'{stage.get('label') or stage.get('id')}'. "
            f"Purpose: {stage.get('purpose') or ''}"
        )
        if behavior:
            system_prompt += f"\n\nAgent-specific behavior profile:\n{behavior}"
        for i in range(max(1, n)):
            litellm_calls.append(
                {
                    "stage_id": stage.get("id"),
                    "role": stage.get("role"),
                    "parallel_index": i,
                    "model": pick.get("model"),
                    "gate": stage.get("gate"),
                    "ack": stage.get("ack"),
                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": goal
                            or f"Execute stage {stage.get('id')} of pipeline {pid}",
                        },
                    ],
                }
            )

    # Also produce a multi-agent plan compatible with existing agents API
    # Map first research→mastermind, critique→supervisor, implement→worker
    role_overrides = {}
    for st, pick in zip(p.get("stages") or [], stages_out):
        role = st.get("role")
        model = pick.get("model")
        if role == "researcher" and model:
            role_overrides["mastermind"] = {"model": model}
        elif role == "critic" and model:
            role_overrides["supervisor"] = {"model": model}
        elif role == "builder" and model:
            role_overrides.setdefault("worker", {"model": model})

    agent_plan = None
    try:
        agent_plan = plan_event(
            snapshot,
            {
                "goal": goal or p.get("title"),
                "mode": p.get("mode") or "multi_agent",
                "token_saver": p.get("token_saver", False),
                "roles": role_overrides,
                "workers": next(
                    (int(s.get("parallel") or 2) for s in (p.get("stages") or []) if s.get("role") == "builder"),
                    2,
                ),
                "session_id": session_id,
                "track_task": True,
            },
        )
    except Exception as e:
        agent_plan = {"error": str(e)}

    makers = sorted({s.get("provider") for s in stages_out if s.get("provider")})
    models = sorted({s.get("model") for s in stages_out if s.get("model")})

    return {
        "pipeline_id": pid,
        "title": p.get("title"),
        "goal": goal,
        "hw_weight": p.get("hw_weight"),
        "cost_weight": p.get("cost_weight"),
        "tags": p.get("tags"),
        "stages": stages_out,
        "makers_in_pipeline": makers,
        "models_in_pipeline": models,
        "litellm_calls": litellm_calls,
        "agent_plan": agent_plan,
        "on_complete": p.get("on_complete")
        or {"slash": ["/done all", "/compact"], "archive": True},
        "flow": " → ".join(
            f"{s.get('label') or s.get('stage_id')}({s.get('model')})" for s in stages_out
        ),
    }
