"""
LLM combo catalog: tiers (Fable low / Sonnet / Opus / GPT…), situation packs,
export/import for GitHub, email, or local share.
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

from agents import apply_runtime_update, get_runtime, plan_event

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
CATALOG_PATH = Path(os.environ.get("AETHER_COMBOS_CATALOG", str(REPO / "combos" / "catalog.yaml")))
EXPORT_DIR = Path(os.environ.get("AETHER_COMBOS_EXPORT", str(REPO / "combos" / "export")))
IMPORT_DIR = Path(os.environ.get("AETHER_COMBOS_IMPORT", str(REPO / "combos" / "import")))

SCHEMA = "aetherstack.combo.v1"

_user_combos: dict[str, dict[str, Any]] = {}  # id -> combo (imported / created)


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    p = path or CATALOG_PATH
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("invalid combos catalog")
    return data


def _situation_to_combo(sid: str, body: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "id": sid,
        "label": body.get("label") or sid,
        "description": body.get("description") or "",
        "mode": body.get("mode") or "multi_agent",
        "token_saver": bool(body.get("token_saver", False)),
        "workers": body.get("workers"),
        "roles": body.get("roles") or {},
        "good_for": body.get("good_for") or [],
        "source": "catalog",
        "kind": "situation",
    }


def _tier_to_combo(tid: str, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "id": f"tier:{tid}",
        "label": body.get("label") or tid,
        "description": body.get("description") or "",
        "mode": "inline",
        "token_saver": body.get("tier") in ("low",),
        "roles": {
            "inline": {
                "model": body.get("model"),
                "maker": body.get("maker"),
                "fallbacks": body.get("fallbacks") or [],
            }
        },
        "tier": body.get("tier"),
        "good_for": body.get("good_for") or [],
        "aliases_display": body.get("aliases_display") or [],
        "cost": body.get("cost"),
        "source": "catalog",
        "kind": "tier",
        "notes": body.get("notes"),
    }


def list_combos() -> dict[str, Any]:
    cat = load_catalog()
    situations = {
        k: _situation_to_combo(k, v, cat) for k, v in (cat.get("situations") or {}).items()
    }
    tiers = {k: _tier_to_combo(k, v) for k, v in (cat.get("tiers") or {}).items()}
    bundled = {}
    if EXPORT_DIR.is_dir():
        for fp in sorted(EXPORT_DIR.glob("*.aether-combo.json")):
            try:
                with open(fp, encoding="utf-8") as f:
                    c = json.load(f)
                if isinstance(c, dict) and c.get("id"):
                    c["_file"] = str(fp.name)
                    bundled[c["id"]] = c
            except Exception:
                continue
    imported = copy.deepcopy(_user_combos)
    # load import dir
    if IMPORT_DIR.is_dir():
        for fp in sorted(IMPORT_DIR.glob("*.aether-combo.json")):
            try:
                with open(fp, encoding="utf-8") as f:
                    c = json.load(f)
                if isinstance(c, dict) and c.get("id"):
                    c["_file"] = str(fp)
                    imported[c["id"]] = c
            except Exception:
                continue

    return {
        "schema": SCHEMA,
        "tiers": tiers,
        "situations": situations,
        "bundled_exports": bundled,
        "imported": imported,
        "matrix_guide": cat.get("matrix_guide") or {},
        "how_to": {
            "launch": "POST /api/combos/{id}/launch",
            "export": "GET /api/combos/{id}/export",
            "import": "POST /api/combos/import  {combo: {...}} or multipart file",
            "plan": "POST /api/combos/{id}/plan  {goal: '...'} ",
            "github": "https://github.com/piksliviksi/aetherstack/tree/main/combos/export",
        },
    }


def get_combo(combo_id: str) -> dict[str, Any] | None:
    data = list_combos()
    if combo_id in data["situations"]:
        return data["situations"][combo_id]
    if combo_id in data["tiers"]:
        return data["tiers"][combo_id]
    if combo_id in data["bundled_exports"]:
        return data["bundled_exports"][combo_id]
    if combo_id in data["imported"]:
        return data["imported"][combo_id]
    # tier: prefix
    if combo_id.startswith("tier:"):
        tid = combo_id[5:]
        return data["tiers"].get(tid) or data["tiers"].get(f"tier:{tid}")
    return None


def combo_to_role_overrides(combo: dict[str, Any]) -> dict[str, Any]:
    roles = combo.get("roles") or {}
    out = {}
    for role, body in roles.items():
        if not isinstance(body, dict):
            continue
        pin = {}
        for k in ("model", "maker", "tier", "strategy", "max_cost"):
            if body.get(k) is not None:
                pin[k] = body[k]
        if pin:
            out[role] = pin
    return out


def launch_combo(combo_id: str, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply combo to agent runtime (mode, token_saver, role pins)."""
    combo = get_combo(combo_id)
    if not combo:
        raise ValueError(f"unknown combo: {combo_id}")
    patch: dict[str, Any] = {
        "mode": combo.get("mode") or "inline",
        "token_saver": bool(combo.get("token_saver", False)),
        "role_overrides": combo_to_role_overrides(combo),
        "clear_overrides": False,
    }
    # clear then set clean pins
    apply_runtime_update({"clear_overrides": True})
    runtime = apply_runtime_update(patch)
    return {
        "ok": True,
        "launched": combo_id,
        "label": combo.get("label"),
        "runtime": runtime,
        "combo": combo,
        "next": "POST /api/agents/plan with your goal, or use resolved models from GET /api/modes",
    }


