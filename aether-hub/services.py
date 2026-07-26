"""Task-first services resolved dynamically against the live capability matrix."""
from __future__ import annotations

import copy
import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import yaml

from agents import apply_runtime_update, plan_event
from matrix import _score_model

ROOT = Path(__file__).resolve().parent
CATALOG_PATH = Path(os.environ.get("AETHER_SERVICE_CATALOG", str(ROOT / "service_catalog.yaml")))
LITELLM_BASE_URL = os.environ.get("LITELLM_INTERNAL_URL", "http://litellm:4000").rstrip("/")
CLI_BRIDGE_URL = os.environ.get("AETHER_CLI_BRIDGE_URL", "http://host.docker.internal:8767").rstrip("/")
CLI_BRIDGE_TOKEN = os.environ.get("AETHER_CLI_BRIDGE_TOKEN", "")
VERIFY_TTL_SECONDS = 5 * 60
_verify_cache: dict[str, tuple[float, bool]] = {}
_MATCH_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "into", "is", "it", "of", "on", "or", "that", "the", "this", "to", "with",
}


def load_service_catalog(path: Path | None = None) -> dict[str, Any]:
    with open(path or CATALOG_PATH, encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("services"), dict):
        raise ValueError("invalid service_catalog.yaml")
    return value


def _cost_rank(value: Any) -> int:
    return {0: 0, "0": 0, "low": 1, "medium": 2, "high": 3, "very_high": 4}.get(value, 2)


def _candidate_models(
    snapshot: dict[str, Any],
    blueprint: dict[str, Any],
    used_models: set[str],
    used_providers: set[str],
) -> list[tuple[float, str, dict[str, Any]]]:
    needs = set(str(item) for item in (blueprint.get("needs") or ["chat"]))
    prefer = str(blueprint.get("prefer") or "auto")
    max_cost = _cost_rank(blueprint.get("max_cost", "very_high"))
    strategy = str(blueprint.get("strategy") or "best_score")
    ranked = []
    for alias, meta in (snapshot.get("models") or {}).items():
        if not meta.get("available") or _cost_rank(meta.get("cost")) > max_cost:
            continue
        score = _score_model(meta, needs, prefer)
        if score < 0:
            continue
        if strategy == "cheapest":
            score += 45 - 15 * _cost_rank(meta.get("cost"))
            if meta.get("tier") == "local":
                score += 15
        if alias not in used_models:
            score += 6
        if meta.get("provider") and meta.get("provider") not in used_providers:
            score += 4
        ranked.append((score, alias, meta))
    return sorted(ranked, key=lambda item: (-item[0], item[1]))


def _offline_suggestion(snapshot: dict[str, Any], needs: list[str]) -> dict[str, Any] | None:
    need_set = set(needs or ["chat"])
    ranked = []
    for alias, meta in (snapshot.get("models") or {}).items():
        caps = set(meta.get("capabilities") or [])
        if need_set and not (need_set & caps):
            continue
        fake = dict(meta)
        fake["available"] = True
        ranked.append((_score_model(fake, need_set, "auto"), alias, meta))
    if not ranked:
        return None
    _, alias, meta = sorted(ranked, key=lambda item: (-item[0], item[1]))[0]
    return {
        "model": alias,
        "provider": meta.get("provider"),
        "backend": meta.get("backend"),
        "reason": meta.get("availability_reason") or "not available",
    }


def _words(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) > 1 and token not in _MATCH_STOP_WORDS
    }


