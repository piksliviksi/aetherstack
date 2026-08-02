"""Tenancy primitives (MULTI-USER M0): teams, projects, memberships.

File-backed JSON store for Team Server single-org deployments. Not a full
multi-tenant database — E5 may move this to Postgres.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from auth import AuthContext

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = Path(
    os.environ.get(
        "AETHER_TENANCY_FILE",
        str(ROOT / ".aetherstack" / "tenancy.json"),
    )
)

ROLE_RANK = {"viewer": 1, "member": 2, "owner": 3, "admin": 4}

_lock = threading.RLock()
_store_path = DEFAULT_STORE
_cache: dict[str, Any] | None = None


def _empty_store() -> dict[str, Any]:
    return {
        "version": 1,
        "teams": {},
        "projects": {},
        "memberships": [],  # {user_id, project_id, team_id, role}
    }


def configure(path: Path | str | None = None) -> None:
    global _store_path, _cache
    with _lock:
        if path is not None:
            _store_path = Path(path)
        _cache = None


def _load() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        if _store_path.is_file():
            try:
                data = json.loads(_store_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    _cache = data
                    _cache.setdefault("teams", {})
                    _cache.setdefault("projects", {})
                    _cache.setdefault("memberships", [])
                    return _cache
            except (OSError, json.JSONDecodeError):
                pass
        _cache = _empty_store()
        return _cache


def _save(data: dict[str, Any]) -> None:
    global _cache
    with _lock:
        _store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = _store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(_store_path)
        _cache = data


def reset_for_tests(path: Path | str) -> None:
    configure(path)
    _save(_empty_store())


def list_teams() -> list[dict[str, Any]]:
    data = _load()
    return list(data["teams"].values())


def list_projects(team_id: str | None = None) -> list[dict[str, Any]]:
    data = _load()
    projects = list(data["projects"].values())
    if team_id:
        projects = [p for p in projects if p.get("team_id") == team_id]
    return projects


def get_project(project_id: str) -> dict[str, Any] | None:
    return _load()["projects"].get(project_id)


def ensure_default_team(name: str = "Default team") -> dict[str, Any]:
    data = _load()
    for team in data["teams"].values():
        return team
    team_id = "team-default"
    team = {
        "kind": "team",
        "team_id": team_id,
        "name": name,
        "created_at": _now(),
    }
    data["teams"][team_id] = team
    _save(data)
    return team


def create_project(
    *,
    name: str,
    team_id: str | None = None,
    owner_user_id: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    data = _load()
    team = None
    if team_id and team_id in data["teams"]:
        team = data["teams"][team_id]
    else:
        team = ensure_default_team()
        team_id = team["team_id"]
    pid = (project_id or f"proj-{uuid.uuid4().hex[:10]}").strip()
    if pid in data["projects"]:
        raise ValueError(f"project already exists: {pid}")
    project = {
        "kind": "project",
        "project_id": pid,
        "team_id": team_id,
        "name": name.strip() or pid,
        "memory_namespace": f"project:{pid}",
        "created_at": _now(),
    }
    data["projects"][pid] = project
    data["memberships"].append(
        {
            "kind": "membership",
            "user_id": owner_user_id,
            "project_id": pid,
            "team_id": team_id,
            "role": "owner",
            "created_at": _now(),
        }
    )
    _save(data)
    return project


def add_member(project_id: str, user_id: str, role: str = "member") -> dict[str, Any]:
    if role not in ROLE_RANK:
        raise ValueError("invalid role")
    data = _load()
    project = data["projects"].get(project_id)
    if not project:
        raise ValueError("unknown project")
    user_id = user_id.strip()
    for m in data["memberships"]:
        if m.get("project_id") == project_id and m.get("user_id") == user_id:
            m["role"] = role
            _save(data)
            return m
    membership = {
        "kind": "membership",
        "user_id": user_id,
        "project_id": project_id,
        "team_id": project.get("team_id"),
        "role": role,
        "created_at": _now(),
    }
    data["memberships"].append(membership)
    _save(data)
    return membership


def remove_member(project_id: str, user_id: str) -> bool:
    data = _load()
    before = len(data["memberships"])
    data["memberships"] = [
        m
        for m in data["memberships"]
        if not (m.get("project_id") == project_id and m.get("user_id") == user_id)
    ]
    if len(data["memberships"]) == before:
        return False
    _save(data)
    return True


def get_role(user_id: str, project_id: str) -> str | None:
    data = _load()
    for m in data["memberships"]:
        if m.get("project_id") == project_id and m.get("user_id") == user_id:
            return str(m.get("role") or "member")
    return None


def list_memberships(
    *,
    project_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    data = _load()
    out = list(data["memberships"])
    if project_id:
        out = [m for m in out if m.get("project_id") == project_id]
    if user_id:
        out = [m for m in out if m.get("user_id") == user_id]
    return out


def role_at_least(have: str | None, need: str) -> bool:
    return ROLE_RANK.get(have or "", 0) >= ROLE_RANK.get(need, 99)


def authorize_project(
    ctx: AuthContext,
    project_id: str,
    min_role: str = "viewer",
) -> str:
    """Return effective role or raise PermissionError."""
    if ctx.is_admin():
        return "owner"
    role = get_role(ctx.user_id, project_id)
    # Desktop open operator is treated as owner of everything when auth off —
    # when auth is on, membership is required.
    if ctx.auth_method == "desktop_open":
        return "owner"
    if not role_at_least(role, min_role):
        raise PermissionError(f"requires {min_role} on project {project_id}")
    return role or "viewer"


def memory_namespace_for_project(project_id: str) -> str:
    project = get_project(project_id)
    if project and project.get("memory_namespace"):
        return str(project["memory_namespace"])
    return f"project:{project_id}"


def attach_project_context(ctx: AuthContext, project_id: str | None) -> AuthContext:
    if not project_id:
        return ctx
    try:
        role = authorize_project(ctx, project_id, "viewer")
    except PermissionError:
        ctx.project_id = project_id
        ctx.role = None
        return ctx
    ctx.project_id = project_id
    ctx.role = role
    return ctx


def snapshot() -> dict[str, Any]:
    data = _load()
    return {
        "team_count": len(data["teams"]),
        "project_count": len(data["projects"]),
        "membership_count": len(data["memberships"]),
        "teams": list_teams(),
        "projects": list_projects(),
    }


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
