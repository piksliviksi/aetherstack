"""System discovery — scan what is actually available before routing / inference."""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any


def _http(url: str, timeout: float = 3.0, headers: dict | None = None) -> tuple[int | None, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw[:500]
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            data = json.loads(body)
        except Exception:
            data = None
        return e.code, data
    except Exception as e:
        return None, {"error": str(e)}


def _tcp_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _run(cmd: list[str], timeout: float = 8.0) -> str:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return f""


def probe_ollama_endpoint(base: str, label: str) -> dict[str, Any]:
    base = base.rstrip("/")
    out: dict[str, Any] = {
        "label": label,
        "base": base,
        "reachable": False,
        "models": [],
        "version": None,
        "ps": [],
        "inference_hint": None,
    }
    code, body = _http(f"{base}/api/version", timeout=3.0)
    if code == 200 and isinstance(body, dict):
        out["version"] = body.get("version")
        out["reachable"] = True
    else:
        code2, _ = _http(f"{base}/", timeout=2.0)
        out["reachable"] = code2 is not None and code2 < 500
        if not out["reachable"]:
            out["error"] = body if isinstance(body, dict) else "unreachable"
            return out

    code, tags = _http(f"{base}/api/tags", timeout=5.0)
    if code == 200 and isinstance(tags, dict):
        for m in tags.get("models") or []:
            name = m.get("name") or m.get("model")
            if not name:
                continue
            out["models"].append(
                {
                    "name": name,
                    "size": m.get("size"),
                    "family": (m.get("details") or {}).get("family"),
                    "parameter_size": (m.get("details") or {}).get("parameter_size"),
                    "quantization": (m.get("details") or {}).get("quantization_level"),
                }
            )

    code, ps = _http(f"{base}/api/ps", timeout=3.0)
    if code == 200 and isinstance(ps, dict):
        for m in ps.get("models") or []:
            out["ps"].append(
                {
                    "name": m.get("name") or m.get("model"),
                    "size": m.get("size"),
                    "processor": m.get("processor") or m.get("details", {}).get("processor"),
                    "until": m.get("expires_at") or m.get("expires"),
                }
            )
            proc = str(m.get("processor") or "")
            if "GPU" in proc.upper():
                out["inference_hint"] = "gpu"
            elif "CPU" in proc.upper() and out["inference_hint"] != "gpu":
                out["inference_hint"] = "cpu"

    return out


def discover_ollama() -> dict[str, Any]:
    """Probe several candidate Ollama bases (container + host)."""
    candidates = []
    env = os.environ.get("OLLAMA_BASE_URL")
    if env:
        candidates.append((env, "OLLAMA_BASE_URL"))
    candidates.extend(
        [
            ("http://host.docker.internal:11434", "host.docker.internal"),
            ("http://127.0.0.1:11434", "localhost"),
            ("http://172.17.0.1:11434", "docker-bridge"),
        ]
    )
    # Optional fixed WSL IP from env (scripts write this)
    wsl_ip = os.environ.get("AETHER_WSL_OLLAMA_IP", "").strip()
    if wsl_ip:
        candidates.append((f"http://{wsl_ip}:11434", "wsl-ip"))

    seen: set[str] = set()
    endpoints: list[dict[str, Any]] = []
    for base, label in candidates:
        key = base.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        endpoints.append(probe_ollama_endpoint(base, label))

    primary = next((e for e in endpoints if e.get("reachable")), None)
    all_models: set[str] = set()
    for e in endpoints:
        for m in e.get("models") or []:
            n = m.get("name")
            if n:
                all_models.add(n)
                if ":" in n:
                    all_models.add(n.split(":", 1)[0])

    return {
        "primary": primary,
        "endpoints": endpoints,
        "all_model_names": sorted(all_models),
        "any_reachable": primary is not None,
    }


def discover_services() -> dict[str, Any]:
    litellm_base = os.environ.get("LITELLM_BASE_URL", "http://litellm:4000")
    hub_self = f"http://127.0.0.1:{os.environ.get('AETHER_HUB_PORT', '8766')}"
    redis_host = "redis"
    # When hub runs on host, use localhost names
    if os.environ.get("AETHER_DISCOVER_HOST_MODE", "").lower() in ("1", "true", "yes"):
        litellm_base = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000")
        redis_host = "127.0.0.1"

    key = os.environ.get("LITELLM_MASTER_KEY", "sk-aether-local")
    code, models = _http(
        f"{litellm_base.rstrip('/')}/v1/models",
        timeout=5.0,
        headers={"Authorization": f"Bearer {key}"},
    )
    litellm_ids: list[str] = []
    if code == 200 and isinstance(models, dict):
        litellm_ids = [m.get("id") for m in models.get("data") or [] if m.get("id")]

    redis_ok = _tcp_open(redis_host, 6379) or _tcp_open("127.0.0.1", 6379)
    webui = _tcp_open("open-webui", 8080) or _tcp_open("127.0.0.1", 3000)

    return {
        "litellm": {
            "base": litellm_base,
            "ok": code == 200,
            "http_status": code,
            "models": litellm_ids,
            "model_count": len(litellm_ids),
        },
        "redis": {"ok": redis_ok, "port": 6379},
        "open_webui": {"ok": webui, "hint": "http://127.0.0.1:3000"},
        "hub": {"port": int(os.environ.get("AETHER_HUB_PORT", "8766"))},
        "spend": discover_spend(litellm_base, key),
    }


def discover_spend(litellm_base: str, key: str) -> dict[str, Any]:
    """Cloud-provider spend vs the litellm_settings.max_budget guardrail. Local Ollama
    calls are free and excluded from this figure by LiteLLM itself."""
    code, body = _http(
        f"{litellm_base.rstrip('/')}/global/spend",
        timeout=5.0,
        headers={"Authorization": f"Bearer {key}"},
    )
    if code != 200 or not isinstance(body, dict):
        return {"ok": False}
    return {
        "ok": True,
        "spend": body.get("spend") or 0.0,
        "max_budget": body.get("max_budget"),
        "budget_duration": _litellm_budget_duration(),
    }


def _litellm_budget_duration() -> str | None:
    path = "/app/litellm_config.yaml"
    if not os.path.exists(path):
        return None
    try:
        import yaml

        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return (cfg.get("litellm_settings") or {}).get("budget_duration")
    except Exception:
        return None


# Primary + multi-account slots (personal / subscription vs enterprise API)
_PROVIDER_KEY_ROOTS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "GOOGLE_API_KEY",
    "MISTRAL_API_KEY",
)
_KEY_SLOTS = ("", "_PERSONAL", "_ENTERPRISE")


