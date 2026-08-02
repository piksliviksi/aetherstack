"""Task-first services resolved dynamically against the live capability matrix."""
from __future__ import annotations

import copy
import json
import os
import re
import stat
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

import yaml

from agents import apply_runtime_update, plan_event
from attachments import build_image_content_part, decode_attachment, extract_pdf_text
from cross_memory import get_xref_state, pull_context
from inference_runtime import begin as begin_inference
from inference_runtime import finish as finish_inference
from matrix import _score_model, normalize_prefer, tiers_match
from memory import MemoryStore
from work_packet import (
    claims_table,
    coverage_gaps,
    ensure_partitions,
    final_work_packet_instruction,
    force_open_claims_for_gaps,
    format_packet_compact,
    honest_incomplete_answer,
    lead_work_packet_instruction,
    merge_packets,
    parse_work_packet,
    partition_for_worker,
    review_work_packet_instruction,
    worker_failure_claim,
    worker_work_packet_instruction,
)

ROOT = Path(__file__).resolve().parent
CATALOG_PATH = Path(os.environ.get("AETHER_SERVICE_CATALOG", str(ROOT / "service_catalog.yaml")))
_catalog_write_lock = threading.Lock()
PROFILE_DIR = Path(os.environ.get("AETHER_SERVICE_PROFILE_DIR", str(ROOT / "profiles" / "services")))
LITELLM_BASE_URL = os.environ.get("LITELLM_INTERNAL_URL", "http://litellm:4000").rstrip("/")
CLI_BRIDGE_URL = os.environ.get("AETHER_CLI_BRIDGE_URL", "http://host.docker.internal:8767").rstrip("/")
CLI_BRIDGE_TOKEN = os.environ.get("AETHER_CLI_BRIDGE_TOKEN", "")
VERIFY_TTL_SECONDS = 5 * 60
_verify_cache: dict[str, tuple[float, bool]] = {}
_verify_cache_lock = threading.Lock()
_preset_model_cooldown: dict[str, float] = {}
_preset_model_cooldown_lock = threading.Lock()
try:
    _preset_cooldown_raw = int(os.environ.get("AETHER_PRESET_MODEL_COOLDOWN_SECONDS", "1800"))
except ValueError:
    _preset_cooldown_raw = 1800
PRESET_MODEL_COOLDOWN_SECONDS = max(30, min(3600, _preset_cooldown_raw))
# Auto mode: sticky preferred model per session (host CLI → next CLI → local GPU)
_auto_session_model: dict[str, str] = {}
_auto_session_exhausted: dict[str, set[str]] = {}
_auto_session_lru: OrderedDict[str, None] = OrderedDict()
_auto_session_lock = threading.RLock()
try:
    _auto_session_max_raw = int(os.environ.get("AETHER_AUTO_SESSION_MAX", "2048"))
except ValueError:
    _auto_session_max_raw = 2048
_AUTO_SESSION_MAX = max(16, min(100_000, _auto_session_max_raw))
# Default host-CLI order, used until the user saves their own priority.
HOST_CLI_AUTO_ORDER = ("grok-cli", "claude-cli", "codex-cli")
AUTO_SEQUENCE_MODES = ("sequential_exhaustion", "per_request")
DEFAULT_AUTO_SEQUENCE_MODE = "sequential_exhaustion"
LOCAL_CODING_AUTO_ORDER = (
    "local-default",
    "local-llama",
    "local-llama31-8b",
    "local-tiny",
)
AUTO_CHAIN_FILE = Path(
    os.environ.get("AETHER_AUTO_CHAIN_STATE", str(ROOT / "data" / "auto_chain.json"))
)


def get_auto_order() -> list[str]:
    """User-chosen Auto fallback order, or the built-in default."""
    try:
        if AUTO_CHAIN_FILE.is_file():
            data = json.loads(AUTO_CHAIN_FILE.read_text(encoding="utf-8"))
            order = [str(item).strip() for item in (data.get("order") or []) if str(item).strip()]
            if order:
                return order
    except (OSError, json.JSONDecodeError):
        pass
    return list(HOST_CLI_AUTO_ORDER)


def get_auto_sequence_mode() -> str:
    """Saved Auto continuation policy; sequential exhaustion is the product default."""
    try:
        if AUTO_CHAIN_FILE.is_file():
            data = json.loads(AUTO_CHAIN_FILE.read_text(encoding="utf-8"))
            mode = str(data.get("sequence_mode") or "").strip()
            if mode in AUTO_SEQUENCE_MODES:
                return mode
    except (OSError, json.JSONDecodeError):
        pass
    return DEFAULT_AUTO_SEQUENCE_MODE


def set_auto_order(order: Any, sequence_mode: Any = None) -> list[str]:
    """Persist model priority and continuation policy. Empty order restores defaults."""
    if not isinstance(order, (list, tuple)):
        raise ValueError("order must be a list of model aliases")
    cleaned: list[str] = []
    for item in order:
        alias = str(item or "").strip()
        if len(alias) > 128:
            raise ValueError(f"model alias too long: {alias[:32]}…")
        if alias and alias not in cleaned:
            cleaned.append(alias)
    mode = str(sequence_mode or get_auto_sequence_mode()).strip()
    if mode not in AUTO_SEQUENCE_MODES:
        raise ValueError(f"sequence_mode must be one of: {', '.join(AUTO_SEQUENCE_MODES)}")
    AUTO_CHAIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTO_CHAIN_FILE.write_text(
        json.dumps({"order": cleaned, "sequence_mode": mode, "updated_at": time.time()}, indent=2) + "\n",
        encoding="utf-8",
    )
    with _auto_session_lock:
        _auto_session_model.clear()
        _auto_session_exhausted.clear()
        _auto_session_lru.clear()
    return cleaned or list(HOST_CLI_AUTO_ORDER)


def _touch_auto_session(session_id: str) -> None:
    """Update bounded process-local Auto state; caller must hold the state lock."""
    if not session_id:
        return
    _auto_session_lru.pop(session_id, None)
    _auto_session_lru[session_id] = None
    while len(_auto_session_lru) > _AUTO_SESSION_MAX:
        expired, _ = _auto_session_lru.popitem(last=False)
        _auto_session_model.pop(expired, None)
        _auto_session_exhausted.pop(expired, None)
_FAILOVER_ERROR_RE = re.compile(
    r"rate.?limit|quota|usage.?limit|weekly|daily.?limit|session.?limit|"
    r"too many requests|\b429\b|insufficient.?quota|exceeded|out of credits|"
    r"billing|subscription|limit reached|capacity|not authenticated|"
    r"unauthorized|payment|overloaded|unavailable|timeout|timed out|"
    r"context.?length|maximum context|token limit|exhausted|no credits|"
    r"resource.?exhausted|throttl|temporarily unavailable|connection refused|"
    r"host CLI bridge|not configured|failed to|ECONNREFUSED",
    re.I,
)
_EXHAUSTION_ERROR_RE = re.compile(
    r"rate.?limit|quota|usage.?limit|weekly|daily.?limit|session.?limit|"
    r"too many requests|\b429\b|insufficient.?quota|out of credits|billing|"
    r"subscription limit|limit reached|context.?length|maximum context|token limit|"
    r"resource.?exhausted|no credits|payment required",
    re.I,
)
_TRANSIENT_ERROR_RE = re.compile(
    r"temporar(?:y|ily) unavailable|overloaded|connection (?:reset|refused)|"
    r"ECONNRESET|ECONNREFUSED|EAI_AGAIN|bad gateway|service unavailable|gateway timeout|\b50[234]\b",
    re.I,
)
_MATCH_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "into", "is", "it", "of", "on", "or", "that", "the", "this", "to", "with",
}

# Unified memory context budget (KiB of text injected into Auto prompts).
# 512 is the default: enough for multi-turn coding + recall without saturating
# typical local Ollama windows (32k–128k tokens). Users can pick 256/512/1024/2048.
MEMORY_CONTEXT_KB_OPTIONS = (256, 512, 1024, 2048)
DEFAULT_MEMORY_CONTEXT_KB = 512


def resolve_memory_context_kb(value: Any = None) -> int:
    """Clamp to allowed memory context sizes (KiB). Default 512."""
    raw = value
    if raw is None or raw == "":
        raw = os.environ.get("AETHER_MEMORY_CONTEXT_KB", DEFAULT_MEMORY_CONTEXT_KB)
    try:
        kb = int(raw)
    except (TypeError, ValueError):
        kb = DEFAULT_MEMORY_CONTEXT_KB
    if kb in MEMORY_CONTEXT_KB_OPTIONS:
        return kb
    return min(MEMORY_CONTEXT_KB_OPTIONS, key=lambda option: abs(option - kb))


def memory_context_chars(kb: Any = None) -> int:
    """Character budget for unified memory injection (~1 char ≈ 1 byte for ASCII)."""
    return resolve_memory_context_kb(kb) * 1024


def _trim_to_budget(text: str, budget: int) -> str:
    text = str(text or "")
    if budget <= 0 or len(text) <= budget:
        return text
    if budget < 32:
        return text[:budget]
    return text[: max(0, budget - 16)].rstrip() + "\n…[truncated]"


def load_service_catalog(path: Path | None = None) -> dict[str, Any]:
    with open(path or CATALOG_PATH, encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("services"), dict):
        raise ValueError("invalid service_catalog.yaml")
    if value.get("schema") != "aetherstack.services.v1":
        raise ValueError("unsupported service catalog schema")
    return value


