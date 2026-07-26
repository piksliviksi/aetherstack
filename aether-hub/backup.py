"""
AetherStack backup — project or global export of memory, research, and config.

Destinations:
  - local folder (default on the PC / mounted path)
  - AWS S3 (boto3 or AWS CLI)
  - Azure Blob (azure-storage-blob or az CLI)

Scopes:
  - project: one project path / id / session filter
  - global: all common namespaces + optional private (opt-in)

Modes:
  - manual: POST /api/backup or scripts/backup-aether.*
  - automatic: hub scheduler when backup.yaml auto.enabled
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from memory import MemoryStore
from privacy import get_privacy_state

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parent
STACK_ROOT = ROOT.parent
DEFAULT_CONFIG = Path(
    os.environ.get(
        "AETHER_BACKUP_CONFIG",
        str(STACK_ROOT / ".aetherstack" / "backup.yaml"),
    )
)
DEFAULT_LOCAL_DIR = Path(
    os.environ.get(
        "AETHER_BACKUP_DIR",
        str(STACK_ROOT / ".aetherstack" / "backups"),
    )
)
BACKUP_ID_RE = re.compile(r"^aether-backup-[A-Za-z0-9_-]{1,96}$")


def _path_under(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False

# Namespaces always treated as global common (not private vault)
GLOBAL_NS_HINTS = (
    "default",
    "conversation-index",
    "xref",
    "xref-index",
    "agent-events",
    "archive:",
    "session:",
    "session-context:",
)

_auto_state: dict[str, Any] = {
    "enabled": False,
    "interval_sec": 86400,
    "last_run": None,
    "last_result": None,
}


def default_config() -> dict[str, Any]:
    return {
        "version": 1,
        "local": {
            "enabled": True,
            "path": str(DEFAULT_LOCAL_DIR),
            "keep_last": 20,
            "zip": True,
        },
        "aws": {
            "enabled": False,
            "bucket": "",
            "prefix": "aetherstack/backups",
            "region": os.environ.get("AWS_DEFAULT_REGION") or "us-east-1",
            "profile": os.environ.get("AWS_PROFILE") or "",
        },
        "azure": {
            "enabled": False,
            "container": "",
            "prefix": "aetherstack/backups",
            "connection_string_env": "AZURE_STORAGE_CONNECTION_STRING",
            "account_url": "",  # e.g. https://acct.blob.core.windows.net
        },
        "auto": {
            "enabled": False,
            "interval_sec": 86400,
            "scope": "global",  # global | project
            "include_private": False,
            "include_embeddings": False,
        },
        "include": {
            "memory_vectors": True,
            "sessions": True,
            "privacy_state": True,
            "xref_registry": True,
            "project_files": True,  # .aetherstack under project path
            "combos_export": False,
            "pipelines_export": False,
        },
    }


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg = default_config()
    p = path or DEFAULT_CONFIG
    if p.is_file() and yaml is not None:
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                        cfg[k] = {**cfg[k], **v}
                    else:
                        cfg[k] = v
        except Exception:
            pass
    # env overrides
    if os.environ.get("AETHER_BACKUP_DIR"):
        cfg["local"]["path"] = os.environ["AETHER_BACKUP_DIR"]
        cfg["local"]["enabled"] = True
    if os.environ.get("AETHER_BACKUP_S3_BUCKET"):
        cfg["aws"]["enabled"] = True
        cfg["aws"]["bucket"] = os.environ["AETHER_BACKUP_S3_BUCKET"]
        if os.environ.get("AETHER_BACKUP_S3_PREFIX"):
            cfg["aws"]["prefix"] = os.environ["AETHER_BACKUP_S3_PREFIX"]
    if os.environ.get("AETHER_BACKUP_AZURE_CONTAINER"):
        cfg["azure"]["enabled"] = True
        cfg["azure"]["container"] = os.environ["AETHER_BACKUP_AZURE_CONTAINER"]
    if os.environ.get("AETHER_BACKUP_AUTO", "").lower() in ("1", "true", "yes"):
        cfg["auto"]["enabled"] = True
    return cfg


def save_config(cfg: dict[str, Any], path: Path | None = None) -> Path:
    p = path or DEFAULT_CONFIG
    p.parent.mkdir(parents=True, exist_ok=True)
    if yaml is None:
        p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    else:
        p.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return p


def get_backup_status() -> dict[str, Any]:
    cfg = load_config()
    return {
        "config_path": str(DEFAULT_CONFIG),
        "config": cfg,
        "auto": dict(_auto_state),
        "default_local_dir": str(DEFAULT_LOCAL_DIR),
    }


def _ns_matches_scope(
    ns: str,
    *,
    scope: str,
    project_id: str | None,
    include_private: bool,
) -> bool:
    is_priv = ns.startswith("private:")
    if is_priv and not include_private:
        return False
    if scope == "global":
        return True
    # project scope
    if project_id:
        if project_id in ns:
            return True
        if ns.startswith(f"archive:") and project_id in ns:
            return True
    return False


def _strip_embeddings(docs: list[dict]) -> list[dict]:
    out = []
    for d in docs:
        c = dict(d)
        c.pop("embedding", None)
        out.append(c)
    return out


def collect_backup_payload(
    mem: MemoryStore,
    *,
    scope: str = "global",
    project_id: str | None = None,
    project_path: str | None = None,
    session_id: str | None = None,
    include_private: bool = False,
    include_embeddings: bool = False,
    include: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Build in-memory archive structure (not yet written to disk)."""
    inc = {**default_config()["include"], **(include or {})}
    scope = (scope or "global").lower()
    ts = time.time()
    bid = f"aether-backup-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"

    payload: dict[str, Any] = {
        "schema": "aetherstack.backup.v1",
        "id": bid,
        "created_at": ts,
        "scope": scope,
        "project_id": project_id,
        "project_path": project_path,
        "session_id": session_id,
        "include_private": include_private,
        "include_embeddings": include_embeddings,
        "vectors": {},
        "sessions": {},
        "privacy": None,
        "xref_registry": None,
        "project_files": {},
        "meta": {"memory_backend": mem.backend},
    }

    if inc.get("memory_vectors", True):
        for ns in mem.list_vector_namespaces():
            if not _ns_matches_scope(
                ns, scope=scope, project_id=project_id, include_private=include_private
            ):
                continue
            if scope == "project" and project_id and project_id not in ns:
                # allow session-related ns when session_id matches
                if session_id and session_id not in ns:
                    continue
            exp = mem.export_namespace(ns)
            docs = exp.get("vectors") or []
            if not include_embeddings:
                docs = _strip_embeddings(docs)
            payload["vectors"][ns] = {"count": len(docs), "vectors": docs}

    if inc.get("sessions", True):
        sids = mem.list_session_ids()
        for sid in sids:
            if scope == "project":
                if session_id and sid != session_id and session_id not in sid:
                    if project_id and project_id not in sid:
                        continue
                elif project_id and project_id not in sid and sid != session_id:
                    # include default session only if explicit session_id
                    if session_id and sid != session_id:
                        continue
                    if not session_id:
                        # project scope without session: only private:project or matching
                        if project_id not in sid and not sid.startswith("private:"):
                            continue
            if not include_private and str(sid).startswith("private:"):
                continue
            payload["sessions"][sid] = mem.export_session(sid)

    if inc.get("privacy_state", True):
        payload["privacy"] = get_privacy_state()

    if inc.get("xref_registry", True):
        try:
            from cross_memory import get_xref_state

            payload["xref_registry"] = get_xref_state()
        except Exception as e:
            payload["xref_registry"] = {"error": str(e)}

    if inc.get("project_files", True) and project_path:
        root = Path(project_path).expanduser().resolve(strict=True)
        aether = (root / ".aetherstack").resolve(strict=False)
        if not _path_under(aether, root):
            raise ValueError("project .aetherstack directory escapes project root")
        if aether.is_dir():
            for fp in aether.rglob("*"):
                resolved = fp.resolve(strict=False)
                if not _path_under(resolved, aether) or not resolved.is_file():
                    continue
                if resolved.suffix.lower() not in (".md", ".json", ".yaml", ".yml", ".txt"):
                    continue
                try:
                    rel = str(resolved.relative_to(root))
                    payload["project_files"][rel] = resolved.read_text(encoding="utf-8", errors="replace")[
                        :200_000
                    ]
                except OSError:
                    continue

    payload["meta"]["vector_namespaces"] = len(payload["vectors"])
    payload["meta"]["session_count"] = len(payload["sessions"])
    payload["meta"]["project_file_count"] = len(payload["project_files"])
    return payload