def discover_cloud_keys() -> dict[str, Any]:
    """
    Report which cloud keys are set.

    Per provider:
      {P}_API_KEY              primary (default model aliases)
      {P}_API_KEY_PERSONAL     personal / subscription account
      {P}_API_KEY_ENTERPRISE   work / org API account

    Both personal and enterprise can be set; use model aliases
    *-personal / *-enterprise simultaneously (e.g. claude-sonnet-4-personal
    and claude-sonnet-4-enterprise).
    """
    keys: dict[str, bool] = {
        "LITELLM_MASTER_KEY": bool(os.environ.get("LITELLM_MASTER_KEY", "").strip()),
    }
    by_provider: dict[str, dict[str, bool]] = {}
    for root in _PROVIDER_KEY_ROOTS:
        prov = root.replace("_API_KEY", "").lower()
        slots: dict[str, bool] = {}
        for suf in _KEY_SLOTS:
            name = f"{root}{suf}" if suf else root
            present = bool(os.environ.get(name, "").strip())
            keys[name] = present
            slot = "primary" if not suf else suf.lstrip("_").lower()
            slots[slot] = present
        by_provider[prov] = slots

    any_cloud = any(keys.get(r) or keys.get(f"{r}_PERSONAL") or keys.get(f"{r}_ENTERPRISE") for r in _PROVIDER_KEY_ROOTS)
    multi = {
        p: s
        for p, s in by_provider.items()
        if sum(1 for v in s.values() if v) >= 2
    }
    return {
        "present": keys,
        "by_provider": by_provider,
        "multi_account_providers": multi,
        "any_cloud": any_cloud,
        "slots": ["primary", "personal", "enterprise"],
        "note": "Use alias suffixes -personal / -enterprise to call two accounts at once.",
    }


def discover_runtime() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "in_docker": os.path.exists("/.dockerenv"),
        "hostname": socket.gethostname(),
    }


