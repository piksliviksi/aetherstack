"""
Private mode — isolate project/model work from the common memory pool.

Rules:
  - Private projects and private models never write to shared namespaces
    (default, conversation-index, xref, agent-events, session-context:*).
  - Private session data uses a separate Redis/local prefix (private vault).
  - Archives stay in private vault only; no sticky index into common pool.
  - Logs redacted: no content, only action tokens.
  - State is persistent until explicit release.
  - Release does not merge private data into the common pool.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

# Shared namespaces that must never receive private content
COMMON_NAMESPACES = frozenset(
    {
        "default",
        "conversation-index",
        "xref",
        "xref-index",
        "agent-events",
    }
)

COMMON_NS_PREFIXES = (
    "session-context:",
    "session:",  # common session vector mirrors
    "xref:",
    "archive:",  # common archives; private uses private:archive:
)

PRIVATE_PREFIX = os.environ.get("AETHER_PRIVATE_PREFIX", "aether:private")
STATE_REDIS_KEY = f"{PRIVATE_PREFIX}:state"
STATE_FILE = Path(
    os.environ.get(
        "AETHER_PRIVACY_STATE",
        str(Path(__file__).resolve().parent / "data" / "privacy_state.json"),
    )
)

_state: dict[str, Any] = {
    "projects": {},  # id -> {id, path, name, private, models[], session_ids[], set_at, released_at}
    "models": {},  # model_alias -> {private, set_at, project_id?}
    "sessions": {},  # session_id -> project_id
    "updated_at": None,
}


def _project_id(path_or_name: str) -> str:
    h = hashlib.sha256(path_or_name.encode("utf-8", errors="replace")).hexdigest()[:12]
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(path_or_name).name or "proj")[:24]
    return f"{base}-{h}"


def _load_from_disk() -> None:
    try:
        if STATE_FILE.is_file():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _state["projects"] = data.get("projects") or {}
                _state["models"] = data.get("models") or {}
                _state["sessions"] = data.get("sessions") or {}
                _state["updated_at"] = data.get("updated_at")
    except (OSError, json.JSONDecodeError):
        pass


def _save_to_disk() -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(
                {
                    "projects": _state["projects"],
                    "models": _state["models"],
                    "sessions": _state["sessions"],
                    "updated_at": _state["updated_at"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def load_from_redis(r: Any) -> None:
    """Merge Redis state if present (authoritative when available)."""
    if r is None:
        return
    try:
        raw = r.get(STATE_REDIS_KEY)
        if not raw:
            return
        data = json.loads(raw)
        if isinstance(data, dict):
            _state["projects"] = data.get("projects") or _state["projects"]
            _state["models"] = data.get("models") or _state["models"]
            _state["sessions"] = data.get("sessions") or _state["sessions"]
            _state["updated_at"] = data.get("updated_at")
    except Exception:
        pass


def save_to_redis(r: Any) -> None:
    if r is None:
        return
    try:
        r.set(
            STATE_REDIS_KEY,
            json.dumps(
                {
                    "projects": _state["projects"],
                    "models": _state["models"],
                    "sessions": _state["sessions"],
                    "updated_at": _state["updated_at"],
                }
            ),
        )
    except Exception:
        pass


# Load disk state at import
_load_from_disk()


def get_privacy_state() -> dict[str, Any]:
    projects = {
        pid: {**p, "private": bool(p.get("private"))}
        for pid, p in (_state.get("projects") or {}).items()
        if p.get("private")
    }
    models = {
        m: {**v, "private": bool(v.get("private"))}
        for m, v in (_state.get("models") or {}).items()
        if v.get("private")
    }
    return {
        "private_project_count": len(projects),
        "private_model_count": len(models),
        "projects": projects,
        "models": models,
        "sessions": dict(_state.get("sessions") or {}),
        "updated_at": _state.get("updated_at"),
        "rules": {
            "common_namespaces_blocked": sorted(COMMON_NAMESPACES),
            "vault_prefix": PRIVATE_PREFIX,
            "release_merges_to_common": False,
            "persistence": "until_explicit_release",
        },
    }


def _persist(r: Any = None) -> None:
    _state["updated_at"] = time.time()
    _save_to_disk()
    save_to_redis(r)


def set_project_private(
    *,
    path: str | None = None,
    project_id: str | None = None,
    name: str | None = None,
    private: bool = True,
    session_id: str | None = None,
    models: list[str] | None = None,
    redis_client: Any = None,
) -> dict[str, Any]:
    """Mark or unmark a project private. Unmark without release is blocked — use release_project."""
    if not private:
        raise ValueError("Use release_project() to leave private state (explicit release).")

    pid = project_id or _project_id(path or name or str(uuid.uuid4()))
    proj = _state.setdefault("projects", {}).get(pid) or {
        "id": pid,
        "path": path,
        "name": name or (Path(path).name if path else pid),
        "session_ids": [],
        "models": [],
    }
    proj["private"] = True
    proj["set_at"] = time.time()
    proj["released_at"] = None
    if path:
        proj["path"] = path
    if name:
        proj["name"] = name
    if models:
        for m in models:
            if m and m not in proj.setdefault("models", []):
                proj["models"].append(m)
            _state.setdefault("models", {})[m] = {
                "private": True,
                "set_at": time.time(),
                "project_id": pid,
            }
    if session_id:
        bind_session(session_id, pid, redis_client=None)
        if session_id not in proj.setdefault("session_ids", []):
            proj["session_ids"].append(session_id)
    _state["projects"][pid] = proj
    _persist(redis_client)
    return {"ok": True, "project": proj, "private": True}


def set_model_private(
    model: str,
    *,
    private: bool = True,
    project_id: str | None = None,
    redis_client: Any = None,
) -> dict[str, Any]:
    """Flag a model alias as private (all traffic for that alias is isolated)."""
    model = (model or "").strip()
    if not model:
        raise ValueError("model required")
    if private:
        _state.setdefault("models", {})[model] = {
            "private": True,
            "set_at": time.time(),
            "project_id": project_id,
        }
        if project_id and project_id in (_state.get("projects") or {}):
            models = _state["projects"][project_id].setdefault("models", [])
            if model not in models:
                models.append(model)
    else:
        # Model-only unflag allowed if not tied to an active private project
        entry = (_state.get("models") or {}).get(model) or {}
        pid = entry.get("project_id")
        if pid and (_state.get("projects") or {}).get(pid, {}).get("private"):
            raise ValueError(
                f"Model {model} is bound to private project {pid}; release the project first."
            )
        _state.setdefault("models", {}).pop(model, None)
    _persist(redis_client)
    return {"ok": True, "model": model, "private": private, "entry": (_state.get("models") or {}).get(model)}


def bind_session(session_id: str, project_id: str, redis_client: Any = None) -> dict[str, Any]:
    session_id = session_id or "default"
    _state.setdefault("sessions", {})[session_id] = project_id
    proj = _state.setdefault("projects", {}).get(project_id)
    if proj is not None:
        sids = proj.setdefault("session_ids", [])
        if session_id not in sids:
            sids.append(session_id)
    _persist(redis_client)
    return {"ok": True, "session_id": session_id, "project_id": project_id}


def release_project(
    project_id: str,
    *,
    purge_vault: bool = True,
    mem: Any = None,
    redis_client: Any = None,
) -> dict[str, Any]:
    """
    Leave private state. Does not copy vault data into common memory.
    Optionally purges private vault keys for the project.
    """
    proj = (_state.get("projects") or {}).get(project_id)
    if not proj:
        raise ValueError(f"unknown project: {project_id}")

    purged = None
    if purge_vault and mem is not None:
        purged = purge_private_vault(mem, project_id=project_id)

    # unbind sessions
    for sid in list(proj.get("session_ids") or []):
        if (_state.get("sessions") or {}).get(sid) == project_id:
            _state["sessions"].pop(sid, None)

    # unbind models owned by this project
    for m in list(proj.get("models") or []):
        entry = (_state.get("models") or {}).get(m)
        if entry and entry.get("project_id") == project_id:
            _state["models"].pop(m, None)

    proj["private"] = False
    proj["released_at"] = time.time()
    proj["session_ids"] = []
    # keep record for audit without active private
    _state["projects"][project_id] = proj
    _persist(redis_client)
    return {
        "ok": True,
        "project_id": project_id,
        "private": False,
        "merged_to_common": False,
        "vault_purged": purged,
        "message": "Project released from private state. Vault not merged into common pool.",
    }


def is_project_private(project_id: str | None = None, path: str | None = None) -> bool:
    if project_id:
        p = (_state.get("projects") or {}).get(project_id)
        if p and p.get("private"):
            return True
    if path:
        pid = _project_id(path)
        p = (_state.get("projects") or {}).get(pid)
        if p and p.get("private"):
            return True
        # also match by stored path
        for p in (_state.get("projects") or {}).values():
            if p.get("private") and p.get("path") and _norm_path(p["path"]) == _norm_path(path):
                return True
    return False


def _norm_path(p: str) -> str:
    try:
        return str(Path(p).expanduser().resolve()).lower()
    except OSError:
        return str(p).lower().replace("\\", "/")


def is_model_private(model: str | None) -> bool:
    if not model:
        return False
    entry = (_state.get("models") or {}).get(model)
    return bool(entry and entry.get("private"))


def is_session_private(session_id: str | None) -> bool:
    if not session_id:
        return False
    pid = (_state.get("sessions") or {}).get(session_id)
    if not pid:
        return False
    p = (_state.get("projects") or {}).get(pid)
    return bool(p and p.get("private"))


def resolve_private_context(
    *,
    session_id: str | None = None,
    project_id: str | None = None,
    path: str | None = None,
    model: str | None = None,
    private_flag: bool | None = None,
) -> dict[str, Any]:
    """
    Single gate for handlers. private_flag=True forces isolation for this request.
    """
    reasons: list[str] = []
    if private_flag is True:
        reasons.append("request_flag")
    if is_session_private(session_id):
        reasons.append("session")
    if is_project_private(project_id=project_id, path=path):
        reasons.append("project")
    if is_model_private(model):
        reasons.append("model")

    private = bool(reasons)
    pid = project_id
    if not pid and session_id:
        pid = (_state.get("sessions") or {}).get(session_id)
    if not pid and path:
        pid = _project_id(path)

    return {
        "private": private,
        "reasons": reasons,
        "project_id": pid,
        "session_id": session_id,
        "model": model,
        "vault_session": private_session_key(session_id or "default", pid),
        "vault_namespace_prefix": private_ns_prefix(pid),
    }


def private_session_key(session_id: str, project_id: str | None = None) -> str:
    """Session id used inside private vault (never the bare common session id)."""
    if project_id:
        return f"private:{project_id}:{session_id}"
    return f"private:orphan:{session_id}"


def private_ns_prefix(project_id: str | None = None) -> str:
    if project_id:
        return f"private:{project_id}"
    return "private:orphan"


def private_archive_ns(session_id: str, project_id: str | None = None) -> str:
    return f"{private_ns_prefix(project_id)}:archive:{session_id}"


def is_common_namespace(namespace: str | None) -> bool:
    ns = namespace or "default"
    if ns in COMMON_NAMESPACES:
        return True
    if ns.startswith("private:"):
        return False
    for p in COMMON_NS_PREFIXES:
        if ns.startswith(p):
            return True
    # bare project namespaces without private: prefix are treated as common
    return True


def assert_write_allowed(namespace: str | None, ctx: dict[str, Any]) -> None:
    """Raise if private context attempts write into common pool."""
    if not ctx.get("private"):
        return
    ns = namespace or "default"
    if is_common_namespace(ns) and not ns.startswith("private:"):
        raise PermissionError(
            f"private_mode_blocks_common_namespace:{ns} "
            f"(use vault prefix {private_ns_prefix(ctx.get('project_id'))})"
        )


def force_private_namespace(namespace: str | None, ctx: dict[str, Any]) -> str:
    """Remap a requested namespace into the private vault when private."""
    if not ctx.get("private"):
        return namespace or "default"
    ns = namespace or "default"
    if ns.startswith("private:"):
        return ns
    prefix = private_ns_prefix(ctx.get("project_id"))
    # strip common prefixes to avoid private:private:…
    clean = ns
    for p in ("archive:", "session:", "session-context:"):
        if clean.startswith(p):
            clean = clean[len(p) :]
            break
    return f"{prefix}:{clean}"


def redact_log(action: str, ctx: dict[str, Any], **meta: Any) -> str:
    """Log line with no content payload."""
    parts = [
        "[private]",
        f"action={action}",
        f"session={ctx.get('session_id') or '-'}",
        f"project={ctx.get('project_id') or '-'}",
        f"model={ctx.get('model') or '-'}",
    ]
    for k, v in meta.items():
        if k in ("text", "content", "prompt", "messages", "body", "excerpt", "prompt_block"):
            continue
        parts.append(f"{k}={v}")
    return " ".join(parts)


def purge_private_vault(mem: Any, *, project_id: str | None = None) -> dict[str, Any]:
    """Delete private vault vectors/sessions for a project (or all orphan private)."""
    prefix = private_ns_prefix(project_id)
    removed_ns = 0
    removed_sessions = 0

    # local fallback buckets
    if hasattr(mem, "_local_vectors"):
        keys = [k for k in list(mem._local_vectors.keys()) if str(k).startswith(prefix) or str(k).startswith("private:")]
        if project_id:
            keys = [k for k in keys if str(k).startswith(prefix)]
        for k in keys:
            del mem._local_vectors[k]
            removed_ns += 1
    if hasattr(mem, "_local_sessions"):
        sk = [k for k in list(mem._local_sessions.keys()) if str(k).startswith("private:")]
        if project_id:
            sk = [k for k in sk if project_id in str(k)]
        for k in sk:
            del mem._local_sessions[k]
            removed_sessions += 1

    # redis
    r = getattr(mem, "_r", None)
    if r is not None:
        try:
            pattern = f"{getattr(mem, 'url', '') and ''}*"
            # Use PREFIX from memory module via keys on vec and session
            from memory import PREFIX  # local import

            if project_id:
                patterns = [
                    f"{PREFIX}:vec:{prefix}*",
                    f"{PREFIX}:session:private:{project_id}:*",
                ]
            else:
                patterns = [
                    f"{PREFIX}:vec:private:*",
                    f"{PREFIX}:session:private:*",
                ]
            for pat in patterns:
                cursor = 0
                while True:
                    cursor, keys = r.scan(cursor=cursor, match=pat, count=200)
                    if keys:
                        r.delete(*keys)
                        if ":vec:" in pat:
                            removed_ns += len(keys)
                        else:
                            removed_sessions += len(keys)
                    if cursor == 0:
                        break
            # also delete :ids sidecars already matched by vec*
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "removed_namespaces": removed_ns,
                "removed_sessions": removed_sessions,
            }

    return {
        "ok": True,
        "project_id": project_id,
        "removed_namespace_keys": removed_ns,
        "removed_sessions": removed_sessions,
    }


def apply_privacy_patch(patch: dict[str, Any], *, redis_client: Any = None, mem: Any = None) -> dict[str, Any]:
    """
    Unified state mutation from API body.

    Examples:
      {"private": true, "path": "D:/code/secret", "session_id": "s1"}
      {"private": true, "model": "local-default"}
      {"release": true, "project_id": "...", "purge_vault": true}
      {"bind_session": "s1", "project_id": "..."}
    """
    if patch.get("release") or patch.get("private") is False and patch.get("project_id"):
        if patch.get("private") is False and not patch.get("release"):
            # explicit: only release_project leaves private state
            return release_project(
                str(patch["project_id"]),
                purge_vault=bool(patch.get("purge_vault", True)),
                mem=mem,
                redis_client=redis_client,
            )
        if patch.get("release"):
            pid = patch.get("project_id") or patch.get("id")
            if not pid:
                raise ValueError("project_id required for release")
            return release_project(
                str(pid),
                purge_vault=bool(patch.get("purge_vault", True)),
                mem=mem,
                redis_client=redis_client,
            )

    if patch.get("bind_session") and patch.get("project_id"):
        return bind_session(str(patch["bind_session"]), str(patch["project_id"]), redis_client=redis_client)

    if patch.get("model") is not None and "path" not in patch and "project_id" not in patch:
        return set_model_private(
            str(patch["model"]),
            private=bool(patch.get("private", True)),
            project_id=patch.get("bind_project"),
            redis_client=redis_client,
        )

    if patch.get("private") is True or patch.get("path") or patch.get("project_id") and patch.get("private", True):
        if patch.get("private") is False:
            raise ValueError("Set private=false via release on project_id")
        return set_project_private(
            path=patch.get("path"),
            project_id=patch.get("project_id") or patch.get("id"),
            name=patch.get("name"),
            private=True,
            session_id=patch.get("session_id"),
            models=patch.get("models") or ([patch["model"]] if patch.get("model") else None),
            redis_client=redis_client,
        )

    raise ValueError(
        "Unrecognized privacy patch. Use: "
        '{"private":true,"path":"...","session_id":"..."} | '
        '{"private":true,"model":"..."} | '
        '{"release":true,"project_id":"..."}'
    )
