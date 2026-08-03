"""GDPR-compliant mode: operator-configurable settings, consent, export, and
real erasure.

AetherStack is self-hosted; the GDPR controller/processor is whoever deploys
it, not this codebase. This module does not itself guarantee legal
compliance — it flips the software's defaults and adds the primitives an
operator needs to actually be compliant:

  - retention: vector/archive entries get an expiring TTL instead of
    persisting forever (memory.py enforces this at read time).
  - cloud consent: a session cannot be routed to a cloud/subscription model
    until consent is recorded for it, so a prompt cannot leave the machine
    silently.
  - export/erase: Article 15/20 (data portability) and Article 17 (erasure)
    primitives keyed by session_id.
  - subprocessors: a static, honest list of the cloud LLM providers this
    checkout can route to, for an operator's own Article 28 disclosures.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from privacy import private_archive_ns, private_session_key, resolve_private_context

ROOT = Path(__file__).resolve().parent.parent
GDPR_SETTINGS_FILE = Path(
    os.environ.get("AETHER_GDPR_SETTINGS_FILE", str(ROOT / "data" / "gdpr_settings.json"))
)

DEFAULT_RETENTION_DAYS = 30
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650  # 10y ceiling — sanity bound, not a recommendation

SUBPROCESSORS = [
    {
        "provider": "xAI",
        "models": "grok-*",
        "purpose": "Cloud inference for prompts routed to Grok models",
        "docs": "https://x.ai/legal",
    },
    {
        "provider": "OpenAI",
        "models": "gpt-*, o3, o4-*",
        "purpose": "Cloud inference for prompts routed to GPT/o-series models",
        "docs": "https://openai.com/policies",
    },
    {
        "provider": "Anthropic",
        "models": "claude-*",
        "purpose": "Cloud inference for prompts routed to Claude models",
        "docs": "https://www.anthropic.com/legal",
    },
    {
        "provider": "Mistral AI",
        "models": "mistral-*, codestral, pixtral",
        "purpose": "Cloud inference for prompts routed to Mistral models",
        "docs": "https://mistral.ai/terms",
    },
    {
        "provider": "Google",
        "models": "gemini-*",
        "purpose": "Cloud inference for prompts routed to Gemini models",
        "docs": "https://policies.google.com/privacy",
    },
]
LOCAL_NOTE = (
    "Local Ollama models (local-default, local-tiny, local-llama, ...) run entirely on this "
    "machine; no prompt content leaves it for those requests. Host-CLI models (grok-cli/"
    "claude-cli/codex-cli) send data to that provider under the account's own subscription terms."
)

_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "retention_days": DEFAULT_RETENTION_DAYS,
    "require_cloud_consent": True,
    "updated_at": None,
}


def get_settings() -> dict[str, Any]:
    try:
        if GDPR_SETTINGS_FILE.is_file():
            data = json.loads(GDPR_SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**_DEFAULTS, **{k: data[k] for k in _DEFAULTS if k in data}}
    except (OSError, json.JSONDecodeError):
        pass
    return dict(_DEFAULTS)


def set_settings(patch: dict[str, Any]) -> dict[str, Any]:
    current = get_settings()
    if "enabled" in patch:
        current["enabled"] = bool(patch["enabled"])
    if "retention_days" in patch:
        try:
            days = int(patch["retention_days"])
        except (TypeError, ValueError):
            raise ValueError("retention_days must be an integer")
        if not (MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS):
            raise ValueError(f"retention_days must be between {MIN_RETENTION_DAYS} and {MAX_RETENTION_DAYS}")
        current["retention_days"] = days
    if "require_cloud_consent" in patch:
        current["require_cloud_consent"] = bool(patch["require_cloud_consent"])
    current["updated_at"] = time.time()
    GDPR_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GDPR_SETTINGS_FILE.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return current


def is_enabled() -> bool:
    return bool(get_settings().get("enabled"))


def retention_seconds() -> int:
    return int(get_settings().get("retention_days", DEFAULT_RETENTION_DAYS)) * 86400


def subprocessors() -> dict[str, Any]:
    return {"cloud_providers": list(SUBPROCESSORS), "local_note": LOCAL_NOTE}


# ── consent ────────────────────────────────────────────────────────────
# Per-session, in-process only: there is no per-user auth yet (multi-user
# mode is design-only, see docs/MULTI-USER.md), so "consent" here is
# per-conversation, not per-account. A real multi-user deployment will need
# to persist this per authenticated user once that lands.
_consented_sessions: set[str] = set()


def record_consent(session_id: str) -> None:
    if session_id:
        _consented_sessions.add(str(session_id))


def revoke_consent(session_id: str) -> None:
    _consented_sessions.discard(str(session_id or ""))


def has_consent(session_id: str) -> bool:
    return str(session_id or "") in _consented_sessions


def cloud_dispatch_allowed(session_id: str | None) -> bool:
    """False only when GDPR mode + consent requirement are both on and this
    session has not recorded consent yet — callers should exclude cloud
    models from routing rather than erroring, so Auto still works locally."""
    settings = get_settings()
    if not settings.get("enabled") or not settings.get("require_cloud_consent"):
        return True
    return has_consent(session_id or "")


def filter_snapshot_for_consent(snapshot: dict[str, Any], session_id: str | None) -> dict[str, Any]:
    """Applies cloud_dispatch_allowed() to an entire model snapshot: when consent
    is missing, every non-local model is marked unavailable so every resolution
    path (named presets, node-graph stages, Auto) sees the same restricted view
    instead of each needing its own session-aware gate."""
    if cloud_dispatch_allowed(session_id):
        return snapshot
    models = snapshot.get("models") or {}
    filtered = {
        alias: (
            meta
            if meta.get("tier") == "local"
            else {**meta, "available": False, "availability_reason": "gdpr_consent_required"}
        )
        for alias, meta in models.items()
    }
    return {**snapshot, "models": filtered}


# ── export / erase ────────────────────────────────────────────────────

def _resolve_storage_ids(session_id: str) -> tuple[str, str]:
    """(store_sid, archive_ns) for this session — private sessions are stored
    under a vault-prefixed id/namespace, not the bare session_id (see
    slash_commands.cmd_clear, which applies this same resolution). Getting
    this wrong means export/erase silently miss a private session entirely."""
    ctx = resolve_private_context(session_id=session_id)
    if ctx.get("private"):
        store_sid = private_session_key(session_id, ctx.get("project_id"))
        archive_ns = private_archive_ns(session_id, ctx.get("project_id"))
    else:
        store_sid = session_id
        archive_ns = f"archive:{session_id}"
    return store_sid, archive_ns


def export_user_data(mem: Any, session_id: str) -> dict[str, Any]:
    """Everything stored under this session_id: live messages, its archive (if
    any), and any vector tagged with this session_id in meta (Article 15/20).
    Resolves the private vault's storage ids first, so a private session's
    data is not silently omitted."""
    store_sid, archive_ns = _resolve_storage_ids(session_id)
    result: dict[str, Any] = {"session_id": session_id, "exported_at": time.time()}
    result["session"] = mem.export_session(store_sid)
    if store_sid != session_id:
        # A private session may also have residual messages under the bare
        # id from before it was bound to the vault (see cmd_clear's handling
        # of the same case) — include them rather than silently dropping them.
        result["session_pre_bind"] = mem.export_session(session_id)
    result["archive"] = mem.export_namespace(archive_ns) if archive_ns in mem.list_vector_namespaces() else None
    tagged: list[dict[str, Any]] = []
    for ns in mem.list_vector_namespaces():
        if ns == archive_ns:
            continue
        for vec in mem.list_vectors(ns):
            if (vec.get("meta") or {}).get("session_id") == session_id:
                tagged.append({"namespace": ns, **vec})
    result["tagged_vectors"] = tagged
    return result


def erase_user_data(mem: Any, session_id: str) -> dict[str, Any]:
    """Deletes the live session AND its archive AND every vector tagged with
    this session_id anywhere (Article 17) — unlike a plain /clear, nothing is
    relocated first. Resolves the private vault's storage ids first, so a
    private session's data is not silently left behind."""
    store_sid, archive_ns = _resolve_storage_ids(session_id)
    removed: dict[str, Any] = {"session": False, "archive_namespace": None, "tagged_vectors": 0}
    mem.clear_session(store_sid)
    if store_sid != session_id:
        mem.clear_session(session_id)  # wipe any pre-bind residual too
    removed["session"] = True
    if archive_ns in mem.list_vector_namespaces() and mem.delete_namespace(archive_ns):
        removed["archive_namespace"] = archive_ns
    for ns in mem.list_vector_namespaces():
        if ns == archive_ns:
            continue
        for vec in list(mem.list_vectors(ns)):
            if (vec.get("meta") or {}).get("session_id") == session_id:
                if mem.delete_vector(ns, vec.get("id")):
                    removed["tagged_vectors"] += 1
    return removed