def discover_gpu_hints() -> dict[str, Any]:
    """Best-effort GPU / AMD compute-engine hints (limited inside containers)."""
    hints: dict[str, Any] = {
        "nvidia_smi": None,
        "rocminfo": None,
        "amd_compute_engines": [],
        "notes": [],
    }
    if shutil.which("nvidia-smi"):
        out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], timeout=5)
        if out and "failed" not in out.lower():
            hints["nvidia_smi"] = out.splitlines()[:4]
    if shutil.which("rocminfo"):
        out = _run(["rocminfo"], timeout=8)
        names = [ln.strip() for ln in out.splitlines() if "Marketing Name:" in ln]
        hints["rocminfo"] = names[:8]
        # Parse GPU agents → compute units (engines)
        engines: list[dict[str, Any]] = []
        cur: dict[str, Any] = {}
        for ln in out.splitlines():
            s = ln.strip()
            if s.startswith("Agent "):
                if cur.get("device_type") == "GPU":
                    engines.append(cur)
                cur = {"agent": s}
            elif "Marketing Name:" in s:
                cur["name"] = s.split(":", 1)[-1].strip()
            elif "Device Type:" in s:
                cur["device_type"] = s.split(":", 1)[-1].strip()
            elif "Compute Unit:" in s:
                try:
                    cur["compute_units"] = int(s.split(":", 1)[-1].strip().split("(")[0].strip())
                except ValueError:
                    cur["compute_units"] = s.split(":", 1)[-1].strip()
            elif "Name:" in s and "gfx" in s.lower():
                cur["gfx"] = s.split(":", 1)[-1].strip()
        if cur.get("device_type") == "GPU":
            engines.append(cur)
        hints["amd_compute_engines"] = engines
        if engines:
            total_cu = sum(
                int(e["compute_units"])
                for e in engines
                if isinstance(e.get("compute_units"), int)
            )
            hints["amd_total_compute_units"] = total_cu or None
            hints["notes"].append(
                f"AMD compute engines: {len(engines)} GPU agent(s), ~{total_cu or '?'} CUs — "
                "inference needs Ollama ROCm package (not CUDA-only install)"
            )
        elif any("Radeon" in n or "AMD" in n for n in names):
            hints["notes"].append("rocminfo sees AMD GPU — Ollama still needs ROCm *libs* in its package")
    # Host scan can enrich with WSL facts
    if os.environ.get("HSA_OVERRIDE_GFX_VERSION"):
        hints["HSA_OVERRIDE_GFX_VERSION"] = os.environ["HSA_OVERRIDE_GFX_VERSION"]
    if os.environ.get("HSA_ENABLE_DXG_DETECTION"):
        hints["HSA_ENABLE_DXG_DETECTION"] = os.environ["HSA_ENABLE_DXG_DETECTION"]
    return hints


def build_recommendations(report: dict[str, Any]) -> list[dict[str, str]]:
    recs: list[dict[str, str]] = []
    ollama = report.get("ollama") or {}
    services = report.get("services") or {}
    keys = report.get("cloud_keys") or {}
    host = report.get("host_scan") or {}

    if not ollama.get("any_reachable"):
        recs.append(
            {
                "severity": "high",
                "code": "ollama_down",
                "action": "Start Ollama (WSL ROCm preferred on AMD, or Windows host)",
                "detail": "No Ollama answered on probed endpoints (:11434).",
            }
        )
    else:
        models = ollama.get("all_model_names") or []
        if not models:
            recs.append(
                {
                    "severity": "high",
                    "code": "no_models",
                    "action": "ollama pull tinyllama   # or llama3.1:8b if RAM allows",
                    "detail": "Ollama is up but has zero models.",
                }
            )
        primary = ollama.get("primary") or {}
        if primary.get("inference_hint") == "cpu":
            recs.append(
                {
                    "severity": "high",
                    "code": "cpu_inference",
                    "action": "sudo bash aether-amd/ensure-backend.sh  # ROCm runners; then ollama ps must show GPU",
                    "detail": "Loaded runner reported CPU — AMD CUs idle until Ollama ROCm package is installed (WSL often ships CUDA/CPU only).",
                }
            )
        # No loaded model yet, but reachable: still flag likely CPU-only stack when host scan says so
        if (
            not primary.get("inference_hint")
            and host.get("ollama_missing_rocm_libs")
            and (host.get("radeon_visible_to_rocminfo") or host.get("amd_compute_engines"))
        ):
            recs.append(
                {
                    "severity": "high",
                    "code": "likely_cpu_ollama",
                    "action": "sudo bash aether-amd/ensure-backend.sh",
                    "detail": "Host scan: ROCm runner libs missing under /usr/local/lib/ollama/rocm* while Radeon is visible.",
                }
            )

    if not (services.get("litellm") or {}).get("ok"):
        recs.append(
            {
                "severity": "high",
                "code": "litellm_down",
                "action": "docker compose up -d litellm",
                "detail": "LiteLLM /v1/models not reachable with master key.",
            }
        )

    if not (services.get("redis") or {}).get("ok"):
        recs.append(
            {
                "severity": "medium",
                "code": "redis_down",
                "action": "docker compose up -d redis",
                "detail": "Redis not accepting connections — cache/memory degraded.",
            }
        )

    if not (keys.get("any_cloud")):
        recs.append(
            {
                "severity": "info",
                "code": "no_cloud_keys",
                "action": "Set {PROVIDER}_API_KEY and/or _PERSONAL / _ENTERPRISE in .env (docs/MULTI-KEYS.md)",
                "detail": "Local-only mode is fine if Ollama has models. Multi-account slots can be set together.",
            }
        )

    # Host scan extras (from PowerShell/bash agent)
    if host.get("windows_ollama_and_wsl_both"):
        recs.append(
            {
                "severity": "high",
                "code": "dual_ollama",
                "action": "Stop Windows Ollama; use WSL ROCm Ollama + portproxy to localhost:11434",
                "detail": "Two Ollamas fight for :11434; Docker usually hits the wrong one.",
            }
        )
    if host.get("ollama_missing_rocm_libs"):
        recs.append(
            {
                "severity": "high",
                "code": "no_rocm_libs",
                "action": "sudo bash aether-amd/ensure-backend.sh  # userspace AMD adapter + ROCm Ollama",
                "detail": "AMD CUs visible via rocminfo/DXG but Ollama has no /rocm runner — stock install skips ROCm when lspci has no amdgpu (typical WSL). Not a kernel driver issue.",
            }
        )
    engines = (report.get("gpu_hints") or {}).get("amd_compute_engines") or host.get(
        "amd_compute_engines"
    )
    if engines and host.get("ollama_missing_rocm_libs"):
        cu = sum(
            int(e.get("compute_units") or 0)
            for e in engines
            if str(e.get("compute_units", "")).isdigit() or isinstance(e.get("compute_units"), int)
        )
        recs.append(
            {
                "severity": "high",
                "code": "amd_compute_idle",
                "action": "Install ROCm Ollama + restart; verify ollama ps shows GPU",
                "detail": f"AMD compute engines detected (~{cu or '?'} CUs) but not used for LLM until ROCm runners load.",
            }
        )
    if host.get("localhost_11434_broken") and host.get("wsl_ollama_ip"):
        recs.append(
            {
                "severity": "high",
                "code": "port_forward",
                "action": f".\\scripts\\ensure-wsl-ollama.ps1  # proxy → {host.get('wsl_ollama_ip')}:11434",
                "detail": "WSL Ollama up on eth0 but Windows localhost:11434 refused.",
            }
        )

    if not recs:
        recs.append(
            {
                "severity": "ok",
                "code": "ready",
                "action": "Stack looks usable — pick a model via /api/route",
                "detail": "Discovery found a working path.",
            }
        )
    return recs