def load_service_profile(service_id: str, profile_dir: Path | None = None) -> tuple[str, str]:
    """Load a bounded, editable built-in service behavior profile."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", service_id):
        raise ValueError("invalid service profile id")
    path = (profile_dir or PROFILE_DIR) / f"{service_id}.md"
    if not path.is_file():
        return "", ""
    content = path.read_text(encoding="utf-8")
    if len(content) > 100_000:
        raise ValueError(f"service profile {service_id!r} exceeds 100000 characters")
    return content, path.name


def _cost_rank(value: Any) -> int:
    # "account" = host CLI subscription seat (already paid; treat like medium-low)
    return {
        0: 0,
        "0": 0,
        "low": 1,
        "account": 2,
        "medium": 2,
        "high": 3,
        "very_high": 4,
    }.get(value, 2)


def _candidate_models(
    snapshot: dict[str, Any],
    blueprint: dict[str, Any],
    used_models: set[str],
    used_providers: set[str],
) -> list[tuple[float, str, dict[str, Any]]]:
    needs = set(str(item) for item in (blueprint.get("needs") or ["chat"]))
    prefer = normalize_prefer(blueprint.get("prefer") or "auto")
    want_tier = blueprint.get("tier")
    max_cost = _cost_rank(blueprint.get("max_cost", "very_high"))
    strategy = str(blueprint.get("strategy") or "best_score")
    ranked = []
    for alias, meta in (snapshot.get("models") or {}).items():
        if not meta.get("available") or _cost_rank(meta.get("cost")) > max_cost:
            continue
        if want_tier and not tiers_match(meta, want_tier):
            continue
        score = _score_model(meta, needs, prefer)
        if score < 0:
            continue
        if strategy == "cheapest":
            score += 45 - 15 * _cost_rank(meta.get("cost"))
            if meta.get("tier") == "local":
                score += 15
        # Presets exist to gain independent judgment from multiple models. Once
        # capability and cost constraints are satisfied, strongly prefer a model
        # that has not already filled another role in this preset.
        if alias not in used_models:
            score += 100
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


def _build_display_chain(
    snapshot: dict[str, Any], candidates: list[tuple[float, str, dict[str, Any]]], limit: int = 3
) -> list[dict[str, Any]]:
    """Top-N ranked candidates plus a guaranteed local-tier entry at the end, so the
    node graph can render the real primary -> ... -> local-GPU-fallback chain that
    auto-resolution actually falls back through, not just the single winning pick."""
    models = snapshot.get("models") or {}
    chain_aliases = [alias for _, alias, _ in candidates[:limit]]
    if not any(models.get(alias, {}).get("tier") == "local" for alias in chain_aliases):
        local = next((alias for _, alias, meta in candidates if meta.get("tier") == "local"), None)
        if not local:
            local = next(
                (alias for alias, meta in models.items() if meta.get("tier") == "local" and meta.get("available")),
                None,
            )
        if local:
            chain_aliases = [*chain_aliases, local]
    return [
        {"model": alias, "tier": models.get(alias, {}).get("tier"), "provider": models.get(alias, {}).get("provider")}
        for alias in chain_aliases
    ]


def _normalize_chain(chain: list[Any], models: dict[str, Any]) -> list[dict[str, Any]]:
    """`fallback_chain` has two producers with different shapes: an authored
    chain from the catalog (graph_to_service_patch saves plain model-alias
    strings, matching how pin_model/needs/etc. are stored) and
    `_build_display_chain`'s auto-ranked chain (list[dict] with tier/provider
    already resolved). service_to_graph only knows how to render dicts, so
    without this normalizer a saved string chain silently collapses to a
    single-entry chain on reload — exactly the round-trip a saved graph must
    not lose."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in chain:
        if isinstance(link, dict):
            alias = link.get("model")
        elif isinstance(link, str):
            alias = link
        else:
            continue
        alias = alias.strip() if isinstance(alias, str) else ""
        if not alias or alias in seen:
            continue
        seen.add(alias)
        meta = models.get(alias) or {}
        out.append(
            {
                "model": alias,
                "tier": (link.get("tier") if isinstance(link, dict) else None) or meta.get("tier"),
                "provider": (link.get("provider") if isinstance(link, dict) else None) or meta.get("provider"),
            }
        )
    return out


def _resolve_agent(
    snapshot: dict[str, Any],
    agent_id: str,
    role: str,
    blueprint: dict[str, Any],
    used_models: set[str],
    used_providers: set[str],
) -> dict[str, Any]:
    needs = list(blueprint.get("needs") or ["chat"])
    base = {
        "id": agent_id,
        "role": role,
        "label": blueprint.get("label") or role.title(),
        "needs": needs,
        "strategy": blueprint.get("strategy") or "best_score",
        "max_cost": blueprint.get("max_cost"),
    }
    models = snapshot.get("models") or {}
    # Whether the catalog actually stores a fallback_chain for this role, vs.
    # `fallback_chain` below being _build_display_chain's live auto-ranked
    # preview. graph.py's service_to_graph uses this to mark preview-only
    # route nodes "synthetic" so an unrelated save can't freeze the current
    # auto-ranking into the catalog as if the user had authored it.
    chain_authored = bool(blueprint.get("fallback_chain"))

    def pick(alias: str, meta: dict[str, Any], chain: list[Any], *, explicit_pin: bool) -> dict[str, Any]:
        used_models.add(alias)
        if meta.get("provider"):
            used_providers.add(str(meta["provider"]))
        capabilities = list(meta.get("capabilities") or [])
        missing_capabilities = sorted(set(needs) - set(capabilities))
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
            "availability_reason": None,
            "score": 999.0,
            "pinned": True,
            # Only a plain pin_model (not a fallback-chain win) round-trips as
            # an explicit single-model choice in the node graph — see
            # graph.py's agent_node(), which stamps model_explicit from this
            # so re-saving an already-pinned preset doesn't need the user to
            # re-touch the model dropdown to keep the pin.
            "model_explicit": explicit_pin,
            "fallback_chain": _normalize_chain(chain, models),
            "chain_authored": chain_authored,
        }

    # An explicit, user-wired fallback chain (from the node graph's route nodes)
    # takes priority over everything else: try each alias in order, first
    # available wins. Reordering/rewiring those nodes and saving is what changes
    # this list, so auto-selection literally follows the wiring.
    authored_chain = blueprint.get("fallback_chain") or None
    if authored_chain:
        for link in authored_chain:
            # Catalog storage is plain alias strings, but tolerate a stray
            # {"model": alias, ...} dict (e.g. hand-edited YAML, or a chain
            # copied from a resolved/display value) rather than crashing on
            # an unhashable dict key.
            alias = link.get("model") if isinstance(link, dict) else link
            if not alias or not isinstance(alias, str):
                continue
            meta = models.get(alias) or {}
            if meta.get("available"):
                return pick(alias, meta, list(authored_chain), explicit_pin=False)

    pin = blueprint.get("pin_model")
    pinned_meta = models.get(pin) if pin else None
    if pin and pinned_meta and pinned_meta.get("available"):
        return pick(pin, pinned_meta, authored_chain or [pin], explicit_pin=True)

    candidates = _candidate_models(snapshot, blueprint, used_models, used_providers)
    display_chain = _normalize_chain(authored_chain, models) if authored_chain else _build_display_chain(snapshot, candidates)
    if not candidates:
        reason = f"pinned model '{pin}' is unavailable" if pin else None
        suggestion = _offline_suggestion(snapshot, needs)
        if reason and suggestion:
            suggestion = {**suggestion, "note": reason}
        return {
            **base,
            "available": False,
            "suggestion": suggestion,
            "fallback_chain": display_chain,
            "chain_authored": chain_authored,
        }
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
        "fallback_chain": display_chain,
        "chain_authored": chain_authored,
    }


