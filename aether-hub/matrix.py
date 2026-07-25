"""Capability / routing sync matrix — load YAML, probe liveness, route."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
DEFAULT_MATRIX = ROOT / "capability_matrix.yaml"


def load_matrix(path: Path | None = None) -> dict[str, Any]:
    p = path or Path(os.environ.get("AETHER_MATRIX_PATH", str(DEFAULT_MATRIX)))
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "models" not in data:
        raise ValueError(f"invalid matrix file: {p}")
    return expand_multi_key_models(data)


def expand_multi_key_models(matrix: dict[str, Any]) -> dict[str, Any]:
    """
    Synthesize -personal / -enterprise aliases for every cloud model that has
    requires_env like ANTHROPIC_API_KEY → ANTHROPIC_API_KEY_PERSONAL / _ENTERPRISE.
    Primary alias keeps {PROVIDER}_API_KEY. Both keys can be live at once.
    """
    models = dict(matrix.get("models") or {})
    extra: dict[str, Any] = {}
    for name, meta in list(models.items()):
        if not isinstance(meta, dict):
            continue
        if meta.get("tier") == "local":
            continue
        if meta.get("key_slot"):
            continue  # already a slot variant
        req = meta.get("requires_env")
        if not req or not str(req).endswith("_API_KEY"):
            continue
        base_env = str(req)
        for slot, suf in (("personal", "_PERSONAL"), ("enterprise", "_ENTERPRISE")):
            alias = f"{name}-{slot}"
            if alias in models or alias in extra:
                continue
            m = dict(meta)
            m["requires_env"] = base_env + suf
            m["key_slot"] = slot
            m["parent_alias"] = name
            m["notes"] = (
                (m.get("notes") or "")
                + f" Key slot={slot} ({base_env}{suf})."
            ).strip()
            extra[alias] = m
    if extra:
        models.update(extra)
        matrix = dict(matrix)
        matrix["models"] = models
    return matrix


def _http_json(url: str, timeout: float = 3.0, headers: dict | None = None) -> Any | None:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def probe_ollama(base: str | None = None) -> dict[str, Any]:
    base = (base or os.environ.get("OLLAMA_BASE_URL") or "http://host.docker.internal:11434").rstrip(
        "/"
    )
    tags = _http_json(f"{base}/api/tags", timeout=4.0)
    names: set[str] = set()
    if tags and isinstance(tags.get("models"), list):
        for m in tags["models"]:
            n = m.get("name") or m.get("model")
            if n:
                names.add(n)
                # also bare name without tag
                if ":" in n:
                    names.add(n.split(":", 1)[0])
    return {"base": base, "ok": tags is not None, "models": sorted(names)}


def env_key_present(name: str | list[str] | None) -> bool:
    """True if env var is set, or any of a list (requires_any_env style)."""
    if not name:
        return True
    if isinstance(name, (list, tuple)):
        return any(env_key_present(n) for n in name)
    v = os.environ.get(str(name), "").strip()
    return bool(v)


def backend_local_name(backend: str) -> str | None:
    """ollama/llama3.1:8b → llama3.1:8b"""
    if not backend:
        return None
    if backend.startswith("ollama/"):
        return backend[len("ollama/") :]
    return None


def annotate_availability(matrix: dict[str, Any], ollama: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a deep-ish copy of matrix with live availability fields."""
    ollama = ollama or probe_ollama()
    models_out: dict[str, Any] = {}
    local_online = 0
    cloud_ready = 0
    offline = 0

    for name, meta in (matrix.get("models") or {}).items():
        m = dict(meta)
        tier = m.get("tier", "unknown")
        req = m.get("requires_env")
        available = False
        reason = ""

        if tier == "local":
            bn = backend_local_name(m.get("backend") or "")
            pulled = False
            if bn and ollama.get("ok"):
                if bn in ollama["models"] or bn.split(":")[0] in ollama["models"]:
                    pulled = True
            if not ollama.get("ok"):
                reason = "ollama unreachable"
            elif not pulled:
                reason = f"not pulled ({bn}); ollama pull {bn}"
            else:
                available = True
                reason = "ollama ready"
            if available:
                local_online += 1
            else:
                offline += 1
        else:
            if env_key_present(req):
                available = True
                reason = f"env {req} set" if req else "no key required"
                cloud_ready += 1
            else:
                reason = f"missing env {req}"
                offline += 1

        m["available"] = available
        m["availability_reason"] = reason
        m["alias"] = name
        models_out[name] = m

    # Capability coverage matrix: capability → {local: [...], cloud: [...]}
    caps: dict[str, dict[str, list[str]]] = {}
    for cap in matrix.get("capabilities") or {}:
        caps[cap] = {"local": [], "cloud": [], "any_available": []}
    for name, m in models_out.items():
        for cap in m.get("capabilities") or []:
            if cap not in caps:
                caps[cap] = {"local": [], "cloud": [], "any_available": []}
            bucket = "local" if m.get("tier") == "local" else "cloud"
            caps[cap][bucket].append(name)
            if m.get("available"):
                caps[cap]["any_available"].append(name)

    snapshot = {
        "version": matrix.get("version"),
        "ts": time.time(),
        "ollama": ollama,
        "models": models_out,
        "capabilities": matrix.get("capabilities") or {},
        "capability_index": caps,
        "routing": matrix.get("routing") or {},
        "summary": {
            "models_total": len(models_out),
            "local_online": local_online,
            "cloud_ready": cloud_ready,
            "unavailable": offline,
        },
    }
    return snapshot