def full_discover(host_scan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run full discovery. Optional host_scan merges Windows/WSL-specific facts."""
    t0 = time.time()
    report: dict[str, Any] = {
        "ts": time.time(),
        "runtime": discover_runtime(),
        "ollama": discover_ollama(),
        "services": discover_services(),
        "cloud_keys": discover_cloud_keys(),
        "gpu_hints": discover_gpu_hints(),
        "host_scan": host_scan or {},
    }
    report["recommendations"] = build_recommendations(report)
    report["summary"] = {
        "ollama_ok": bool((report["ollama"] or {}).get("any_reachable")),
        "ollama_models": len((report["ollama"] or {}).get("all_model_names") or []),
        "litellm_ok": bool(((report["services"] or {}).get("litellm") or {}).get("ok")),
        "redis_ok": bool(((report["services"] or {}).get("redis") or {}).get("ok")),
        "cloud_keys": bool((report["cloud_keys"] or {}).get("any_cloud")),
        "top_issue": next(
            (r for r in report["recommendations"] if r.get("severity") in ("high", "medium")),
            report["recommendations"][0] if report["recommendations"] else None,
        ),
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
    return report


def print_report_text(report: dict[str, Any]) -> str:
    lines = []
    s = report.get("summary") or {}
    lines.append("AetherStack system scan")
    lines.append("=" * 40)
    lines.append(
        f"Ollama: {'OK' if s.get('ollama_ok') else 'DOWN'}  "
        f"models={s.get('ollama_models')}  "
        f"LiteLLM: {'OK' if s.get('litellm_ok') else 'DOWN'}  "
        f"Redis: {'OK' if s.get('redis_ok') else 'DOWN'}"
    )
    ollama = report.get("ollama") or {}
    for ep in ollama.get("endpoints") or []:
        st = "UP" if ep.get("reachable") else "down"
        names = ", ".join(m.get("name", "") for m in (ep.get("models") or [])[:6]) or "—"
        lines.append(f"  [{st}] {ep.get('label')}: {ep.get('base')}  models: {names}")
    lines.append("Recommendations:")
    for r in report.get("recommendations") or []:
        lines.append(f"  ({r.get('severity')}) {r.get('action')}")
        if r.get("detail"):
            lines.append(f"           {r.get('detail')}")
    return "\n".join(lines)