def resolve_service(service_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    catalog = load_service_catalog()
    service = (catalog.get("services") or {}).get(service_id)
    if not service:
        raise ValueError(f"unknown service: {service_id}")
    defaults = catalog.get("defaults") or {}
    behavior_markdown, behavior_source = load_service_profile(service_id)
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
        "task_template": service.get("task_template") or service.get("summary") or "",
        "activities": list(service.get("activities") or []),
        "accent": service.get("accent") or "blue",
        "instructions": service.get("instructions") or "",
        "behavior_markdown": behavior_markdown,
        "behavior_source": behavior_source,
        "mode": service.get("mode") or defaults.get("mode") or "multi_agent",
        "lean_mode": service.get("lean_mode") or defaults.get("lean_mode") or "balanced",
        "token_saver": bool(service.get("token_saver", defaults.get("token_saver", False))),
        "memory": service.get("memory"),
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
    r"\b(auth|security|privacy|release|production|migration|payment|permission|destructive|regression|audit|legal|"
    r"analy[sz]e|analysis|review|critic|critique|assess|evaluate|inspect|weak spots?|risks?|codebase)\b",
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

    first_worker = workers[0] if workers else None
    same_backend = bool(
        lead
        and first_worker
        and (
            lead.get("model") == first_worker.get("model")
            or (
                lead.get("backend")
                and lead.get("backend") == first_worker.get("backend")
            )
        )
    )
    chosen = [lead] if lead else []
    if first_worker and (assurance or complex_work or not same_backend):
        chosen.append(first_worker)
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
    with _verify_cache_lock:
        cached = _verify_cache.get(alias)
    if cached and time.time() - cached[0] < VERIFY_TTL_SECONDS:
        return cached[1]
    key = os.environ.get("LITELLM_MASTER_KEY", "")
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
    with _verify_cache_lock:
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
    services = [describe_auto_service(snapshot)]
    services.extend(minimize_service_agents(resolve_service(service_id, snapshot)) for service_id in catalog["services"])
    return {
        "schema": catalog.get("schema"),
        "services": services,
        "available_model_count": sum(1 for meta in (snapshot.get("models") or {}).values() if meta.get("available")),
        "available_providers": sorted(
            {meta.get("provider") for meta in (snapshot.get("models") or {}).values() if meta.get("available") and meta.get("provider")}
        ),
        "host_cli": copy.deepcopy(snapshot.get("host_cli") or {
            "ok": False, "models": [], "reason": "bridge status unavailable"
        }),
        "runtime": (discover or {}).get("services") or {},
        "cloud": (discover or {}).get("cloud_keys") or {},
        "default_service": "auto",
        "note": "Auto is the default sequential model chain; task presets resolve teams from live capabilities.",
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


def _replace_service_block(raw_text: str, service_id: str, new_service: dict[str, Any]) -> str:
    """Splice a single service's YAML block back into the catalog's raw text,
    leaving every other line byte-identical. A plain `yaml.safe_dump(catalog, ...)`
    of the whole ~600-line hand-authored file reformats every service (flow-style
    lists/dicts become block-style, blank-line spacing changes) on every single
    graph save, which would make every preset edit produce a huge unrelated diff
    across services nobody touched."""
    lines = raw_text.split("\n")
    start_marker = f"  {service_id}:"
    start_idx = next(
        (i for i, line in enumerate(lines) if line == start_marker or line.startswith(start_marker + " ")),
        None,
    )
    if start_idx is None:
        raise ValueError(f"service '{service_id}' block not found in {CATALOG_PATH.name}")
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            continue
        if len(line) - len(line.lstrip(" ")) < 4:
            end_idx = i
            break
    while end_idx > start_idx + 1 and lines[end_idx - 1].strip() == "":
        end_idx -= 1
    dumped = yaml.safe_dump(
        {service_id: new_service}, sort_keys=False, allow_unicode=True, width=100, default_flow_style=None
    )
    new_block = ["  " + line if line else line for line in dumped.rstrip("\n").split("\n")]
    return "\n".join(lines[:start_idx] + new_block + lines[end_idx:])


def save_service_graph(service_id: str, graph: dict[str, Any]) -> dict[str, Any]:
    """Write node-graph edits (pinned models, needs, strategy, max_cost, the
    memory node's scope/action, and the fallback-chain order) back into
    service_catalog.yaml for the given service, touching only that service's
    own block. Note: a lead node's instructions_md is separate external
    behavior-profile markdown, not the catalog's `instructions:` field — it is
    intentionally not written here (see graph_to_service_patch)."""
    from graph import graph_to_service_patch

    patch = graph_to_service_patch(graph)
    if patch.get("id") and patch["id"] != service_id:
        raise ValueError("graph does not belong to this service")

    def apply_role(existing: dict[str, Any], role_patch: dict[str, Any]) -> dict[str, Any]:
        updated = dict(existing)
        for key, value in role_patch.items():
            if value is None:
                updated.pop(key, None)
            else:
                updated[key] = value
        return updated

    # ThreadingHTTPServer can process two graph saves at once. Lock the entire
    # read/modify/replace transaction so one service update cannot restore a
    # stale snapshot over another. A unique temporary path also avoids threads
    # writing the same PID-based file.
    with _catalog_write_lock:
        raw_text = CATALOG_PATH.read_text(encoding="utf-8")
        catalog = yaml.safe_load(raw_text)
        catalog_services = (catalog or {}).get("services") or {}
        if service_id not in catalog_services:
            raise ValueError(f"unknown service: {service_id}")
        service = dict(catalog_services[service_id])

        for role_key in ("lead", "reviewer"):
            if patch.get(role_key):
                service[role_key] = apply_role(service.get(role_key) or {}, patch[role_key])
        if patch.get("workstreams"):
            # build_service_graph() shows the smallest-useful-team view
            # (minimize_service_agents), so the graph may display fewer workers
            # than the catalog actually defines. Update in place by position and
            # never shrink the list to len(patch) — that would silently delete
            # catalog workstreams the minimized preview simply didn't render.
            existing = list(service.get("workstreams") or [])
            for index, worker_patch in enumerate(patch["workstreams"]):
                if not worker_patch:
                    continue
                if index < len(existing):
                    existing[index] = apply_role(existing[index], worker_patch)
                else:
                    existing.append(apply_role({}, worker_patch))
            service["workstreams"] = existing
        if "memory" in patch:
            if patch["memory"] is None:
                service.pop("memory", None)
            else:
                service["memory"] = patch["memory"]

        new_text = _replace_service_block(raw_text, service_id, service)
        tmp_path = CATALOG_PATH.with_name(
            f".{CATALOG_PATH.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
        )
        try:
            tmp_path.write_text(new_text, encoding="utf-8")
            try:
                os.chmod(tmp_path, stat.S_IMODE(CATALOG_PATH.stat().st_mode))
            except OSError:
                pass
            os.replace(tmp_path, CATALOG_PATH)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
        return {"ok": True, "id": service_id, "service": service}


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
    resolution_snapshot = snapshot
    goal = str(event.get("goal") or event.get("prompt") or "")
    prefer_local = bool(event.get("prefer_local")) or (
        bool(event.get("token_saver"))
        and str(event.get("agent_budget") or "adaptive").lower() == "minimal"
        and service_id not in _ASSURANCE_SERVICES
        and not _COMPLEX_WORDS.search(goal)
        and len(goal) <= 700
    )
    if prefer_local:
        catalog_service = (load_service_catalog().get("services") or {}).get(service_id) or {}
        lead_needs = set((catalog_service.get("lead") or {}).get("needs") or ["chat"])
        local_full_fit = any(
            meta.get("available")
            and meta.get("tier") == "local"
            and lead_needs.issubset(set(meta.get("capabilities") or []))
            for meta in (snapshot.get("models") or {}).values()
        )
        if local_full_fit:
            resolution_snapshot = copy.deepcopy(snapshot)
            for meta in (resolution_snapshot.get("models") or {}).values():
                if meta.get("tier") != "local":
                    meta["available"] = False
                    meta["availability_reason"] = "local-first token-saver request"
    resolved = (
        resolve_verified_service(service_id, resolution_snapshot)
        if event.get("verify", True)
        else resolve_service(service_id, resolution_snapshot)
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
            "service_instructions": "\n\n".join(
                value for value in (resolved["instructions"], resolved.get("behavior_markdown")) if value
            ),
            "roles": roles,
            "workers": max(1, len(tasks)),
            "tasks": tasks or None,
        },
    )
    # plan_event supports generic multi-agent events and therefore always
    # creates a worker and supervisor. Service presets deliberately minimize
    # the team; do not reintroduce roles that minimize_service_agents removed.
    selected_roles = {
        agent.get("role")
        for agent in resolved.get("agents") or []
        if agent.get("available")
    }
    removed_roles = {"worker", "supervisor"} - selected_roles
    if removed_roles:
        plan["agents"] = [
            agent for agent in (plan.get("agents") or [])
            if agent.get("role") not in removed_roles
        ]
        plan["litellm_calls"] = [
            call for call in (plan.get("litellm_calls") or [])
            if call.get("role") not in removed_roles
        ]
        plan["edges"] = [
            edge for edge in (plan.get("edges") or [])
            if not any(
                str(edge.get(key) or "").endswith(f"-{role}")
                or f"-{role}-" in str(edge.get(key) or "")
                for role in removed_roles
                for key in ("from", "to")
            )
        ]
        plan["makers_in_event"] = sorted(
            {agent.get("provider") for agent in plan["agents"] if agent.get("provider")}
        )
        plan["models_in_event"] = sorted(
            {agent.get("model") for agent in plan["agents"] if agent.get("model")}
        )
    resolved_agents = [agent for agent in (resolved.get("agents") or []) if agent.get("available")]
    role_offsets: dict[str, int] = {}
    for call in plan.get("litellm_calls") or []:
        role = str(call.get("role") or "")
        role_agents = [agent for agent in resolved_agents if agent.get("role") == role]
        task_id = str(call.get("task_id") or "")
        agent = next((item for item in role_agents if str(item.get("id") or "") == task_id), None)
        if agent is None and role_agents:
            offset = role_offsets.get(role, 0)
            agent = role_agents[min(offset, len(role_agents) - 1)]
            role_offsets[role] = offset + 1
        if agent:
            call["fallback_chain"] = [
                str(item.get("model") if isinstance(item, dict) else item)
                for item in (agent.get("fallback_chain") or [])
                if (item.get("model") if isinstance(item, dict) else item)
            ]
    plan["service"] = resolved
    return plan


def _chat_completion(call: dict[str, Any], messages: list[dict[str, str]] | None = None) -> dict[str, Any]:
    model = str(call.get("model") or "")
    host_cli = model in {"codex-cli", "claude-cli", "grok-cli"}
    key = CLI_BRIDGE_TOKEN if host_cli else os.environ.get("LITELLM_MASTER_KEY", "")
    if host_cli and not key:
        raise RuntimeError("host CLI bridge is not configured")
    payload = {
        "model": model,
        "messages": messages or call.get("messages") or [],
        "max_tokens": call.get("max_tokens") or 1600,
        "workspace_write": bool(call.get("workspace_write")),
    }
    request = urllib.request.Request(
        f"{CLI_BRIDGE_URL if host_cli else LITELLM_BASE_URL}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    activity_id = begin_inference(model, "host_cli") if host_cli else None
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            value = json.loads(response.read().decode("utf-8"))
    except Exception:
        if activity_id:
            finish_inference(activity_id, "failed")
        raise
    else:
        if activity_id:
            finish_inference(activity_id, "complete")
    choices = value.get("choices") or []
    content = (((choices[0] if choices else {}).get("message") or {}).get("content") or "")
    return {
        "model": value.get("model") or call.get("model"),
        "content": str(content),
        "usage": value.get("usage") or {},
    }


def _chat_completion_stream(
    call: dict[str, Any],
    messages: list[dict[str, Any]],
    on_delta: Callable[[str], None],
) -> dict[str, Any]:
    model = str(call.get("model") or "")
    payload = {
        "model": model,
        "messages": messages or call.get("messages") or [],
        "max_tokens": call.get("max_tokens") or 1600,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    key = os.environ.get("LITELLM_MASTER_KEY", "")
    request = urllib.request.Request(
        f"{LITELLM_BASE_URL}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    parts: list[str] = []
    final_model = model
    usage: dict[str, Any] = {}
    with urllib.request.urlopen(request, timeout=180) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            payload_text = line[len("data:"):].strip()
            if payload_text == "[DONE]":
                break
            chunk = json.loads(payload_text)
            final_model = chunk.get("model") or final_model
            choice = (chunk.get("choices") or [{}])[0]
            delta_text = (choice.get("delta") or {}).get("content") or ""
            if delta_text:
                parts.append(delta_text)
                on_delta(delta_text)
            if chunk.get("usage"):
                usage = chunk["usage"]
    return {"model": final_model, "content": "".join(parts), "usage": usage}


def _is_host_cli(snapshot: dict[str, Any], model_id: str) -> bool:
    return (snapshot.get("models") or {}).get(model_id, {}).get("executor") == "host_cli"


def _history_block(history: Any) -> str:
    if not isinstance(history, list):
        return ""
    lines = []
    for item in history[-24:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user")[:20]
        content = str(item.get("content") or "")[:6000]
        if content:
            lines.append(f"{role}: {content}")
    return "\n\n".join(lines)[-48000:]


def _merge_history(session_history: list[Any] | None, client_history: Any) -> list[Any]:
    """Server-stored session transcript is authoritative (survives a model switch and a
    reloaded webview); anything the client sent that isn't in it yet is appended after."""
    merged = list(session_history or [])
    seen = {(str(m.get("role")), str(m.get("content"))) for m in merged if isinstance(m, dict)}
    for item in client_history if isinstance(client_history, list) else []:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("role")), str(item.get("content")))
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def _handoff_namespace(session_id: str) -> str:
    return f"handoff-reasoning:{session_id}"


def _load_handoff_context(memory: MemoryStore | None, session_id: str | None, current_model: str) -> str:
    """Pull the previous turn's internal reasoning (lead plan + review notes) back in as
    text context — the only channel that exists between two different model providers.
    Hidden states / KV-caches are architecture-specific and never exposed by any provider's
    API, so this is the real mechanism: written reasoning, not shared weights."""
    if memory is None or not session_id:
        return ""
    try:
        docs = memory.list_vectors(_handoff_namespace(session_id))
    except Exception:
        return ""
    if not docs:
        return ""
    previous_model = (docs[0].get("meta") or {}).get("model")
    trace = "\n\n---\n\n".join(str(d.get("text") or "")[:4000] for d in docs[:3] if d.get("text"))
    if not trace:
        return ""
    if previous_model and previous_model != current_model:
        return (
            f"### Prior reasoning from this session (previously worked by {previous_model}, "
            f"now continued by {current_model})\n"
            "Treat this as your own prior work; continue from it, do not re-derive from scratch.\n\n"
            f"{trace}"
        )
    return f"### Your prior reasoning in this session\n\n{trace}"


def _store_handoff_context(
    memory: MemoryStore | None,
    session_id: str | None,
    service_id: str,
    model: str | None,
    goal: str,
    lead_content: str,
    review_content: str | None,
) -> None:
    if memory is None or not session_id:
        return
    text = f"[goal]\n{goal[:2000]}\n\n[lead reasoning]\n{(lead_content or '')[:6000]}"
    if review_content:
        text += f"\n\n[review notes]\n{review_content[:3000]}"
    try:
        memory.upsert_vector(
            text=text,
            namespace=_handoff_namespace(session_id),
            meta={"model": model, "service_id": service_id, "goal": goal[:200]},
        )
    except Exception:
        pass


def _auto_pull_xref(memory: MemoryStore | None, goal: str) -> str:
    """Auto cross-project recall, mirroring what /api/agents/plan already does — extended
    here so the ordinary service-run path (chat) benefits too, not just the generic
    multi-agent event endpoint."""
    if memory is None or not goal:
        return ""
    try:
        state = get_xref_state()
        if not (state.get("multi_project") and state.get("auto_pull", True)):
            return ""
        pulled = pull_context(memory, goal[:500], top_k=state.get("max_pull"))
        if pulled.get("ok") and pulled.get("prompt_block"):
            return pulled["prompt_block"]
    except Exception:
        pass
    return ""


def _service_memory_ops(service_id: str, resolved_service: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a memory_op descriptor (same shape graph_exec.py's freeform-canvas
    Memory nodes produce) from a service preset's saved memory-node config, so
    chat's Auto/preset path draws on the exact same three-tier pool
    (tree/project/global via resolve_memory_namespace) instead of a separate
    mechanism. Presets that have never had their memory node edited/saved carry
    no `memory` key and get no op — purely opt-in."""
    cfg = resolved_service.get("memory")
    if not cfg:
        return []
    from graph import MEMORY_ACTIONS, MEMORY_SCOPES, resolve_memory_namespace

    scope = str(cfg.get("scope") or "tree").strip().lower()
    if scope not in MEMORY_SCOPES:
        scope = "tree"
    action = str(cfg.get("action") or "search").strip().lower()
    if action not in MEMORY_ACTIONS:
        action = "search"
    namespace = resolve_memory_namespace(
        scope=scope,
        graph_id=f"service-{service_id}",
        project_id=cfg.get("project_id") or service_id,
        namespace=cfg.get("namespace"),
    )
    return [
        {
            "node_id": f"service-{service_id}-memory",
            "label": "Cross-project memory",
            "scope": scope,
            "action": action,
            "namespace": namespace,
            "project_id": cfg.get("project_id") or service_id,
        }
    ]


def _select_vision_model(snapshot: dict[str, Any]) -> str | None:
    best_id: str | None = None
    best_score = float("-inf")
    for model_id, meta in (snapshot.get("models") or {}).items():
        if meta.get("executor") == "host_cli":
            continue
        score = _score_model(meta, {"vision"}, "auto")
        if score > best_score:
            best_id, best_score = model_id, score
    return best_id if best_score > 0 else None


def _augment_final_message_with_attachments(
    final_messages: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    snapshot: dict[str, Any],
    final_call: dict[str, Any],
) -> None:
    if not attachments:
        return
    text = final_messages[-1]["content"]
    for attachment in attachments:
        if attachment.get("type") != "pdf":
            continue
        raw = decode_attachment(attachment)
        extracted = extract_pdf_text(raw)
        label = attachment.get("name") or "attachment.pdf"
        text += f"\n\n--- {label} ---\n{extracted}" if extracted else f"\n\n[no text could be extracted from {label}]"
    images = [item for item in attachments if item.get("type") == "image"]
    if images:
        vision_model = _select_vision_model(snapshot)
        if vision_model:
            final_call["model"] = vision_model
            parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
            for attachment in images:
                raw = decode_attachment(attachment)
                mime = attachment.get("mime") or "image/png"
                parts.append(build_image_content_part(raw, mime))
            final_messages[-1]["content"] = parts
            return
        text += "\n\n[image attached but no vision-capable model is currently available; image omitted]"
    final_messages[-1]["content"] = text


def _emit_status(
    on_status: Callable[[dict[str, Any]], None] | None,
    phase: str,
    *,
    model: str | None = None,
    models: list[str] | None = None,
    label: str | None = None,
) -> None:
    """Best-effort progress for UIs (VS Code chat, SSE). Never raise into the run."""
    if on_status is None:
        return
    payload: dict[str, Any] = {"phase": phase}
    if model:
        payload["model"] = model
    if models:
        payload["models"] = [m for m in models if m]
    if label:
        payload["label"] = label
    try:
        on_status(payload)
    except Exception:
        pass


def _complete_with_retry(
    completion: Callable[[dict[str, Any], list[dict[str, Any]] | None], dict[str, Any]],
    call: dict[str, Any],
    messages: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Retry one clearly transient transport/backend failure, never auth, quota, or timeouts."""
    try:
        return completion(call, messages)
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code not in (502, 503, 504) and not _TRANSIENT_ERROR_RE.search(str(exc or "")):
            raise
        time.sleep(0.15)
        return completion(call, messages)


def _complete_with_preset_failover(
    completion: Callable[[dict[str, Any], list[dict[str, Any]] | None], dict[str, Any]],
    call: dict[str, Any],
    messages: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Continue a preset role on its next resolved model after a provider limit."""
    models: list[str] = []
    for candidate in [call.get("model"), *(call.get("fallback_chain") or [])]:
        model = str(candidate or "")
        if model and model not in models:
            models.append(model)
    errors: list[dict[str, str]] = []
    now = time.monotonic()
    with _preset_model_cooldown_lock:
        expired = [model for model, until in _preset_model_cooldown.items() if until <= now]
        for model in expired:
            _preset_model_cooldown.pop(model, None)
        cooled = {model for model in models if _preset_model_cooldown.get(model, 0) > now}
    eligible = [model for model in models if model not in cooled]
    if eligible:
        for model in models:
            if model in cooled:
                errors.append({"model": model, "error": "temporarily skipped after a recent provider failure"})
        models = eligible
    for index, model in enumerate(models):
        attempt = {**call, "model": model}
        try:
            result = _complete_with_retry(completion, attempt, messages)
            with _preset_model_cooldown_lock:
                _preset_model_cooldown.pop(model, None)
            if errors:
                result = {
                    **result,
                    "failover_from": errors[0]["model"],
                    "failover_errors": errors,
                    "attempted_models": [item["model"] for item in errors] + [model],
                }
            return result
        except Exception as exc:
            failover_error = is_failover_error(exc)
            if failover_error:
                with _preset_model_cooldown_lock:
                    _preset_model_cooldown[model] = time.monotonic() + PRESET_MODEL_COOLDOWN_SECONDS
            if not failover_error or index == len(models) - 1:
                raise
            errors.append({"model": model, "error": str(exc)[:500]})
    raise RuntimeError("preset role has no available model")


def is_failover_error(exc: BaseException | str) -> bool:
    """True when the failure looks like quota/limit/unavailability (try next model)."""
    text = str(exc or "")
    if not text:
        return False
    if _FAILOVER_ERROR_RE.search(text):
        return True
    # HTTPError often embeds status codes
    code = getattr(exc, "code", None)
    if code in (401, 402, 403, 408, 429, 502, 503, 504):
        return True
    return False


def is_exhaustion_error(exc: BaseException | str) -> bool:
    """True only for limits that should advance a sequential session permanently."""
    text = str(exc or "")
    code = getattr(exc, "code", None)
    return bool(_EXHAUSTION_ERROR_RE.search(text)) or code in (402, 429)


def list_auto_failover_chain(
    snapshot: dict[str, Any],
    *,
    session_id: str | None = None,
    prefer_local: bool = False,
    sequence_mode: str | None = None,
) -> list[dict[str, Any]]:
    """
    Ordered models for Auto mode.

    1. The user's saved priority order (``get_auto_order``); defaults to
       ``HOST_CLI_AUTO_ORDER`` until they save one. Aliases may name host CLIs
       or local models, so "codex → claude → local" is expressible directly.
    2. Any other authenticated host CLI the bridge exposed.
    3. Local Ollama GPU/CPU coding models when no cloud headroom remains.
    """
    models = snapshot.get("models") or {}
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(alias: str, reason: str) -> None:
        if alias in seen:
            return
        meta = models.get(alias) or {}
        if not meta.get("available"):
            return
        seen.add(alias)
        chain.append(
            {
                "model": alias,
                "provider": meta.get("provider"),
                "backend": meta.get("backend"),
                "tier": meta.get("tier"),
                "executor": meta.get("executor") or ("host_cli" if alias.endswith("-cli") else "gateway"),
                "reason": reason,
                "capabilities": list(meta.get("capabilities") or []),
            }
        )

    mode = sequence_mode or get_auto_sequence_mode()
    session_key = str(session_id or "").strip()
    with _auto_session_lock:
        if mode == "sequential_exhaustion" and session_key:
            exhausted = set(_auto_session_exhausted.get(session_key, set()))
            sticky = _auto_session_model.get(session_key)
            if sticky or exhausted:
                _touch_auto_session(session_key)
        else:
            exhausted = set()
            sticky = None
    if sticky and sticky not in exhausted and not prefer_local:
        add(sticky, "sticky session model")

    if not prefer_local:
        for alias in get_auto_order():
            if alias not in exhausted:
                add(alias, "authenticated host CLI (user priority order)")
        # Any other host_cli aliases the bridge exposed
        for alias, meta in models.items():
            if alias not in exhausted and meta.get("executor") == "host_cli" and meta.get("available"):
                add(str(alias), "authenticated host CLI")

    for alias in LOCAL_CODING_AUTO_ORDER:
        add(alias, "local Ollama GPU/CPU coding fallback")
    for alias, meta in models.items():
        if meta.get("tier") == "local" and meta.get("available"):
            caps = set(meta.get("capabilities") or [])
            if caps & {"code", "chat", "tools"}:
                add(str(alias), "local Ollama available model")

    return chain


def describe_auto_mode(
    snapshot: dict[str, Any],
    session_id: str | None = None,
    memory_context_kb: Any = None,
) -> dict[str, Any]:
    chain = list_auto_failover_chain(snapshot, session_id=session_id)
    kb = resolve_memory_context_kb(memory_context_kb)
    return {
        "service_id": "auto",
        "label": "Auto",
        "mode": "direct_models",
        "memory": "unified",
        "memory_context_kb": kb,
        "memory_context_options_kb": list(MEMORY_CONTEXT_KB_OPTIONS),
        "memory_context_chars": memory_context_chars(kb),
        "description": (
            "Uses detected host CLI models (Grok/Claude/Codex) as-is with unified memory; "
            "on session/week limits fails over to the next available model; "
            "when no cloud tokens remain, uses local Ollama GPU for coding."
        ),
        "model_chain": chain,
        "primary": (chain[0]["model"] if chain else None),
        "host_cli_count": sum(1 for item in chain if item.get("executor") == "host_cli"),
        "local_count": sum(1 for item in chain if item.get("tier") == "local"),
        "priority_order": get_auto_order(),
        "order": get_auto_order(),
        "priority_default": list(HOST_CLI_AUTO_ORDER),
        "sequence_mode": get_auto_sequence_mode(),
        "sequence_modes": list(AUTO_SEQUENCE_MODES),
    }


def describe_auto_service(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Service-list shape for Auto so every UI treats it as a first-class preset."""
    description = describe_auto_mode(snapshot)
    chain = description["model_chain"]
    agents = [
        {
            "id": f"route-{index + 1}",
            "role": "route",
            "label": f"{index + 1}. {item['model']}",
            "model": item["model"],
            "available": True,
            "provider": item.get("provider"),
            "backend": item.get("backend"),
            "tier": item.get("tier"),
            "needs": ["chat"],
            "missing_capabilities": [],
        }
        for index, item in enumerate(chain)
    ]
    return {
        "id": "auto",
        "label": "Auto",
        "summary": "Continue with one model until its limit, then hand off to the next model and finally local Ollama.",
        "activities": ["continue work", "preserve context", "switch on limits", "finish locally"],
        "accent": "blue",
        "mode": "auto",
        "lean_mode": "balanced",
        "token_saver": False,
        "behavior_source": "",
        "agents": agents,
        "ready": bool(agents),
        "degraded": not bool(agents),
        "available_agents": len(agents),
        "agent_count": len(agents),
        "models": [item["model"] for item in chain],
        "providers": sorted({item.get("provider") for item in chain if item.get("provider")}),
        "backends": sorted({item.get("backend") for item in chain if item.get("backend")}),
        "missing": [],
        "partial": [],
        "verification": "live",
        "sequence_mode": description["sequence_mode"],
        "priority_order": description["priority_order"],
    }


def build_auto_graph(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Editable route graph for Auto's saved model order."""
    description = describe_auto_mode(snapshot)
    aliases = list(description["priority_order"])
    available = snapshot.get("models") or {}
    for item in description["model_chain"]:
        alias = item.get("model")
        if alias and alias not in aliases:
            aliases.append(alias)
    graph_id = "service-auto"
    goal_id = f"{graph_id}-goal"
    output_id = f"{graph_id}-output"
    nodes: list[dict[str, Any]] = [
        {
            "id": goal_id,
            "type": "goal",
            "x": 30,
            "y": 150,
            "data": {"label": "Incoming request", "text": "Auto continuation", "service_id": "auto"},
        }
    ]
    edges: list[dict[str, Any]] = []
    previous = goal_id
    for index, alias in enumerate(aliases):
        meta = available.get(alias) or {}
        node_id = f"{graph_id}-route-{index + 1}"
        nodes.append(
            {
                "id": node_id,
                "type": "route",
                "x": 180 + index * 150,
                "y": 150,
                "data": {
                    "label": f"{index + 1}. {alias}",
                    "model": alias,
                    "tier": meta.get("tier"),
                    "provider": meta.get("provider"),
                    "available": bool(meta.get("available")),
                    "service_id": "auto",
                    "synthetic": False,
                },
            }
        )
        edges.append({"id": f"e-{previous}-{node_id}", "from": previous, "to": node_id, "kind": "data"})
        previous = node_id
    nodes.append(
        {
            "id": output_id,
            "type": "output",
            "x": 210 + len(aliases) * 150,
            "y": 150,
            "data": {"label": "Answer", "service_id": "auto"},
        }
    )
    edges.append({"id": f"e-{previous}-{output_id}", "from": previous, "to": output_id, "kind": "data"})
    return {
        "schema": "aetherstack.graph.v1",
        "id": graph_id,
        "title": "Auto model sequence",
        "service_id": "auto",
        "sequence_mode": description["sequence_mode"],
        "sequence_modes": description["sequence_modes"],
        "nodes": nodes,
        "edges": edges,
        "recursive": False,
        "max_iterations": 1,
        "resolved_models": [item.get("model") for item in description["model_chain"]],
    }


def save_auto_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Persist the connected Goal -> route nodes -> Output ordering."""
    nodes = {str(node.get("id")): node for node in (graph.get("nodes") or []) if node.get("id")}
    goal = next((node for node in nodes.values() if node.get("type") == "goal"), None)
    if not goal:
        raise ValueError("Auto graph requires a Goal node")
    outgoing: dict[str, list[str]] = {}
    for edge in graph.get("edges") or []:
        if edge.get("kind", "data") == "data" and edge.get("from") in nodes and edge.get("to") in nodes:
            outgoing.setdefault(str(edge["from"]), []).append(str(edge["to"]))
    order: list[str] = []
    cursor = str(goal["id"])
    seen = {cursor}
    while True:
        targets = [target for target in outgoing.get(cursor, []) if target not in seen]
        if len(targets) != 1:
            raise ValueError("Auto sequence must be one unambiguous Goal -> models -> Output path")
        cursor = targets[0]
        seen.add(cursor)
        node = nodes[cursor]
        if node.get("type") == "output":
            break
        if node.get("type") != "route":
            raise ValueError("Auto sequence accepts only model route nodes between Goal and Output")
        alias = str((node.get("data") or {}).get("model") or "").strip()
        if not alias:
            raise ValueError("Every Auto route node needs a model")
        if alias not in order:
            order.append(alias)
    if not order:
        raise ValueError("Auto sequence requires at least one model")
    set_auto_order(order, graph.get("sequence_mode"))
    return {"ok": True, "id": "auto", "order": order, "sequence_mode": get_auto_sequence_mode()}


def _auto_memory_block(
    memory: MemoryStore | None,
    session_id: str | None,
    goal: str,
    history: Any,
    context_kb: Any = None,
) -> str:
    """Unified memory surface: session transcript + vector hits, trimmed to context budget."""
    budget = memory_context_chars(context_kb)
    # Reserve ~15% for vector recall; rest for session/history
    session_budget = max(2048, int(budget * 0.85))
    vector_budget = max(1024, budget - session_budget)
    chunks: list[str] = []
    used = 0

    def take(block: str, limit: int) -> str | None:
        nonlocal used
        remaining = budget - used
        if remaining <= 0:
            return None
        piece = _trim_to_budget(block, min(limit, remaining))
        if not piece.strip():
            return None
        used += len(piece)
        return piece

    if memory is not None and session_id:
        try:
            # Scale message count with budget: ~1 msg per 2–4 KiB, capped
            msg_limit = min(200, max(12, resolve_memory_context_kb(context_kb) // 4))
            msgs = memory.get_session(session_id, limit=msg_limit)
            lines = []
            per_msg = max(400, session_budget // max(8, msg_limit))
            for msg in msgs[-msg_limit:]:
                role = str(msg.get("role") or "user")
                content = str(msg.get("content") or "").strip()
                if content:
                    lines.append(f"{role}: {_trim_to_budget(content, per_msg)}")
            if lines:
                block = take("### Session memory\n" + "\n".join(lines), session_budget)
                if block:
                    chunks.append(block)
        except Exception:
            pass
        for ns in ("default", "conversation-index", "project:default"):
            if used >= budget:
                break
            try:
                top_k = min(12, max(3, resolve_memory_context_kb(context_kb) // 128))
                res = memory.search(goal[:500], namespace=ns, top_k=top_k)
                hits = [
                    h for h in (res.get("hits") or [])
                    if float(h.get("score") or 0) >= 0.28 and (h.get("text") or "").strip()
                ]
                if hits:
                    hit_cap = max(300, vector_budget // max(1, len(hits)))
                    body = "\n".join(
                        f"- {_trim_to_budget(str(h.get('text') or ''), hit_cap)}" for h in hits
                    )
                    block = take(f"### Stored memory ({ns})\n{body}", vector_budget)
                    if block:
                        chunks.append(block)
                    break
            except Exception:
                continue
    # Client-supplied history as secondary continuity
    hist = _history_block(history)
    if hist and not any(c.startswith("### Session memory") for c in chunks):
        block = take("### Recent conversation\n" + hist, session_budget)
        if block:
            chunks.append(block)
    return "\n\n".join(chunks).strip()


def execute_auto(
    snapshot: dict[str, Any],
    event: dict[str, Any] | None = None,
    completion: Callable[[dict[str, Any], list[dict[str, Any]] | None], dict[str, Any]] | None = None,
    on_delta: Callable[[str], None] | None = None,
    on_status: Callable[[dict[str, Any]], None] | None = None,
    memory: MemoryStore | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Auto mode: direct model chat (host CLIs as detected) + unified memory + failover.

    Does not run multi-agent service presets. When a model hits session/week/quota
    limits (or is unavailable), tries the next model in the chain. When no
    cloud/subscription models remain, uses local Ollama for coding/chat.
    """
    event = dict(event or {})
    goal = str(event.get("goal") or event.get("prompt") or "").strip()
    if not goal:
        raise ValueError("goal is required")
    if len(goal) > 100_000:
        raise ValueError("goal exceeds 100000 characters")

    sid = str(session_id or event.get("session_id") or event.get("session") or "").strip() or None
    prefer_local = bool(event.get("prefer_local") or event.get("force_local"))
    context_kb = resolve_memory_context_kb(
        event.get("memory_context_kb")
        if event.get("memory_context_kb") is not None
        else event.get("context_kb")
    )
    sequence_mode = str(event.get("sequence_mode") or get_auto_sequence_mode())
    if sequence_mode not in AUTO_SEQUENCE_MODES:
        raise ValueError(f"sequence_mode must be one of: {', '.join(AUTO_SEQUENCE_MODES)}")
    chain = list_auto_failover_chain(
        snapshot,
        session_id=sid,
        prefer_local=prefer_local,
        sequence_mode=sequence_mode,
    )
    if not chain:
        raise ValueError(
            "no models available for Auto mode — authenticate a host CLI (Grok/Claude/Codex) "
            "or start local Ollama with a chat/code model"
        )

    mem_block = _auto_memory_block(memory, sid, goal, event.get("history"), context_kb=context_kb)
    system = (
        "You are AetherStack Auto. Answer the user directly, the same way native "
        "Grok, Claude, or Codex chat would. Shared memory may appear below — use it "
        "when relevant. Do not mention agents, orchestration, failover, or which "
        "model is running unless the user asks."
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    if mem_block:
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Unified memory context ({context_kb} KiB budget, "
                    f"{len(mem_block)} chars used):\n{mem_block}"
                ),
            }
        )
        messages.append({"role": "assistant", "content": "Understood. I'll use relevant memory when helpful."})
    messages.append({"role": "user", "content": goal})

    # Attachments (vision/PDF) on final user turn when present
    attachments = [item for item in (event.get("attachments") or []) if isinstance(item, dict)]
    if attachments:
        tmp_call = {"model": chain[0]["model"], "max_tokens": 2000}
        _augment_final_message_with_attachments(messages, attachments, snapshot, tmp_call)

    completion = completion or _chat_completion
    attempts: list[dict[str, Any]] = []
    last_error: str | None = None
    chain_models = [item["model"] for item in chain]

    _emit_status(
        on_status,
        "auto_chain",
        model=chain_models[0],
        models=chain_models,
        label=f"Auto · {len(chain_models)} models ready…",
    )

    for index, item in enumerate(chain):
        model = item["model"]
        host = item.get("executor") == "host_cli" or _is_host_cli(snapshot, model)
        label = f"{'CLI' if host else 'Local'} · {model}"
        _emit_status(on_status, "answering", model=model, models=chain_models, label=f"Using {model}…")
        call = {"model": model, "max_tokens": int(event.get("max_tokens") or 2000), "role": "auto"}
        try:
            streamed_chunks: list[str] = []
            streamed_result = None
            if on_delta is not None and not host:
                streamed_result = _chat_completion_stream(call, messages, streamed_chunks.append)
                result = streamed_result
            else:
                result = completion(call, messages)
            text = str(result.get("content") or "")
            if final_output_needs_correction(text):
                correction_messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "Do the bounded work now. Replace intent or promises with the actual answer, concrete "
                            "findings, evidence, and verification requested by the user. Do not expose internal drafts."
                        ),
                    },
                ]
                result = completion(call, correction_messages)
                text = str(result.get("content") or "")
            if final_output_needs_correction(text):
                raise RuntimeError(f"{model} returned intent-to-work instead of a completed answer")
            if on_delta is not None:
                if result is streamed_result:
                    for chunk in streamed_chunks:
                        on_delta(chunk)
                elif text:
                    on_delta(text)
            answer = str(result.get("content") or "").strip()
            if not answer:
                raise RuntimeError(f"{model} returned an empty answer")
            if sid and sequence_mode == "sequential_exhaustion":
                with _auto_session_lock:
                    _auto_session_model[sid] = model
                    _touch_auto_session(sid)
            if memory is not None and sid:
                try:
                    memory.append_message(sid, "user", goal, meta={"auto": True})
                    memory.append_message(
                        sid,
                        "assistant",
                        answer,
                        meta={"auto": True, "model": model, "executor": item.get("executor")},
                    )
                except Exception:
                    pass
            return {
                "ok": True,
                "service_id": "auto",
                "auto_mode": True,
                "answer": answer,
                "model": result.get("model") or model,
                "executor": item.get("executor"),
                "tier": item.get("tier"),
                "usage": result.get("usage") or {},
                "model_chain": chain_models,
                "failover_attempts": attempts,
                "attempt_index": index,
                "memory": "unified",
                "sequence_mode": sequence_mode,
                "memory_context_kb": context_kb,
                "memory_chars_used": len(mem_block) if mem_block else 0,
                "selection": {
                    "service_id": "auto",
                    "label": "Auto",
                    "confidence": "direct",
                    "source": "auto-direct-models",
                    "model": model,
                    "model_chain": chain_models,
                    "memory_context_kb": context_kb,
                },
                "agents": [
                    {
                        "id": "auto",
                        "role": "auto",
                        "label": "Auto",
                        "model": model,
                        "available": True,
                        "provider": item.get("provider"),
                        "backend": item.get("backend"),
                        "tier": item.get("tier"),
                    }
                ],
            }
        except Exception as exc:
            last_error = str(exc)[:500]
            fail_kind = "limit_or_unavailable" if is_failover_error(exc) else "error"
            if sid and sequence_mode == "sequential_exhaustion" and is_exhaustion_error(exc):
                with _auto_session_lock:
                    _auto_session_exhausted.setdefault(sid, set()).add(model)
                    if _auto_session_model.get(sid) == model:
                        _auto_session_model.pop(sid, None)
                    _touch_auto_session(sid)
            attempts.append(
                {
                    "model": model,
                    "executor": item.get("executor"),
                    "error": last_error,
                    "kind": fail_kind,
                }
            )
            _emit_status(
                on_status,
                "failover",
                model=model,
                models=chain_models,
                label=f"{model} failed · next…",
            )
            # Non-failover hard errors still try next model in Auto (resilience),
            # but only when more models remain.
            if index >= len(chain) - 1:
                break
            continue

    raise RuntimeError(
        "Auto mode exhausted all models "
        f"(tried {len(attempts)}): {last_error or 'unknown error'}. "
        "Re-authenticate a host CLI or pull a local Ollama coding model."
    )


_INTENT_ONLY_RE = re.compile(
    r"\b(i(?:'ll| will| am going to)|let me|next i|i can|will inspect|will verify|will investigate|will check)\b",
    re.IGNORECASE,
)
_EVIDENCE_RE = re.compile(
    r"(?:[/\\][\w.-]+|\b[\w.-]+\.(?:py|js|ts|html|css|yaml|yml|json|md|sh|go|rs|java|cpp|h)\b|"
    r"\b(?:observed|evidence|result|output|source|assumption|inference|reproduced|tested|line|symbol|function|class)\b)",
    re.IGNORECASE,
)
_LINE_CITATION_RE = re.compile(
    r"(?P<path>[\w./\\-]+\.(?:py|js|ts|html|css|yaml|yml|json|md|sh|go|rs|java|cpp|h))"
    r"[,:\s]*\bline\s+\d+",
    re.IGNORECASE,
)


def _has_verifiable_citation(text: str) -> bool:
    """A "path.py line N"-style claim must point at a real file; an illustrative or
    plain evidence-shaped mention (no specific line claim) is left to the broader check."""
    fabricated = False
    for match in _LINE_CITATION_RE.finditer(text):
        candidate = match.group("path").strip("/\\.,;:()[]{}\"'")
        if not candidate:
            continue
        if (ROOT / candidate).exists() or (ROOT.parent / candidate).exists() or Path(candidate).exists():
            return True
        fabricated = True
    return not fabricated
_COMPLETED_WORK_RE = re.compile(
    r"\b(?:observed|found|checked|verified|ran|tested|reproduced|shows?|contains?|fails?|passes?|line\s+\d+)\b",
    re.IGNORECASE,
)
_FUTURE_WORK_OPENING_RE = re.compile(
    r"^\s*(?:#{1,6}[^\n]*\n+\s*)*(?:to\s+(?:begin|start)|i(?:'ve| have)\s+(?:begun|started)|"
    r"i(?:'ll| will| am going to)|let me)\b",
    re.IGNORECASE,
)
_INTERNAL_PROCESS_RE = re.compile(
    r"\b(?:internal draft|internal supporting material|internal quality notes)\s*:",
    re.IGNORECASE,
)


def final_output_needs_correction(content: Any) -> bool:
    """Keep plans and internal orchestration transcripts out of final answers."""
    text = str(content or "").strip()
    if not text:
        return True
    if _FUTURE_WORK_OPENING_RE.search(text) or _INTERNAL_PROCESS_RE.search(text):
        return True
    return bool(_INTENT_ONLY_RE.search(text)) and not bool(_COMPLETED_WORK_RE.search(text))


def worker_output_needs_correction(content: Any) -> bool:
    """Reject worker placeholders before they can masquerade as useful team work."""
    text = str(content or "").strip()
    if len(text) < 120:
        return True
    if not _EVIDENCE_RE.search(text):
        return True
    if not _has_verifiable_citation(text):
        return True
    if _INTENT_ONLY_RE.search(text) and "\n" not in text:
        return True
    return bool(_INTENT_ONLY_RE.search(text)) and not bool(_COMPLETED_WORK_RE.search(text))


def execute_service(
    service_id: str,
    snapshot: dict[str, Any],
    event: dict[str, Any] | None = None,
    completion: Callable[[dict[str, Any], list[dict[str, Any]] | None], dict[str, Any]] | None = None,
    on_delta: Callable[[str], None] | None = None,
    on_status: Callable[[dict[str, Any]], None] | None = None,
    memory: MemoryStore | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Execute a bounded lead -> workers -> review -> synthesis service run.

    `memory`/`session_id`, when supplied, make a model switch mid-conversation carry
    real context: the server-stored session transcript (not just what the client echoes
    back) plus the previous turn's written reasoning (lead plan + review notes) are fed
    to whichever model runs this turn. That written-reasoning handoff is the only channel
    that exists between two different model providers — no provider API exposes hidden
    states / KV-cache, and they're architecture-specific even when it's the same provider,
    so there is no lower-level state to transfer.

    `on_status` reports short phase/model updates so clients can show progress before
    the final answer tokens stream (lead/workers/review can take a long time).
    """
    run_started = time.perf_counter()
    timings_ms: dict[str, int] = {}
    event = dict(event or {})
    goal = str(event.get("goal") or event.get("prompt") or "").strip()
    if not goal:
        raise ValueError("goal is required")
    if len(goal) > 100_000:
        raise ValueError("goal exceeds 100000 characters")
    completion = completion or _chat_completion
    _emit_status(on_status, "planning", label="Planning…")
    plan = plan_service(service_id, snapshot, event)
    activation = _activate_resolved_service(plan["service"], event)
    calls = plan.get("litellm_calls") or []
    if any(call.get("workspace_write") for call in calls) and not event.get("_workspace_write_authorized"):
        raise PermissionError("workspace-write execution requires trusted local authorization")
    lead_call = next((call for call in calls if call.get("role") == "mastermind"), None)
    supervisor_call = next((call for call in calls if call.get("role") == "supervisor"), None)
    worker_calls = [call for call in calls if call.get("role") == "worker"][:6]
    if not lead_call or not lead_call.get("model"):
        raise ValueError("no available lead model for this service")

    planned_models = []
    for call in [lead_call, *worker_calls, supervisor_call]:
        if call and call.get("model") and call.get("model") not in planned_models:
            planned_models.append(call.get("model"))
    _emit_status(
        on_status,
        "planned",
        model=lead_call.get("model"),
        models=planned_models,
        label="Team ready…",
    )

    session_history = None
    if memory is not None and session_id:
        try:
            session_history = memory.get_session(session_id, limit=60)
        except Exception:
            session_history = None
    history = _history_block(_merge_history(session_history, event.get("history")))
    handoff_context = _load_handoff_context(memory, session_id, lead_call.get("model"))
    xref_block = _auto_pull_xref(memory, goal)

    # Preset-level Memory node (tree/project/global — same pool and namespace
    # resolution as the freeform canvas's Memory nodes, see graph.py). Only
    # presets whose graph has been saved with a memory node carry this.
    memory_ops = _service_memory_ops(service_id, plan.get("service") or {})
    memory_block = ""
    if any(op.get("action") == "search" for op in memory_ops):
        from graph_exec import _memory_reads

        _emit_status(on_status, "memory", label="Memory…")
        memory_block = _memory_reads(memory, memory_ops, goal)
        _emit_status(on_status, "memory_done", label="Memory done…")

    lead_messages = copy.deepcopy(lead_call.get("messages") or [])
    if history:
        lead_messages.append({"role": "user", "content": f"Recent conversation:\n{history}"})
    if handoff_context:
        lead_messages.append({"role": "user", "content": handoff_context})
    if xref_block:
        lead_messages.append({"role": "user", "content": xref_block})
    if memory_block:
        lead_messages.append({"role": "user", "content": memory_block})
    lead_messages.append(
        {
            "role": "user",
            "content": (
                "Quality contract: inspect the available implementation or supplied material before concluding. "
                "Use concrete evidence such as file paths, symbols, commands, observed output, source links, or explicit "
                "assumptions. Delegate checks that can falsify the draft. For analysis/review requests, identify weak "
                "spots, behavioral risks, and missing verification rather than returning a component inventory. "
                + lead_work_packet_instruction()
            ),
        }
    )
    lead_started = time.perf_counter()
    _emit_status(on_status, "lead", model=lead_call.get("model"), label="Lead…")
    try:
        lead = _complete_with_preset_failover(completion, lead_call, lead_messages)
    except Exception:
        _emit_status(on_status, "lead_error", model=lead_call.get("model"), label="Lead failed")
        raise
    _emit_status(on_status, "lead_done", model=lead.get("model") or lead_call.get("model"), label="Lead done…")
    timings_ms["lead"] = round((time.perf_counter() - lead_started) * 1000)

    lead_packet = parse_work_packet(lead.get("content") or "", goal=goal, default_owner="lead")
    lead_packet = ensure_partitions(lead_packet, worker_calls, goal=goal)
    team_packet = copy.deepcopy(lead_packet)

    def run_worker(index_call: tuple[int, dict[str, Any]]) -> dict[str, Any]:
        index, call = index_call
        task_id = str(call.get("task_id") or f"worker-{index + 1}")
        partition = partition_for_worker(lead_packet, task_id, index)
        messages = copy.deepcopy(call.get("messages") or [])
        # Partition-scoped brief: avoid replaying the full lead essay (token overlap).
        messages.append(
            {
                "role": "user",
                "content": worker_work_packet_instruction(partition, lead_packet),
            }
        )
        try:
            result = _complete_with_preset_failover(completion, call, messages)
            if worker_output_needs_correction(result.get("content")):
                first_usage = result.get("usage") or {}
                first_failover = {
                    key: copy.deepcopy(result.get(key))
                    for key in ("failover_from", "failover_errors", "attempted_models")
                    if result.get(key) is not None
                }
                attempted = set(result.get("attempted_models") or [])
                retry_call = {
                    **call,
                    "model": result.get("model") or call.get("model"),
                    "fallback_chain": [
                        model for model in (call.get("fallback_chain") or []) if model not in attempted
                    ],
                }
                retry_messages = copy.deepcopy(messages)
                retry_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "That response described intended work without sufficient evidence. Perform the bounded check "
                            "now and replace it with findings for your partition only. Include concrete references or observed "
                            "results; clearly mark anything that remains an inference. Prefer a Work Packet JSON claims list."
                        ),
                    }
                )
                result = _complete_with_preset_failover(completion, retry_call, retry_messages)
                for key, value in first_failover.items():
                    result.setdefault(key, value)
                retry_usage = result.get("usage") or {}
                result["usage"] = {
                    key: int(first_usage.get(key) or 0) + int(retry_usage.get(key) or 0)
                    for key in set(first_usage) | set(retry_usage)
                }
                if worker_output_needs_correction(result.get("content")):
                    attempted_models = set(result.get("attempted_models") or [])
                    attempted_models.add(str(result.get("model") or call.get("model") or ""))
                    alternatives = [
                        model for model in (call.get("fallback_chain") or []) if model not in attempted_models
                    ]
                    if alternatives:
                        quality_call = {
                            **call,
                            "model": alternatives[0],
                            "fallback_chain": alternatives,
                        }
                        replacement = _complete_with_preset_failover(
                            completion,
                            quality_call,
                            retry_messages,
                        )
                        replacement_usage = replacement.get("usage") or {}
                        prior_usage = result.get("usage") or {}
                        replacement["usage"] = {
                            key: int(prior_usage.get(key) or 0) + int(replacement_usage.get(key) or 0)
                            for key in set(prior_usage) | set(replacement_usage)
                        }
                        result["usage"] = replacement["usage"]
                        if not worker_output_needs_correction(replacement.get("content")):
                            replacement.setdefault("failover_from", result.get("model") or call.get("model"))
                            replacement.setdefault(
                                "failover_errors",
                                [{"model": str(result.get("model") or call.get("model")), "error": "insufficient evidence after correction"}],
                            )
                            replacement.setdefault(
                                "attempted_models",
                                [*attempted_models, replacement.get("model")],
                            )
                            result = replacement
                    if worker_output_needs_correction(result.get("content")):
                        # Keep an explicit open claim so the gap is visible (not silence).
                        fail_packet = worker_failure_claim(
                            task_id,
                            "worker output rejected after fallback produced insufficient evidence",
                            goal=goal,
                        )
                        result = {
                            **result,
                            "content": format_packet_compact(fail_packet, max_chars=2000),
                            "work_packet": fail_packet,
                            "error": "worker output rejected after fallback produced insufficient evidence",
                            "quality_warning": "worker returned insufficient evidence after correction and fallback",
                        }
            if "work_packet" not in result:
                result["work_packet"] = parse_work_packet(
                    result.get("content") or "",
                    goal=goal,
                    default_owner=task_id,
                )
            return {"ok": True, "role": "worker", "task_id": task_id, "partition": partition, **result}
        except Exception as exc:
            fail_packet = worker_failure_claim(task_id, str(exc)[:300], goal=goal)
            return {
                "ok": False,
                "role": "worker",
                "task_id": task_id,
                "model": call.get("model"),
                "error": str(exc)[:500],
                "content": format_packet_compact(fail_packet, max_chars=2000),
                "work_packet": fail_packet,
                "partition": partition,
            }

    workers = []
    if worker_calls:
        workers_started = time.perf_counter()
        worker_models = [c.get("model") for c in worker_calls if c.get("model")]
        _emit_status(
            on_status,
            "workers",
            model=worker_models[0] if worker_models else None,
            models=worker_models,
            label="Team…",
        )
        with ThreadPoolExecutor(max_workers=len(worker_calls)) as pool:
            workers = list(pool.map(run_worker, list(enumerate(worker_calls))))
        _emit_status(
            on_status,
            "workers_done",
            model=worker_models[0] if worker_models else None,
            models=worker_models,
            label="Team done…",
        )
        timings_ms["workers"] = round((time.perf_counter() - workers_started) * 1000)

    worker_packets = [item.get("work_packet") for item in workers if item.get("work_packet")]
    team_packet = merge_packets(lead_packet, *worker_packets, goal=goal)
    gaps = coverage_gaps(team_packet)
    if gaps:
        team_packet = force_open_claims_for_gaps(team_packet, gaps)
    worker_text = claims_table(team_packet, max_chars=12000)
    if not worker_text.strip() or worker_text.startswith("Claim id |"):
        # claims_table always has header; append raw worker prose tails for residual context.
        prose_bits = "\n\n".join(
            f"[{item.get('task_id') or 'worker'} / {item.get('model')}]\n{(item.get('content') or item.get('error') or '')[:4000]}"
            for item in workers
        )[-16000:]
        if prose_bits.strip():
            worker_text = f"{worker_text}\n\n### Worker notes\n{prose_bits}"

    review = None
    if supervisor_call and supervisor_call.get("model"):
        review_started = time.perf_counter()
        _emit_status(on_status, "review", model=supervisor_call.get("model"), label="Review…")
        review_messages = copy.deepcopy(supervisor_call.get("messages") or [])
        review_messages.append(
            {
                "role": "user",
                "content": review_work_packet_instruction(team_packet, gaps),
            }
        )
        try:
            review = _complete_with_preset_failover(completion, supervisor_call, review_messages)
        except Exception as exc:
            review = {"model": supervisor_call.get("model"), "content": "", "error": str(exc)[:500], "usage": {}}
        review_phase = "review_error" if review.get("error") else "review_done"
        _emit_status(on_status, review_phase, model=(review or {}).get("model") or supervisor_call.get("model"), label="Review failed" if review.get("error") else "Review done…")
        timings_ms["review"] = round((time.perf_counter() - review_started) * 1000)

    final_call = dict(lead_call)
    final_call["max_tokens"] = lead_call.get("max_tokens") or 2000
    final_messages = [
        {
            "role": "system",
            "content": (
                "You are AetherStack, an interactive coding and project copilot. Return only the final user-facing answer. "
                "Use the supplied internal material silently: never mention a lead, plan, worker, reviewer, supervisor, agent, "
                "orchestration, subtask, provided material, approval, or synthesis. Do not narrate that work is complete or announce "
                "what you will do next. Follow the requested format and length exactly; do not grade your own answer, explain that "
                "it is concise, or append a follow-up question. Code must be minimal and complete, with no undeclared names or "
                "placeholder logic. Answer the original goal directly with the requested explanation, code, design, decision, "
                "or concrete action. Ask one focused question only when missing information truly blocks a useful answer. Resolve "
                "conflicts and state only uncertainty that matters to the user."
                " Apply valid reviewer corrections and omit unsupported worker claims. Prefer evidence-backed findings "
                "over inventories or generic best practices. Cite claim ids like [C1] when you rely on the Work Packet."
            ),
        },
        {
            "role": "user",
            "content": final_work_packet_instruction(
                goal,
                team_packet,
                (review or {}).get("content", "") or "",
            ),
        },
    ]
    attachments = [item for item in (event.get("attachments") or []) if isinstance(item, dict)]
    _augment_final_message_with_attachments(final_messages, attachments, snapshot, final_call)
    final_started = time.perf_counter()
    _emit_status(on_status, "answering", model=final_call.get("model"), label="on it..")
    honest_incomplete = False
    try:
        streamed_chunks: list[str] = []
        streamed_final = None
        if on_delta is not None and not _is_host_cli(snapshot, final_call.get("model")):
            try:
                streamed_final = _chat_completion_stream(final_call, final_messages, streamed_chunks.append)
                final = streamed_final
            except Exception as exc:
                if not is_failover_error(exc):
                    raise
                final = _complete_with_preset_failover(completion, final_call, final_messages)
        else:
            final = _complete_with_preset_failover(completion, final_call, final_messages)
        final_text = str(final.get("content") or "")
        if final_output_needs_correction(final_text):
            correction_messages = [
                *final_messages,
                {
                    "role": "user",
                    "content": (
                        "Your response only promised future work. Perform the bounded synthesis now and return the actual "
                        "answer with concrete findings and verification. Cite claim ids. If evidence is insufficient, return "
                        "an honest incomplete report of open claims instead of promising more inspection."
                    ),
                },
            ]
            corrected_call = {**final_call, "model": final.get("model") or final_call.get("model")}
            corrected = _complete_with_retry(completion, corrected_call, correction_messages)
            corrected_text = str(corrected.get("content") or "")
            if final_output_needs_correction(corrected_text):
                alternatives = [
                    model for model in (final_call.get("fallback_chain") or [])
                    if model != corrected_call["model"]
                ]
                if alternatives:
                    corrected = _complete_with_preset_failover(
                        completion,
                        {**final_call, "model": alternatives[0], "fallback_chain": alternatives},
                        correction_messages,
                    )
                    corrected_text = str(corrected.get("content") or "")
                if final_output_needs_correction(corrected_text):
                    # Honest incomplete instead of opaque hard-fail / intent loop.
                    incomplete = honest_incomplete_answer(
                        goal,
                        team_packet,
                        extra_reasons=["final synthesis remained intent-only after correction and fallback"],
                    )
                    corrected = {
                        **(corrected if isinstance(corrected, dict) else {}),
                        "model": (corrected or {}).get("model") or final.get("model") or final_call.get("model"),
                        "content": incomplete,
                        "usage": (corrected or {}).get("usage") or {},
                    }
                    honest_incomplete = True
                    corrected_text = incomplete
            corrected.setdefault("failover_from", final.get("model") or final_call.get("model"))
            corrected.setdefault(
                "failover_errors",
                [{"model": str(final.get("model") or final_call.get("model")), "error": "intent-only final synthesis"}],
            )
            corrected.setdefault(
                "attempted_models",
                [final.get("model") or final_call.get("model"), corrected.get("model")],
            )
            final = corrected
        # Do not overwrite a final answer that already passed quality gates just
        # because workers were degraded — that is reported via degraded_reasons.
        if on_delta is not None:
            if final is streamed_final and not honest_incomplete:
                for chunk in streamed_chunks:
                    on_delta(chunk)
            else:
                on_delta(final.get("content") or "")
    except Exception:
        _emit_status(on_status, "answering_error", model=final_call.get("model"), label="Answer failed")
        raise
    _emit_status(on_status, "answering_done", model=final.get("model") or final_call.get("model"), label="Answer ready")
    timings_ms["answering"] = round((time.perf_counter() - final_started) * 1000)
    if any(op.get("action") == "store" for op in memory_ops):
        from graph_exec import _memory_writes

        _emit_status(on_status, "memory_store", label="Storing memory…")
        _memory_writes(memory, memory_ops, goal, final.get("content") or "")
        _emit_status(on_status, "memory_store_done", label="Memory stored…")
    steps = [
        {"role": "lead-plan", **lead, "work_packet": lead_packet},
        *workers,
    ]
    if review:
        steps.append({"role": "review", **review})
    handoff_blob = (
        f"{(lead.get('content') or '')[:4000]}\n\nWork Packet:\n{format_packet_compact(team_packet, max_chars=3500)}"
    )
    _store_handoff_context(
        memory,
        session_id,
        service_id,
        lead_call.get("model"),
        goal,
        handoff_blob,
        (review or {}).get("content"),
    )
    usage_items = [lead.get("usage") or {}, final.get("usage") or {}]
    usage_items.extend(item.get("usage") or {} for item in workers)
    if review:
        usage_items.append(review.get("usage") or {})
    usage = {
        key: sum(int(item.get(key) or 0) for item in usage_items)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    degraded_reasons = [
        f"{item.get('task_id') or 'worker'}: {item.get('error') or item.get('quality_warning')}"
        for item in workers
        if not item.get("ok") or item.get("error") or item.get("quality_warning")
    ]
    degraded_reasons.extend(gaps)
    if review and review.get("error"):
        degraded_reasons.append(f"review: {review['error']}")
    if honest_incomplete:
        degraded_reasons.append("final: honest incomplete (insufficient supported claims)")
    failovers = [
        {
            "role": item.get("role"),
            "model": item.get("model"),
            "failover_from": item.get("failover_from"),
            "attempted_models": item.get("attempted_models"),
            "errors": item.get("failover_errors") or [],
        }
        for item in [steps[0], *workers, *([review] if review else []), {"role": "answering", **final}]
        if item.get("failover_from")
    ]
    timings_ms["total"] = round((time.perf_counter() - run_started) * 1000)
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
        "degraded": bool(degraded_reasons),
        "degraded_reasons": degraded_reasons,
        "failovers": failovers,
        "timings_ms": timings_ms,
        "work_packet": team_packet,
        "honest_incomplete": honest_incomplete,
    }