def write_local_backup(
    payload: dict[str, Any],
    *,
    dest_dir: str | Path | None = None,
    as_zip: bool = True,
    keep_last: int = 20,
) -> dict[str, Any]:
    dest = Path(dest_dir or DEFAULT_LOCAL_DIR).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    bid = payload.get("id") or f"aether-backup-{uuid.uuid4().hex[:8]}"
    if not BACKUP_ID_RE.fullmatch(str(bid)):
        raise ValueError("invalid backup id")
    folder = dest / bid
    folder.mkdir(parents=True, exist_ok=True)

    manifest = {k: v for k, v in payload.items() if k not in ("vectors", "sessions", "project_files")}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    (folder / "vectors.json").write_text(
        json.dumps(payload.get("vectors") or {}, indent=2, default=str), encoding="utf-8"
    )
    (folder / "sessions.json").write_text(
        json.dumps(payload.get("sessions") or {}, indent=2, default=str), encoding="utf-8"
    )
    if payload.get("project_files"):
        pf = folder / "project_files"
        pf.mkdir(exist_ok=True)
        for rel, text in (payload.get("project_files") or {}).items():
            outp = (pf / rel.replace("\\", "/")).resolve(strict=False)
            if not _path_under(outp, pf.resolve()):
                raise ValueError(f"backup project file escapes destination: {rel}")
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(text, encoding="utf-8")

    zip_path = None
    if as_zip:
        zip_path = dest / f"{bid}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fp in folder.rglob("*"):
                if fp.is_file():
                    zf.write(fp, arcname=str(fp.relative_to(folder)))
        # remove unpacked tree to save space
        shutil.rmtree(folder, ignore_errors=True)

    # retention
    if keep_last > 0:
        zips = sorted(dest.glob("aether-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in zips[keep_last:]:
            try:
                old.unlink()
            except OSError:
                pass
        dirs = sorted(
            [p for p in dest.iterdir() if p.is_dir() and p.name.startswith("aether-backup-")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in dirs[keep_last:]:
            shutil.rmtree(old, ignore_errors=True)

    return {
        "ok": True,
        "destination": "local",
        "path": str(zip_path or folder),
        "id": bid,
        "zip": bool(zip_path),
    }


def upload_s3(local_path: str | Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Upload file to AWS S3. Prefer boto3; fall back to AWS CLI."""
    local_path = Path(local_path)
    bucket = (cfg.get("bucket") or "").strip()
    if not bucket:
        return {"ok": False, "error": "aws.bucket not configured"}
    prefix = (cfg.get("prefix") or "aetherstack/backups").strip().strip("/")
    key = f"{prefix}/{local_path.name}"
    region = cfg.get("region") or "us-east-1"

    # boto3
    try:
        import boto3  # type: ignore

        session_kw = {}
        if cfg.get("profile"):
            session = boto3.Session(profile_name=cfg["profile"], region_name=region)
        else:
            session = boto3.Session(region_name=region)
        s3 = session.client("s3")
        s3.upload_file(str(local_path), bucket, key)
        return {"ok": True, "destination": "aws_s3", "bucket": bucket, "key": key, "uri": f"s3://{bucket}/{key}"}
    except ImportError:
        pass
    except Exception as e:
        return {"ok": False, "destination": "aws_s3", "error": str(e)}

    # AWS CLI
    cmd = ["aws", "s3", "cp", str(local_path), f"s3://{bucket}/{key}", "--region", region]
    if cfg.get("profile"):
        cmd.extend(["--profile", str(cfg["profile"])])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return {"ok": False, "destination": "aws_s3", "error": (r.stderr or r.stdout or "aws cli failed")[:500]}
        return {"ok": True, "destination": "aws_s3", "bucket": bucket, "key": key, "uri": f"s3://{bucket}/{key}", "via": "aws-cli"}
    except FileNotFoundError:
        return {
            "ok": False,
            "destination": "aws_s3",
            "error": "Install boto3 or AWS CLI, and set credentials",
        }
    except Exception as e:
        return {"ok": False, "destination": "aws_s3", "error": str(e)}


def upload_azure(local_path: str | Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Upload file to Azure Blob. Prefer SDK; fall back to az CLI."""
    local_path = Path(local_path)
    container = (cfg.get("container") or "").strip()
    if not container:
        return {"ok": False, "error": "azure.container not configured"}
    prefix = (cfg.get("prefix") or "aetherstack/backups").strip().strip("/")
    blob_name = f"{prefix}/{local_path.name}"

    conn_env = cfg.get("connection_string_env") or "AZURE_STORAGE_CONNECTION_STRING"
    conn = os.environ.get(conn_env, "").strip()

    try:
        from azure.storage.blob import BlobServiceClient  # type: ignore

        if conn:
            client = BlobServiceClient.from_connection_string(conn)
        elif cfg.get("account_url"):
            # DefaultAzureCredential path would need azure-identity; keep simple
            return {"ok": False, "error": "Set connection string env for Azure upload"}
        else:
            return {"ok": False, "error": f"Missing env {conn_env}"}
        blob = client.get_blob_client(container=container, blob=blob_name)
        with open(local_path, "rb") as f:
            blob.upload_blob(f, overwrite=True)
        return {
            "ok": True,
            "destination": "azure_blob",
            "container": container,
            "blob": blob_name,
        }
    except ImportError:
        pass
    except Exception as e:
        return {"ok": False, "destination": "azure_blob", "error": str(e)}

    # az CLI
    cmd = [
        "az",
        "storage",
        "blob",
        "upload",
        "--container-name",
        container,
        "--name",
        blob_name,
        "--file",
        str(local_path),
        "--overwrite",
    ]
    if conn:
        cmd.extend(["--connection-string", conn])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return {"ok": False, "destination": "azure_blob", "error": (r.stderr or r.stdout or "az failed")[:500]}
        return {"ok": True, "destination": "azure_blob", "container": container, "blob": blob_name, "via": "az-cli"}
    except FileNotFoundError:
        return {
            "ok": False,
            "destination": "azure_blob",
            "error": "Install azure-storage-blob or Azure CLI (az)",
        }
    except Exception as e:
        return {"ok": False, "destination": "azure_blob", "error": str(e)}


def run_backup(
    mem: MemoryStore,
    *,
    scope: str = "global",
    project_id: str | None = None,
    project_path: str | None = None,
    session_id: str | None = None,
    include_private: bool | None = None,
    include_embeddings: bool | None = None,
    destinations: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Full backup: collect → local (usually) → optional AWS/Azure.

    destinations: subset of ["local", "aws", "azure"]; default = all enabled in config.
    """
    cfg = config or load_config()
    auto = cfg.get("auto") or {}
    if include_private is None:
        include_private = bool(auto.get("include_private", False))
    if include_embeddings is None:
        include_embeddings = bool(auto.get("include_embeddings", False))

    payload = collect_backup_payload(
        mem,
        scope=scope,
        project_id=project_id,
        project_path=project_path,
        session_id=session_id,
        include_private=include_private,
        include_embeddings=include_embeddings,
        include=cfg.get("include"),
    )

    dests = destinations
    if not dests:
        dests = []
        if (cfg.get("local") or {}).get("enabled", True):
            dests.append("local")
        if (cfg.get("aws") or {}).get("enabled"):
            dests.append("aws")
        if (cfg.get("azure") or {}).get("enabled"):
            dests.append("azure")
        if not dests:
            dests = ["local"]

    results: list[dict[str, Any]] = []
    local_path = None

    if "local" in dests:
        loc = cfg.get("local") or {}
        r = write_local_backup(
            payload,
            dest_dir=loc.get("path") or DEFAULT_LOCAL_DIR,
            as_zip=bool(loc.get("zip", True)),
            keep_last=int(loc.get("keep_last") or 20),
        )
        results.append(r)
        if r.get("ok"):
            local_path = r.get("path")

    # cloud uploads need a local file first
    if local_path is None and (("aws" in dests) or ("azure" in dests)):
        r = write_local_backup(payload, dest_dir=DEFAULT_LOCAL_DIR, as_zip=True)
        results.append({**r, "note": "staging for cloud upload"})
        local_path = r.get("path") if r.get("ok") else None

    if "aws" in dests and local_path:
        results.append(upload_s3(local_path, cfg.get("aws") or {}))
    if "azure" in dests and local_path:
        results.append(upload_azure(local_path, cfg.get("azure") or {}))

    ok = any(r.get("ok") for r in results)
    return {
        "ok": ok,
        "backup_id": payload.get("id"),
        "scope": scope,
        "project_id": project_id,
        "meta": payload.get("meta"),
        "results": results,
        "created_at": payload.get("created_at"),
    }


def list_local_backups(dest_dir: str | Path | None = None) -> dict[str, Any]:
    dest = Path(dest_dir or load_config().get("local", {}).get("path") or DEFAULT_LOCAL_DIR)
    items = []
    if dest.is_dir():
        for p in sorted(dest.glob("aether-backup-*"), key=lambda x: x.stat().st_mtime, reverse=True):
            items.append(
                {
                    "name": p.name,
                    "path": str(p),
                    "size": p.stat().st_size if p.is_file() else None,
                    "mtime": p.stat().st_mtime,
                    "type": "zip" if p.suffix == ".zip" else "dir",
                }
            )
    return {"ok": True, "dir": str(dest), "backups": items[:50]}


def set_auto_config(patch: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    if "auto" in patch and isinstance(patch["auto"], dict):
        cfg["auto"] = {**cfg.get("auto", {}), **patch["auto"]}
    for k in ("local", "aws", "azure", "include"):
        if k in patch and isinstance(patch[k], dict):
            cfg[k] = {**cfg.get(k, {}), **patch[k]}
    save_config(cfg)
    _auto_state["enabled"] = bool((cfg.get("auto") or {}).get("enabled"))
    _auto_state["interval_sec"] = int((cfg.get("auto") or {}).get("interval_sec") or 86400)
    return get_backup_status()


def run_auto_if_due(mem: MemoryStore) -> dict[str, Any] | None:
    cfg = load_config()
    auto = cfg.get("auto") or {}
    if not auto.get("enabled"):
        _auto_state["enabled"] = False
        return None
    _auto_state["enabled"] = True
    interval = int(auto.get("interval_sec") or 86400)
    _auto_state["interval_sec"] = interval
    last = _auto_state.get("last_run") or 0
    if time.time() - float(last) < interval:
        return None
    result = run_backup(
        mem,
        scope=str(auto.get("scope") or "global"),
        include_private=bool(auto.get("include_private", False)),
        include_embeddings=bool(auto.get("include_embeddings", False)),
        config=cfg,
    )
    _auto_state["last_run"] = time.time()
    _auto_state["last_result"] = {
        "ok": result.get("ok"),
        "backup_id": result.get("backup_id"),
        "results": result.get("results"),
    }
    return result