def plan_with_combo(
    combo_id: str,
    snapshot: dict[str, Any],
    event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    combo = get_combo(combo_id)
    if not combo:
        raise ValueError(f"unknown combo: {combo_id}")
    event = dict(event or {})
    event.setdefault("mode", combo.get("mode"))
    event.setdefault("token_saver", combo.get("token_saver"))
    if combo.get("workers") is not None:
        event.setdefault("workers", combo.get("workers"))
    # merge role pins into event
    event["roles"] = combo_to_role_overrides(combo)
    # if event has roles already, event wins for keys present
    plan = plan_event(snapshot, event)
    plan["combo_id"] = combo_id
    plan["combo_label"] = combo.get("label")
    return plan


def export_combo(combo_id: str, *, write_file: bool = False) -> dict[str, Any]:
    combo = get_combo(combo_id)
    if not combo:
        raise ValueError(f"unknown combo: {combo_id}")
    payload = {
        "schema": SCHEMA,
        "id": combo.get("id") or combo_id,
        "label": combo.get("label"),
        "description": combo.get("description"),
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": combo.get("source") or "aether-hub-export",
        "mode": combo.get("mode"),
        "token_saver": combo.get("token_saver"),
        "workers": combo.get("workers"),
        "roles": combo.get("roles"),
        "good_for": combo.get("good_for"),
        "tier": combo.get("tier"),
        "notes": combo.get("notes"),
        "aliases_display": combo.get("aliases_display"),
    }
    # strip internal keys
    payload = {k: v for k, v in payload.items() if v is not None and not str(k).startswith("_")}
    if write_file:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(payload["id"]))
        fp = EXPORT_DIR / f"{safe}.aether-combo.json"
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        payload["_written"] = str(fp)
    return payload


def import_combo(raw: dict[str, Any] | str, *, persist: bool = True) -> dict[str, Any]:
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = dict(raw)
    if data.get("schema") and data.get("schema") != SCHEMA:
        # accept forward-compatible minor
        if not str(data.get("schema", "")).startswith("aetherstack.combo"):
            raise ValueError(f"unsupported schema: {data.get('schema')}")
    cid = data.get("id") or f"imported-{uuid.uuid4().hex[:8]}"
    data["id"] = cid
    data["schema"] = SCHEMA
    data["source"] = data.get("source") or "import"
    data["imported_at"] = time.time()
    _user_combos[cid] = data
    if persist:
        IMPORT_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in cid)
        fp = IMPORT_DIR / f"{safe}.aether-combo.json"
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        data["_file"] = str(fp)
    return {"ok": True, "id": cid, "combo": data, "launch": f"POST /api/combos/{cid}/launch"}


def guide_table() -> list[dict[str, Any]]:
    """Human matrix: situation × recommended tiers."""
    cat = load_catalog()
    tiers = cat.get("tiers") or {}
    rows = []
    for sit, body in (cat.get("situations") or {}).items():
        rows.append(
            {
                "situation": sit,
                "label": body.get("label"),
                "mode": body.get("mode"),
                "token_saver": body.get("token_saver"),
                "mastermind": ((body.get("roles") or {}).get("mastermind") or {}).get("model")
                or ((body.get("roles") or {}).get("inline") or {}).get("model"),
                "supervisor": ((body.get("roles") or {}).get("supervisor") or {}).get("model"),
                "worker": ((body.get("roles") or {}).get("worker") or {}).get("model"),
                "good_for": body.get("good_for"),
            }
        )
    tier_rows = [
        {
            "id": k,
            "label": v.get("label"),
            "tier": v.get("tier"),
            "model": v.get("model"),
            "good_for": v.get("good_for"),
            "display_aliases": v.get("aliases_display"),
        }
        for k, v in tiers.items()
    ]
    return {"situations": rows, "tiers": tier_rows, "matrix_guide": cat.get("matrix_guide")}
