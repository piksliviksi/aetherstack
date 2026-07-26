"""Safe upstream update checks and archive staging for the local Hub UI."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY = "piksliviksi/aetherstack"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/commits/main"
ARCHIVE_URL = f"https://github.com/{REPOSITORY}/archive/refs/heads/main.zip"
VERSION_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/VERSION"
UPDATE_DIR = Path(os.environ.get("AETHER_UPDATE_DIR", "/host-aetherstack/updates"))
CURRENT_VERSION = os.environ.get("AETHERSTACK_VERSION", "development")
CURRENT_REVISION = os.environ.get("AETHERSTACK_REVISION", "").strip()
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


def _request(url: str):
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"AetherStack/{CURRENT_VERSION}",
        },
    )


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for part in str(value or "").strip().lstrip("v").split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def check_update() -> dict[str, Any]:
    with urllib.request.urlopen(_request(API_URL), timeout=15) as response:
        value = json.loads(response.read().decode("utf-8"))
    latest_version = ""
    try:
        with urllib.request.urlopen(_request(VERSION_URL), timeout=15) as response:
            latest_version = response.read().decode("utf-8").strip()[:40]
    except Exception:
        # Older upstream revisions predate VERSION. Commit checks and archive
        # staging remain useful until the version marker is published.
        pass
    commit = value.get("commit") or {}
    latest = str(value.get("sha") or "")
    return {
        "ok": bool(latest),
        "repository": REPOSITORY,
        "current_version": CURRENT_VERSION,
        "latest_version": latest_version or None,
        "current_revision": CURRENT_REVISION or None,
        "latest_revision": latest,
        "latest_short": latest[:12],
        "latest_date": ((commit.get("committer") or {}).get("date")),
        "latest_message": str(commit.get("message") or "").splitlines()[0][:300],
        "update_available": (
            _version_tuple(latest_version) > _version_tuple(CURRENT_VERSION)
            if _version_tuple(latest_version) and _version_tuple(CURRENT_VERSION)
            else (None if not CURRENT_REVISION else not latest.startswith(CURRENT_REVISION))
        ),
        "can_stage": True,
        "can_apply_here": False,
        "apply_hint": "After reviewing local changes, apply from the trusted host checkout and restart AetherStack from VS Code.",
    }


def stage_update() -> dict[str, Any]:
    status = check_update()
    revision = status.get("latest_revision")
    if not revision:
        raise ValueError("upstream revision unavailable")
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPDATE_DIR / f"aetherstack-main-{revision[:12]}.zip"
    temporary = destination.with_suffix(".zip.part")
    digest = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(_request(ARCHIVE_URL), timeout=60) as response, open(temporary, "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise ValueError("update archive exceeds 100 MiB limit")
                digest.update(chunk)
                handle.write(chunk)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    manifest = {
        "schema": "aetherstack.update.v1",
        "staged_at": time.time(),
        "repository": REPOSITORY,
        "revision": revision,
        "archive": destination.name,
        "bytes": size,
        "sha256": digest.hexdigest(),
        "applied": False,
    }
    manifest_path = UPDATE_DIR / f"aetherstack-main-{revision[:12]}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "status": "staged",
        "manifest": manifest,
        "path": str(destination),
        "apply_hint": "Review and apply from the trusted host checkout, then restart through VS Code; the Hub never overwrites the checkout itself.",
    }


def update_status() -> dict[str, Any]:
    try:
        return check_update()
    except Exception as exc:
        return {
            "ok": False,
            "repository": REPOSITORY,
            "current_version": CURRENT_VERSION,
            "error": str(exc)[:500],
            "can_stage": False,
            "can_apply_here": False,
        }
