"""
Optional auto-install of missing packages / models / services.
Default OFF. Host script does elevated installs; hub can plan + safe applies.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
BOOT_PATH = Path(os.environ.get("AETHER_BOOTSTRAP_PATH", str(ROOT / "bootstrap.yaml")))

_state: dict[str, Any] = {
    "enabled": False,
    "auto_apply": False,
    "last_plan": None,
    "last_run": None,
}


def load_bootstrap_config(path: Path | None = None) -> dict[str, Any]:
    p = path or BOOT_PATH
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("invalid bootstrap.yaml")
    return data


def get_bootstrap_state() -> dict[str, Any]:
    env_on = os.environ.get("AETHER_AUTO_INSTALL", "").strip().lower() in ("1", "true", "yes", "on")
    return {
        **_state,
        "enabled": bool(_state.get("enabled") or env_on),
        "env_AETHER_AUTO_INSTALL": env_on,
    }


def set_bootstrap_state(patch: dict[str, Any]) -> dict[str, Any]:
    if "enabled" in patch and patch["enabled"] is not None:
        _state["enabled"] = bool(patch["enabled"])
    if "auto_apply" in patch and patch["auto_apply"] is not None:
        _state["auto_apply"] = bool(patch["auto_apply"])
    _state["updated_at"] = time.time()
    return get_bootstrap_state()


def _run(cmd: list[str], timeout: float = 600.0) -> dict[str, Any]:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        return {
            "ok": r.returncode == 0,
            "code": r.returncode,
            "stdout": (r.stdout or "")[-4000:],
            "stderr": (r.stderr or "")[-2000:],
            "cmd": cmd,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "cmd": cmd}


def build_install_plan(discover: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """From discover report → list of install actions (not yet applied)."""
    cfg = cfg or load_bootstrap_config()
    cats = cfg.get("categories") or {}
    limits = cfg.get("limits") or {}
    host = discover.get("host_scan") or {}
    ollama = discover.get("ollama") or {}
    services = discover.get("services") or {}
    runtime = discover.get("runtime") or {}

    actions: list[dict[str, Any]] = []
    models_have = set(ollama.get("all_model_names") or [])
    # also bare names
    for m in list(models_have):
        if ":" in m:
            models_have.add(m.split(":", 1)[0])

    # --- python pip ---
    pip_cfg = cats.get("python_pip") or {}
    for pkg in pip_cfg.get("packages") or []:
        try:
            __import__(pkg.split("[")[0].replace("-", "_") if pkg != "PyYAML" else "yaml")
            present = True
        except ImportError:
            # redis, PyYAML, psutil special-case
            mod = {"PyYAML": "yaml", "redis": "redis", "psutil": "psutil"}.get(pkg, pkg)
            try:
                __import__(mod)
                present = True
            except ImportError:
                present = False
        if not present:
            actions.append(
                {
                    "id": f"pip:{pkg}",
                    "category": "python_pip",
                    "safe": True,
                    "where": "hub_or_host",
                    "title": f"pip install {pkg}",
                    "cmd": [sys.executable, "-m", "pip", "install", "--user", pkg],
                    "reason": f"Python package {pkg} not importable",
                }
            )

    # --- ollama models ---
    om = cats.get("ollama_models") or {}
    if ollama.get("any_reachable"):
        essential = list(om.get("essential") or [])
        optional = list(om.get("optional") or [])
        large = list(om.get("large") or [])
        ram = host.get("ram_gb") or host.get("free_ram_gb")
        pull_list: list[str] = []
        for name in essential:
            bare = name.split(":")[0]
            if name not in models_have and bare not in models_have:
                pull_list.append(name)
        for name in optional:
            bare = name.split(":")[0]
            if name not in models_have and bare not in models_have:
                pull_list.append(name)
        min_ram = float(limits.get("skip_large_models_if_ram_gb_below") or 10)
        if ram is None or float(ram) >= min_ram:
            if not (cfg.get("defaults") or {}).get("prefer_small_models", True) or not pull_list:
                for name in large:
                    bare = name.split(":")[0]
                    if name not in models_have and bare not in models_have:
                        pull_list.append(name)
        max_pulls = int(limits.get("max_ollama_pulls_per_run") or 2)
        base = ((ollama.get("primary") or {}).get("base") or "http://127.0.0.1:11434").rstrip("/")
        for name in pull_list[:max_pulls]:
            actions.append(
                {
                    "id": f"ollama_pull:{name}",
                    "category": "ollama_models",
                    "safe": True,
                    "where": "host",  # ollama CLI on host/WSL
                    "title": f"ollama pull {name}",
                    "cmd": ["ollama", "pull", name],
                    "env_hint": {"OLLAMA_HOST": base},
                    "reason": f"Model {name} not present on Ollama",
                    "api_pull": {"url": f"{base}/api/pull", "body": {"name": name, "stream": False}},
                }
            )
    else:
        actions.append(
            {
                "id": "ollama_start",
                "category": "host_tools",
                "safe": False,
                "where": "host",
                "title": "Start or install Ollama",
                "script": "ensure-wsl-ollama.ps1 | start Ollama app",
                "reason": "Ollama not reachable on any endpoint",
            }
        )

    # --- docker compose services ---
    dc = cats.get("docker_compose_services") or {}
    litellm_ok = ((services.get("litellm") or {}).get("ok"))
    redis_ok = ((services.get("redis") or {}).get("ok"))
    # hub can't easily know container names from inside without host_scan
    containers = set(host.get("containers") or [])
    wanted = list(dc.get("services") or [])
    missing_svc = []
    name_map = {
        "redis": "aether-redis",
        "litellm": "aether-litellm",
        "aether-hub": "aether-hub",
        "open-webui": "aether-open-webui",
    }
    if containers:
        for svc in wanted:
            cname = name_map.get(svc, svc)
            if cname not in containers and svc not in containers:
                # also check service health flags
                if svc == "redis" and redis_ok:
                    continue
                if svc == "litellm" and litellm_ok:
                    continue
                missing_svc.append(svc)
    if missing_svc:
        actions.append(
            {
                "id": "compose_up:" + ",".join(missing_svc),
                "category": "docker_compose_services",
                "safe": True,
                "where": "host",
                "title": f"docker compose up -d {' '.join(missing_svc)}",
                "cmd": ["docker", "compose", "up", "-d", *missing_svc],
                "reason": f"Services not running: {missing_svc}",
            }
        )

    # --- docker images (host) ---
    di = cats.get("docker_images") or {}
    for img in di.get("images") or []:
        actions.append(
            {
                "id": f"docker_pull:{img}",
                "category": "docker_images",
                "safe": True,
                "where": "host",
                "title": f"docker pull {img}",
                "cmd": ["docker", "pull", img],
                "reason": f"Ensure image present: {img}",
                "optional": True,  # only if compose would need it
            }
        )

    # --- host elevated ---
    if host.get("ollama_missing_rocm_libs") or host.get("flags", {}).get("ollama_missing_rocm_libs"):
        actions.append(
            {
                "id": "wsl_ollama_rocm",
                "category": "host_tools",
                "safe": False,
                "elevated": True,
                "where": "wsl",
                "title": "Install Ollama ROCm package (AMD compute engines / CUs)",
                "script": "wsl -d Debian -- bash -lc 'sudo bash /mnt/d/llm/stack/scripts/install-ollama-rocm-wsl.sh'",
                "reason": "WSL exposes GPU via DXG/rocminfo, not lspci — force ollama-linux-amd64-rocm so HIP uses CUs",
            }
        )
    if host.get("localhost_11434_broken") or host.get("flags", {}).get("localhost_11434_broken"):
        actions.append(
            {
                "id": "wsl_portproxy",
                "category": "host_tools",
                "safe": False,
                "elevated": True,
                "where": "windows",
                "title": "Port-forward localhost:11434 → WSL Ollama",
                "script": ".\\scripts\\ensure-wsl-ollama.ps1",
                "reason": "WSL Ollama up but Windows localhost:11434 refused",
            }
        )
    if host.get("windows_ollama_and_wsl_both") or host.get("flags", {}).get("windows_ollama_and_wsl_both"):
        actions.append(
            {
                "id": "stop_windows_ollama",
                "category": "host_tools",
                "safe": False,
                "where": "windows",
                "title": "Stop Windows Ollama (prefer WSL ROCm for Radeon)",
                "script": "Stop-Process -Name ollama* -Force",
                "reason": "Two Ollama instances fight for :11434",
            }
        )

    # de-dup optional docker pulls if not needed
    if not missing_svc and litellm_ok and redis_ok:
        actions = [a for a in actions if a.get("category") != "docker_images"]

    return {
        "ts": time.time(),
        "enabled": get_bootstrap_state().get("enabled"),
        "action_count": len(actions),
        "safe_count": sum(1 for a in actions if a.get("safe")),
        "elevated_count": sum(1 for a in actions if a.get("elevated") or not a.get("safe")),
        "actions": actions,
        "note": "Auto-install is OFF by default. Enable then run with confirm.",
    }


def apply_plan(
    plan: dict[str, Any],
    *,
    confirm: bool = False,
    only_safe: bool = True,
    categories: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute install actions. Requires bootstrap enabled + confirm."""
    st = get_bootstrap_state()
    if not st.get("enabled") and not dry_run:
        return {
            "ok": False,
            "error": "auto-install disabled. POST /api/bootstrap {\"enabled\":true} or set AETHER_AUTO_INSTALL=1",
        }
    if not confirm and not st.get("auto_apply") and not dry_run:
        return {
            "ok": False,
            "error": "confirm=true required (or auto_apply). Dry-run with dry_run=true.",
        }

    results = []
    cats = set(categories) if categories else None
    in_docker = os.path.exists("/.dockerenv")

    for action in plan.get("actions") or []:
        if cats and action.get("category") not in cats:
            continue
        if only_safe and not action.get("safe"):
            results.append({**action, "status": "skipped", "reason": "not safe for auto (host/elevated)"})
            continue
        if action.get("where") == "host" and in_docker and action.get("category") != "python_pip":
            # Hub container: only run safe in-container actions; host deferred
            if action.get("category") in ("ollama_models",):
                # try HTTP pull API to host.docker.internal
                api = action.get("api_pull")
                if api and not dry_run:
                    res = _ollama_api_pull(api["url"], api["body"])
                    results.append({**action, "status": "ran" if res.get("ok") else "failed", "result": res})
                elif dry_run:
                    results.append({**action, "status": "dry_run", "via": "api_pull"})
                else:
                    results.append({**action, "status": "deferred_to_host", "script": "auto-install.ps1"})
                continue
            results.append({**action, "status": "deferred_to_host", "hint": "Run scripts/auto-install.ps1 -Yes"})
            continue

        cmd = action.get("cmd")
        if not cmd:
            results.append({**action, "status": "skipped", "reason": "no cmd (use host script)"})
            continue
        if dry_run:
            results.append({**action, "status": "dry_run"})
            continue
        # python pip only inside hub by default
        if action.get("category") == "python_pip":
            res = _run(cmd, timeout=300)
            results.append({**action, "status": "ok" if res.get("ok") else "failed", "result": res})
        elif action.get("category") == "ollama_models" and shutil.which("ollama"):
            res = _run(cmd, timeout=1800)
            results.append({**action, "status": "ok" if res.get("ok") else "failed", "result": res})
        else:
            results.append({**action, "status": "deferred_to_host"})

    out = {
        "ok": True,
        "dry_run": dry_run,
        "ts": time.time(),
        "results": results,
        "applied": sum(1 for r in results if r.get("status") in ("ok", "ran")),
        "failed": sum(1 for r in results if r.get("status") == "failed"),
        "deferred": sum(1 for r in results if r.get("status") == "deferred_to_host"),
    }
    _state["last_run"] = out
    return out


def _ollama_api_pull(url: str, body: dict) -> dict[str, Any]:
    import urllib.request

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return {"ok": True, "body": raw[:2000]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def plan_and_maybe_apply(
    discover: dict[str, Any],
    *,
    confirm: bool = False,
    dry_run: bool = True,
    only_safe: bool = True,
) -> dict[str, Any]:
    plan = build_install_plan(discover)
    _state["last_plan"] = plan
    st = get_bootstrap_state()
    if st.get("enabled") and (confirm or st.get("auto_apply")) and not dry_run:
        run = apply_plan(plan, confirm=True, only_safe=only_safe, dry_run=False)
        return {"plan": plan, "run": run}
    if dry_run:
        run = apply_plan(plan, confirm=True, only_safe=only_safe, dry_run=True)
        return {"plan": plan, "run": run}
    return {"plan": plan, "run": None, "hint": "Pass confirm=true with enabled to apply safe actions"}
