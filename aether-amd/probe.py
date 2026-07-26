#!/usr/bin/env python3
"""Aether AMD userspace adapter — probe compute engines + Ollama backend readiness."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROFILES = ROOT / "profiles"


def _run(cmd: list[str], timeout: float = 12.0, env: dict | None = None) -> str:
    e = os.environ.copy()
    e.setdefault("HSA_ENABLE_DXG_DETECTION", "1")
    e.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
    ld = e.get("LD_LIBRARY_PATH", "")
    e["LD_LIBRARY_PATH"] = "/opt/rocm/lib:/usr/lib/wsl/lib" + (f":{ld}" if ld else "")
    e["PATH"] = "/opt/rocm/bin:" + e.get("PATH", "")
    if env:
        e.update(env)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e, errors="replace")
        return (r.stdout or "") + (r.stderr or "")
    except Exception as ex:
        return f""


def load_profiles() -> list[dict[str, Any]]:
    out = []
    if not PROFILES.is_dir():
        return out
    for fp in sorted(PROFILES.glob("*.json")):
        try:
            out.append(json.loads(fp.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def parse_rocminfo() -> list[dict[str, Any]]:
    raw = _run(["rocminfo"], timeout=15)
    if not raw.strip():
        return []
    engines: list[dict[str, Any]] = []
    cur: dict[str, Any] = {}
    for ln in raw.splitlines():
        s = ln.strip()
        if re.match(r"Agent \d+", s):
            if cur.get("device_type") == "GPU":
                engines.append(cur)
            cur = {"agent": s}
        elif "Marketing Name:" in s:
            cur["name"] = s.split(":", 1)[-1].strip()
        elif "Device Type:" in s:
            cur["device_type"] = s.split(":", 1)[-1].strip()
        elif "Compute Unit:" in s:
            part = s.split(":", 1)[-1].strip().split("(")[0].strip()
            try:
                cur["compute_units"] = int(part)
            except ValueError:
                cur["compute_units"] = part
        elif "Chip ID:" in s:
            cur["chip_id"] = s.split(":", 1)[-1].strip()
        elif "Name:" in s and "gfx" in s.lower():
            cur.setdefault("gfx", s.split(":", 1)[-1].strip())
    if cur.get("device_type") == "GPU":
        engines.append(cur)
    return engines


def match_profile(engines: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> dict[str, Any] | None:
    for eng in engines:
        chip = str(eng.get("chip_id") or "")
        name = str(eng.get("name") or "")
        for p in profiles:
            if p.get("id") == "generic-rdna2":
                continue
            for cid in p.get("chip_ids") or []:
                if cid.lower().replace("0x", "") in chip.lower().replace("0x", ""):
                    return p
            for mn in p.get("marketing_names") or []:
                if mn.lower() in name.lower():
                    return p
    # fallback
    for p in profiles:
        if p.get("id") == "generic-rdna2":
            return p
    return profiles[0] if profiles else None


def find_ollama_rocm_dirs(lib: Path | None = None) -> list[str]:
    """Ollama ROCm package may use lib/ollama/rocm or lib/ollama/rocm_v7_2 etc."""
    lib = lib or Path("/usr/local/lib/ollama")
    if not lib.is_dir():
        return []
    found: list[str] = []
    for p in sorted(lib.iterdir()):
        if not p.is_dir():
            continue
        name = p.name.lower()
        if name == "rocm" or name.startswith("rocm_"):
            # Prefer dirs that actually contain HIP ggml
            if any(p.glob("libggml-hip*")) or any(p.glob("*hip*")) or name == "rocm":
                found.append(str(p))
            elif name.startswith("rocm_"):
                found.append(str(p))
    return found


def ollama_backend() -> dict[str, Any]:
    lib = Path("/usr/local/lib/ollama")
    rocm_dirs = find_ollama_rocm_dirs(lib)
    return {
        "ollama_bin": bool(Path("/usr/local/bin/ollama").exists() or _run(["which", "ollama"]).strip()),
        "lib_dir": str(lib) if lib.is_dir() else None,
        "rocm_runners": bool(rocm_dirs),
        "rocm_dirs": rocm_dirs,
        "lib_children": sorted(p.name for p in lib.iterdir())[:20] if lib.is_dir() else [],
        "api": _run(["curl", "-sf", "--max-time", "2", "http://127.0.0.1:11434/"]).strip()[:80],
    }


def host_flags() -> dict[str, Any]:
    return {
        "dxg": Path("/dev/dxg").exists(),
        "kfd": Path("/dev/kfd").exists(),
        "dri": Path("/dev/dri").exists(),
        "in_wsl": "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
        if Path("/proc/version").exists()
        else False,
    }


def build_report() -> dict[str, Any]:
    engines = parse_rocminfo()
    profiles = load_profiles()
    profile = match_profile(engines, profiles)
    backend = ollama_backend()
    flags = host_flags()
    total_cu = sum(int(e["compute_units"]) for e in engines if isinstance(e.get("compute_units"), int))

    ready = bool(engines) and backend.get("rocm_runners") and bool(backend.get("api"))
    actions: list[str] = []
    if not engines:
        actions.append("Install ROCm userland + librocdxg; ensure HSA_ENABLE_DXG_DETECTION=1")
    if engines and not backend.get("rocm_runners"):
        actions.append("sudo bash aether-amd/ensure-backend.sh   # force Ollama ROCm package")
    if engines and backend.get("rocm_runners") and not backend.get("api"):
        actions.append("systemctl restart ollama && curl http://127.0.0.1:11434/")
    if ready:
        actions.append("ollama run tinyllama 'hi' && ollama ps   # expect GPU not 100% CPU")

    return {
        "adapter": "aether-amd-userspace",
        "kernel_driver": False,
        "note": "Uses vendor Adrenalin/amdgpu + ROCm; this adapter only glues profiles + Ollama HIP",
        "engines": engines,
        "total_compute_units": total_cu or None,
        "matched_profile": profile.get("id") if profile else None,
        "profile": profile,
        "ollama": backend,
        "host": flags,
        "compute_ready": ready,
        "actions": actions,
    }


def main() -> int:
    rep = build_report()
    print(json.dumps(rep, indent=2))
    print(file=sys.stderr)
    print("Aether AMD adapter (userspace - not a kernel driver)", file=sys.stderr)
    if rep.get("engines"):
        for e in rep["engines"]:
            print(
                f"  engine: {e.get('name')}  CUs={e.get('compute_units')}  gfx={e.get('gfx')}",
                file=sys.stderr,
            )
    else:
        print("  No GPU agents from rocminfo", file=sys.stderr)
    print(f"  Ollama ROCm runners: {rep['ollama'].get('rocm_runners')}", file=sys.stderr)
    print(f"  compute_ready: {rep.get('compute_ready')}", file=sys.stderr)
    for a in rep.get("actions") or []:
        print(f"  -> {a}", file=sys.stderr)
    return 0 if rep.get("engines") else 1


if __name__ == "__main__":
    raise SystemExit(main())