def _phrase_present(phrase: str, value: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", phrase.lower())
    if not tokens:
        return False
    pattern = r"\b" + r"\W+".join(re.escape(token) for token in tokens) + r"\b"
    return re.search(pattern, value.lower()) is not None


def classify_service(goal: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Choose a catalog service from task language without pinning models or providers."""
    goal = str(goal or "").strip()
    if not goal:
        raise ValueError("goal is required for automatic service selection")
    catalog = load_service_catalog()
    goal_lower = goal.lower()
    goal_words = _words(goal)
    ranked: list[tuple[float, str, list[str]]] = []
    for service_id, service in (catalog.get("services") or {}).items():
        score = 0.0
        matches: list[str] = []
        label = str(service.get("label") or service_id)
        identity_phrases = {service_id.replace("-", " "), label.lower()}
        for phrase in identity_phrases:
            if phrase and _phrase_present(phrase, goal_lower):
                score += 14.0
                matches.append(phrase)
        for phrase_value in service.get("match") or []:
            phrase = str(phrase_value).strip().lower()
            if phrase and phrase not in matches and _phrase_present(phrase, goal_lower):
                score += 8.0 + min(4, len(_words(phrase)))
                matches.append(phrase)
        label_overlap = goal_words & _words(label)
        activity_overlap = goal_words & _words(" ".join(service.get("activities") or []))
        context_overlap = goal_words & _words(
            f"{service.get('summary', '')} {service.get('instructions', '')}"
        )
        score += 5.0 * len(label_overlap)
        score += 2.0 * len(activity_overlap)
        score += 0.5 * len(context_overlap)
        ranked.append((score, service_id, sorted(set(matches) | label_overlap | activity_overlap)))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    default_id = str((catalog.get("defaults") or {}).get("default_service") or "")
    if not ranked:
        raise ValueError("service catalog is empty")
    best = ranked[0]
    if best[0] <= 0 and default_id in (catalog.get("services") or {}):
        best = next(item for item in ranked if item[1] == default_id)
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    margin = max(0.0, best[0] - runner_up)
    confidence = "high" if best[0] >= 18 and margin >= 6 else "medium" if best[0] >= 8 else "fallback"
    return {
        "service_id": best[1],
        "label": (catalog["services"][best[1]] or {}).get("label") or best[1],
        "confidence": confidence,
        "score": round(best[0], 2),
        "matched_terms": best[2],
        "candidates": [
            {"service_id": service_id, "score": round(score, 2)}
            for score, service_id, _matches in ranked[:3]
        ],
        "service": minimize_service_agents(resolve_service(best[1], snapshot), {"goal": goal}),
    }


def _resolve_agent(
    snapshot: dict[str, Any],
    agent_id: str,
    role: str,
    blueprint: dict[str, Any],
    used_models: set[str],
    used_providers: set[str],
) -> dict[str, Any]:
    candidates = _candidate_models(snapshot, blueprint, used_models, used_providers)
    needs = list(blueprint.get("needs") or ["chat"])
    base = {
        "id": agent_id,
        "role": role,
        "label": blueprint.get("label") or role.title(),
        "needs": needs,
        "strategy": blueprint.get("strategy") or "best_score",
    }
    if not candidates:
        return {**base, "available": False, "suggestion": _offline_suggestion(snapshot, needs)}
    score, alias, meta = candidates[0]
    capabilities = list(meta.get("capabilities") or [])
    missing_capabilities = sorted(set(needs) - set(capabilities))
    used_models.add(alias)
    if meta.get("provider"):
        used_providers.add(str(meta["provider"]))
    return {
        **base,
        "available": True,
        "model": alias,
        "provider": meta.get("provider"),
        "backend": meta.get("backend"),
        "tier": meta.get("tier"),
        "cost": meta.get("cost"),
        "capabilities": capabilities,
        "missing_capabilities": missing_capabilities,
        "capability_fit": "full" if not missing_capabilities else "partial",
        "availability_reason": meta.get("availability_reason"),
        "score": round(score, 2),
    }


def resolve_service(service_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    catalog = load_service_catalog()
    service = (catalog.get("services") or {}).get(service_id)
    if not service:
        raise ValueError(f"unknown service: {service_id}")
    defaults = catalog.get("defaults") or {}
    used_models: set[str] = set()
    used_providers: set[str] = set()
    agents = [
        _resolve_agent(snapshot, "lead", "mastermind", service.get("lead") or {}, used_models, used_providers),
        _resolve_agent(snapshot, "reviewer", "supervisor", service.get("reviewer") or {}, used_models, used_providers),
    ]
    for index, stream in enumerate(service.get("workstreams") or []):
        agents.append(
            _resolve_agent(snapshot, f"worker-{index + 1}", "worker", stream, used_models, used_providers)
        )
    available = [agent for agent in agents if agent.get("available")]
    missing = [agent for agent in agents if not agent.get("available")]
    partial = [agent for agent in available if agent.get("missing_capabilities")]
    return {
        "id": service_id,
        "label": service.get("label") or service_id,
        "summary": service.get("summary") or "",
        "activities": list(service.get("activities") or []),
        "accent": service.get("accent") or "blue",
        "instructions": service.get("instructions") or "",
        "mode": service.get("mode") or defaults.get("mode") or "multi_agent",
        "lean_mode": service.get("lean_mode") or defaults.get("lean_mode") or "balanced",
        "token_saver": bool(service.get("token_saver", defaults.get("token_saver", False))),
        "agents": agents,
        "ready": not missing and not partial and bool(available),
        "degraded": bool(available) and bool(missing or partial),
        "available_agents": len(available),
        "agent_count": len(agents),
        "models": sorted({agent.get("model") for agent in available if agent.get("model")}),
        "providers": sorted({agent.get("provider") for agent in available if agent.get("provider")}),
        "backends": sorted({agent.get("backend") for agent in available if agent.get("backend")}),
        "missing": missing,
        "partial": partial,
        "verification": "not_run",
    }


_ASSURANCE_SERVICES = {"research", "testing", "bugfixing", "whitehat-pentesting"}
_ASSURANCE_WORDS = re.compile(
    r"\b(auth|security|privacy|release|production|migration|payment|permission|destructive|regression|audit|legal)\b",
    re.IGNORECASE,
)
_COMPLEX_WORDS = re.compile(
    r"\b(compare|multiple|several|comprehensive|architecture|end[- ]to[- ]end|parallel|cross[- ]platform|system[- ]wide)\b",
    re.IGNORECASE,
)


def minimize_service_agents(
    resolved: dict[str, Any], event: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Use the smallest useful team; expand only for assurance or real parallel work."""
    event = event or {}
    budget = str(event.get("agent_budget") or "adaptive").lower()
    if budget == "full":
        result = copy.deepcopy(resolved)
        result["agent_policy"] = {"budget": "full", "reason": "explicit full team"}
        return result

    result = copy.deepcopy(resolved)
    agents = list(result.get("agents") or [])
    lead = next((agent for agent in agents if agent.get("role") == "mastermind"), None)
    reviewer = next((agent for agent in agents if agent.get("role") == "supervisor"), None)
    workers = [agent for agent in agents if agent.get("role") == "worker"]
    goal = str(event.get("goal") or event.get("prompt") or "")
    assurance = result.get("id") in _ASSURANCE_SERVICES or bool(_ASSURANCE_WORDS.search(goal))
    complex_work = bool(_COMPLEX_WORDS.search(goal)) or len(goal) > 700

    chosen = [agent for agent in (lead, workers[0] if workers else None) if agent]
    if assurance and reviewer:
        chosen.append(reviewer)
    if budget == "adaptive" and complex_work and len(workers) > 1:
        chosen.append(workers[1])
    chosen_ids = {agent.get("id") for agent in chosen}
    result["agents"] = [agent for agent in agents if agent.get("id") in chosen_ids]
    available = [agent for agent in result["agents"] if agent.get("available")]
    missing = [agent for agent in result["agents"] if not agent.get("available")]
    partial = [agent for agent in available if agent.get("missing_capabilities")]
    result.update(
        {
            "ready": not missing and not partial and bool(available),
            "degraded": bool(available) and bool(missing or partial),
            "available_agents": len(available),
            "agent_count": len(result["agents"]),
            "models": sorted({agent.get("model") for agent in available if agent.get("model")}),
            "providers": sorted({agent.get("provider") for agent in available if agent.get("provider")}),
            "backends": sorted({agent.get("backend") for agent in available if agent.get("backend")}),
            "missing": missing,
            "partial": partial,
            "agent_policy": {
                "budget": budget if budget in {"minimal", "adaptive"} else "adaptive",
                "assurance_gate": assurance,
                "parallel_worker": complex_work and len(workers) > 1,
                "reason": "smallest useful team; review only for assurance and a second worker only for parallel complexity",
            },
        }
    )
    return result


def _verify_model(alias: str) -> bool:
    cached = _verify_cache.get(alias)
    if cached and time.time() - cached[0] < VERIFY_TTL_SECONDS:
        return cached[1]
    key = os.environ.get("LITELLM_MASTER_KEY", "sk-aether-local")
    url = f"{LITELLM_BASE_URL}/health?model={urllib.parse.quote(alias)}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    ok = False
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        ok = (
            response.status == 200
            and int(body.get("healthy_count") or 0) > 0
            and int(body.get("unhealthy_count") or 0) == 0
        )
    except Exception:
        ok = False
    _verify_cache[alias] = (time.time(), ok)
    return ok


def _verify_host_cli(alias: str) -> bool:
    if not CLI_BRIDGE_TOKEN:
        return False
    request = urllib.request.Request(
        f"{CLI_BRIDGE_URL}/health?model={urllib.parse.quote(alias)}",
        headers={"Authorization": f"Bearer {CLI_BRIDGE_TOKEN}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        return response.status == 200 and body.get("ok") is True
    except Exception:
        return False


def resolve_verified_service(
    service_id: str,
    snapshot: dict[str, Any],
    verifier: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    supplied_verifier = verifier
    working = copy.deepcopy(snapshot)
    checked: dict[str, bool] = {}
    resolved = resolve_service(service_id, working)
    for _ in range(3):
        aliases = sorted({a.get("model") for a in resolved["agents"] if a.get("model") and a.get("available")})
        pending = [alias for alias in aliases if alias not in checked]
        if pending:
            def verify_alias(alias: str) -> bool:
                if supplied_verifier:
                    return supplied_verifier(alias)
                meta = (working.get("models") or {}).get(alias) or {}
                return _verify_host_cli(alias) if meta.get("executor") == "host_cli" else _verify_model(alias)

            with ThreadPoolExecutor(max_workers=min(6, len(pending))) as pool:
                results = list(pool.map(verify_alias, pending))
            checked.update(dict(zip(pending, results)))
        failed = [alias for alias in aliases if not checked.get(alias, False)]
        if not failed:
            break
        for alias in failed:
            if alias in (working.get("models") or {}):
                working["models"][alias]["available"] = False
                working["models"][alias]["availability_reason"] = (
                    "authenticated host CLI health failed"
                    if working["models"][alias].get("executor") == "host_cli"
                    else "LiteLLM provider health failed"
                )
        resolved = resolve_service(service_id, working)
    resolved["verification"] = "passed" if resolved.get("ready") else "degraded"
    resolved["verified_models"] = sorted(alias for alias, ok in checked.items() if ok)
    resolved["failed_models"] = sorted(alias for alias, ok in checked.items() if not ok)
    return resolved


def list_services(snapshot: dict[str, Any], discover: dict[str, Any] | None = None) -> dict[str, Any]:
    catalog = load_service_catalog()
    services = [minimize_service_agents(resolve_service(service_id, snapshot)) for service_id in catalog["services"]]
    return {
        "schema": catalog.get("schema"),
        "services": services,
        "available_model_count": sum(1 for meta in (snapshot.get("models") or {}).values() if meta.get("available")),
        "available_providers": sorted(
            {meta.get("provider") for meta in (snapshot.get("models") or {}).values() if meta.get("available") and meta.get("provider")}
        ),
        "runtime": (discover or {}).get("services") or {},
        "cloud": (discover or {}).get("cloud_keys") or {},
        "note": "Agents are resolved from live capabilities. The catalog contains no model or provider pins.",
    }


def activate_service(
    service_id: str,
    snapshot: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    resolved = (
        resolve_verified_service(service_id, snapshot)
        if options.get("verify", True)
        else resolve_service(service_id, snapshot)
    )
    resolved = minimize_service_agents(resolved, options)
    runtime = _activate_resolved_service(resolved, options)
    return {"ok": resolved.get("ready") or resolved.get("degraded"), "service": resolved, "runtime": runtime}


def _activate_resolved_service(
    resolved: dict[str, Any], options: dict[str, Any] | None = None
) -> dict[str, Any]:
    options = options or {}
    picks = {
        agent["role"]: {"model": agent["model"]}
        for agent in resolved["agents"]
        if agent.get("available") and agent["role"] in {"mastermind", "supervisor", "worker"}
    }
    apply_runtime_update({"clear_overrides": True})
    return apply_runtime_update(
        {
            "mode": resolved["mode"],
            "token_saver": bool(options.get("token_saver", resolved["token_saver"])),
            "lean_mode": options.get("lean_mode") or resolved["lean_mode"],
            "service": resolved["id"],
            "role_overrides": picks,
        }
    )


def default_service_id() -> str:
    catalog = load_service_catalog()
    services = catalog.get("services") or {}
    if not services:
        raise ValueError("service catalog is empty")
    # The first catalog entry is the visible first preset (Research by default).
    return next(iter(services))


def build_service_graph(
    service_id: str, snapshot: dict[str, Any], verify: bool = False
) -> dict[str, Any]:
    from graph import service_to_graph

    resolved = (
        resolve_verified_service(service_id, snapshot)
        if verify
        else resolve_service(service_id, snapshot)
    )
    return service_to_graph(minimize_service_agents(resolved))


def plan_service(
    service_id: str,
    snapshot: dict[str, Any],
    event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = dict(event or {})
    resolved = (
        resolve_verified_service(service_id, snapshot)
        if event.get("verify", True)
        else resolve_service(service_id, snapshot)
    )
    resolved = minimize_service_agents(resolved, event)
    roles = {}
    tasks = []
    for agent in resolved["agents"]:
        if not agent.get("available"):
            continue
        if agent["role"] in ("mastermind", "supervisor"):
            roles[agent["role"]] = {"model": agent["model"]}
        elif agent["role"] == "worker":
            tasks.append(
                {
                    "id": agent["id"],
                    "description": agent["label"],
                    "need": agent["needs"],
                    "model": agent["model"],
                }
            )
    plan = plan_event(
        snapshot,
        {
            **event,
            "mode": resolved["mode"],
            "token_saver": bool(event.get("token_saver", resolved["token_saver"])),
            "lean_mode": event.get("lean_mode") or resolved["lean_mode"],
            "service": service_id,
            "service_instructions": resolved["instructions"],
            "roles": roles,
            "workers": max(1, len(tasks)),
            "tasks": tasks or None,
        },
    )
    plan["service"] = resolved
    return plan


def _chat_completion(call: dict[str, Any], messages: list[dict[str, str]] | None = None) -> dict[str, Any]:
    model = str(call.get("model") or "")
    host_cli = model in {"codex-cli", "claude-cli", "grok-cli"}
    key = CLI_BRIDGE_TOKEN if host_cli else os.environ.get("LITELLM_MASTER_KEY", "sk-aether-local")
    if host_cli and not key:
        raise RuntimeError("host CLI bridge is not configured")
    payload = {
        "model": model,
        "messages": messages or call.get("messages") or [],
        "max_tokens": call.get("max_tokens") or 1600,
    }
    request = urllib.request.Request(
        f"{CLI_BRIDGE_URL if host_cli else LITELLM_BASE_URL}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        value = json.loads(response.read().decode("utf-8"))
    choices = value.get("choices") or []
    content = (((choices[0] if choices else {}).get("message") or {}).get("content") or "")
    return {
        "model": value.get("model") or call.get("model"),
        "content": str(content),
        "usage": value.get("usage") or {},
    }


def _history_block(history: Any) -> str:
    if not isinstance(history, list):
        return ""
    lines = []
    for item in history[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user")[:20]
        content = str(item.get("content") or "")[:4000]
        if content:
            lines.append(f"{role}: {content}")
    return "\n\n".join(lines)[-16000:]


def execute_service(
    service_id: str,
    snapshot: dict[str, Any],
    event: dict[str, Any] | None = None,
    completion: Callable[[dict[str, Any], list[dict[str, str]] | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute a bounded lead -> workers -> review -> synthesis service run."""
    event = dict(event or {})
    goal = str(event.get("goal") or event.get("prompt") or "").strip()
    if not goal:
        raise ValueError("goal is required")
    if len(goal) > 100_000:
        raise ValueError("goal exceeds 100000 characters")
    completion = completion or _chat_completion
    plan = plan_service(service_id, snapshot, event)
    activation = _activate_resolved_service(plan["service"], event)
    calls = plan.get("litellm_calls") or []
    lead_call = next((call for call in calls if call.get("role") == "mastermind"), None)
    supervisor_call = next((call for call in calls if call.get("role") == "supervisor"), None)
    worker_calls = [call for call in calls if call.get("role") == "worker"][:6]
    if not lead_call or not lead_call.get("model"):
        raise ValueError("no available lead model for this service")

    history = _history_block(event.get("history"))
    lead_messages = copy.deepcopy(lead_call.get("messages") or [])
    if history:
        lead_messages.append({"role": "user", "content": f"Recent conversation:\n{history}"})
    lead = completion(lead_call, lead_messages)

    def run_worker(call: dict[str, Any]) -> dict[str, Any]:
        messages = copy.deepcopy(call.get("messages") or [])
        messages.append({"role": "user", "content": f"Lead plan:\n{lead['content'][:12000]}"})
        try:
            result = completion(call, messages)
            return {"ok": True, "role": "worker", "task_id": call.get("task_id"), **result}
        except Exception as exc:
            return {
                "ok": False,
                "role": "worker",
                "task_id": call.get("task_id"),
                "model": call.get("model"),
                "error": str(exc)[:500],
            }

    workers = []
    if worker_calls:
        with ThreadPoolExecutor(max_workers=len(worker_calls)) as pool:
            workers = list(pool.map(run_worker, worker_calls))
    worker_text = "\n\n".join(
        f"[{item.get('task_id') or 'worker'} / {item.get('model')}]\n{item.get('content') or item.get('error') or ''}"
        for item in workers
    )[-40000:]

    review = None
    if supervisor_call and supervisor_call.get("model"):
        review_messages = copy.deepcopy(supervisor_call.get("messages") or [])
        review_messages.append(
            {
                "role": "user",
                "content": f"Goal:\n{goal}\n\nLead plan:\n{lead['content'][:10000]}\n\nWorker results:\n{worker_text}",
            }
        )
        try:
            review = completion(supervisor_call, review_messages)
        except Exception as exc:
            review = {"model": supervisor_call.get("model"), "content": "", "error": str(exc)[:500], "usage": {}}

    final_call = dict(lead_call)
    final_call["max_tokens"] = lead_call.get("max_tokens") or 2000
    final_messages = [
        {
            "role": "system",
            "content": (
                "You are AetherStack, an interactive coding and project copilot. Answer the user directly and conversationally, "
                "using the plan, worker results, review, and recent context. Provide the next useful decision, explanation, code, "
                "or concrete action instead of merely listing facts or orchestration status. Ask one focused question only when "
                "missing information truly blocks a useful answer. Resolve conflicts, do not mention orchestration mechanics "
                "unless useful, and clearly state remaining uncertainty."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Goal:\n{goal}\n\nLead plan:\n{lead['content'][:10000]}\n\n"
                f"Worker results:\n{worker_text}\n\nSupervisor review:\n{(review or {}).get('content', '')[:10000]}"
            ),
        },
    ]
    final = completion(final_call, final_messages)
    steps = [
        {"role": "lead-plan", "model": lead.get("model"), "content": lead.get("content")},
        *workers,
    ]
    if review:
        steps.append({"role": "review", **review})
    usage_items = [lead.get("usage") or {}, final.get("usage") or {}]
    usage_items.extend(item.get("usage") or {} for item in workers)
    if review:
        usage_items.append(review.get("usage") or {})
    usage = {
        key: sum(int(item.get(key) or 0) for item in usage_items)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    return {
        "ok": True,
        "service_id": service_id,
        "answer": final.get("content"),
        "model": final.get("model"),
        "agents": plan.get("service", {}).get("agents") or [],
        "steps": steps,
        "usage": usage,
        "lean_mode": plan.get("lean_mode"),
        "token_saver": plan.get("token_saver"),
        "activation": activation,
    }