def _score_model(meta: dict[str, Any], needs: set[str], prefer: str | None) -> float:
    if not meta.get("available"):
        return -1e9
    caps = set(meta.get("capabilities") or [])
    if needs and not needs.issubset(caps):
        # partial credit if intersection
        if not (needs & caps):
            return -1e8
        score = 10.0 * len(needs & caps)
    else:
        score = 100.0 + 10.0 * len(needs)

    tier = meta.get("tier")
    if prefer == "local" and tier == "local":
        score += 50
    if prefer == "cloud" and tier == "cloud":
        score += 50
    if prefer == "auto":
        # prefer local for private/cheap/fast needs
        if needs & {"private", "cheap"} and tier == "local":
            score += 40
        if needs & {"vision", "reason", "long_context"} and tier == "cloud":
            score += 30

    cost = {"0": 20, 0: 20, "low": 15, "medium": 5, "high": 0, "very_high": -10}.get(
        meta.get("cost", "medium"), 5
    )
    score += cost
    lat = {"very_low": 15, "low": 10, "medium": 5, "high": 0}.get(meta.get("latency", "medium"), 5)
    score += lat
    return score


def route(
    snapshot: dict[str, Any],
    need: list[str] | None = None,
    prefer: str | None = "auto",
) -> dict[str, Any]:
    needs = set(n.strip() for n in (need or ["chat"]) if n and n.strip())
    prefer = (prefer or "auto").lower()
    models = snapshot.get("models") or {}
    routing = snapshot.get("routing") or {}

    ranked: list[tuple[float, str, dict]] = []
    for name, meta in models.items():
        s = _score_model(meta, needs, prefer)
        ranked.append((s, name, meta))
    ranked.sort(key=lambda x: x[0], reverse=True)

    primary = None
    alternatives: list[dict[str, Any]] = []
    for s, name, meta in ranked:
        if s < 0:
            continue
        entry = {
            "model": name,
            "score": round(s, 2),
            "tier": meta.get("tier"),
            "capabilities": meta.get("capabilities"),
            "reason": meta.get("availability_reason"),
            "available": True,
        }
        if primary is None:
            primary = entry
        else:
            alternatives.append(entry)
        if len(alternatives) >= 5:
            break

    # Fallback chain from YAML if primary missing
    if primary is None:
        for cap in needs:
            chain = (routing.get("fallbacks") or {}).get(cap) or []
            for alias in chain:
                meta = models.get(alias)
                if meta and meta.get("available"):
                    primary = {
                        "model": alias,
                        "score": 0,
                        "tier": meta.get("tier"),
                        "capabilities": meta.get("capabilities"),
                        "reason": "yaml fallback chain",
                        "available": True,
                    }
                    break
            if primary:
                break

    # Still recommend a model offline (planning / "what should I enable")
    offline_plan = None
    if primary is None:
        planned: list[tuple[float, str, dict]] = []
        for name, meta in models.items():
            caps = set(meta.get("capabilities") or [])
            if needs and not (needs & caps):
                continue
            # reuse scorer with a fake available flag
            fake = dict(meta)
            fake["available"] = True
            planned.append((_score_model(fake, needs, prefer), name, meta))
        planned.sort(key=lambda x: x[0], reverse=True)
        if planned:
            _, name, meta = planned[0]
            offline_plan = {
                "model": name,
                "score": 0,
                "tier": meta.get("tier"),
                "capabilities": meta.get("capabilities"),
                "reason": meta.get("availability_reason") or "offline plan",
                "available": False,
            }
            primary = offline_plan

    return {
        "need": sorted(needs),
        "prefer": prefer,
        "primary": primary,
        "alternatives": alternatives,
        "offline_plan": offline_plan is not None,
        "litellm_model": (primary or {}).get("model"),
        "hint": (
            (
                f"Enable model first: {(primary or {}).get('reason')}. "
                f"Then POST :4000/v1/chat/completions model={(primary or {}).get('model')!r}"
            )
            if primary and not primary.get("available", True)
            else (
                f"POST http://127.0.0.1:4000/v1/chat/completions with model="
                f"{(primary or {}).get('model')!r}"
                if primary
                else "No model matches; extend capability_matrix.yaml."
            )
        ),
    }


def matrix_table(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Flat rows for UI / docs: model × key caps."""
    cap_names = list((snapshot.get("capabilities") or {}).keys()) or [
        "chat",
        "code",
        "reason",
        "vision",
        "tools",
        "embed",
        "private",
    ]
    rows = []
    for name, m in (snapshot.get("models") or {}).items():
        caps = set(m.get("capabilities") or [])
        row = {
            "model": name,
            "tier": m.get("tier"),
            "available": m.get("available"),
            "provider": m.get("provider"),
            "cost": m.get("cost"),
            "latency": m.get("latency"),
        }
        for c in cap_names:
            row[c] = c in caps
        rows.append(row)
    rows.sort(key=lambda r: (0 if r["tier"] == "local" else 1, r["model"]))
    return rows
