"""Collectors for live metrics, project disk impact, and system footprint."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Optional dependency — works without it
try:
    import psutil  # type: ignore
except ImportError:
    psutil = None  # type: ignore

HEAVY_DIR_NAMES = {
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".git",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    ".cache",
    "pods",
    ".gradle",
    ".idea",
    "vendor",
    ".turbo",
    "coverage",
    ".parcel-cache",
    "bower_components",
    ".terraform",
    "Checkpoints",
    "models",
    ".ollama",
    "huggingface",
    ".huggingface",
    "torch",
    "site-packages",
}

MANIFESTS = [
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "Pipfile",
    "environment.yml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.toml",
    "go.mod",
    "composer.json",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "CMakeLists.txt",
]


def _bytes_gb(n: float | int | None) -> float | None:
    if n is None:
        return None
    return round(float(n) / (1024**3), 3)


def _run(cmd: list[str], timeout: float = 8.0) -> str:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f""


def live_metrics() -> dict[str, Any]:
    """CPU, memory, disk space & throughput, GPU best-effort."""
    out: dict[str, Any] = {
        "ts": time.time(),
        "platform": platform.platform(),
        "cpu": {},
        "memory": {},
        "disks": [],
        "disk_io": {},
        "gpu": [],
        "backend": "psutil" if psutil else "fallback",
    }

    if psutil:
        out["cpu"] = {
            "percent": psutil.cpu_percent(interval=0.3),
            "count_logical": psutil.cpu_count(logical=True),
            "count_physical": psutil.cpu_count(logical=False),
            "load_avg": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        }
        vm = psutil.virtual_memory()
        out["memory"] = {
            "total_gb": _bytes_gb(vm.total),
            "available_gb": _bytes_gb(vm.available),
            "used_gb": _bytes_gb(vm.used),
            "percent": vm.percent,
        }
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            out["disks"].append(
                {
                    "device": part.device,
                    "mount": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": _bytes_gb(u.total),
                    "used_gb": _bytes_gb(u.used),
                    "free_gb": _bytes_gb(u.free),
                    "percent": u.percent,
                }
            )
        try:
            dio = psutil.disk_io_counters()
            if dio:
                # Sample twice for rates
                t0 = time.time()
                r0, w0 = dio.read_bytes, dio.write_bytes
                time.sleep(0.4)
                dio2 = psutil.disk_io_counters()
                dt = max(time.time() - t0, 0.001)
                out["disk_io"] = {
                    "read_mb_s": round((dio2.read_bytes - r0) / dt / (1024**2), 2),
                    "write_mb_s": round((dio2.write_bytes - w0) / dt / (1024**2), 2),
                    "read_count_delta": dio2.read_count - dio.read_count,
                    "write_count_delta": dio2.write_count - dio.write_count,
                }
        except Exception:
            out["disk_io"] = {}
    else:
        # Minimal fallback without psutil
        out["cpu"] = {"percent": None, "note": "pip install psutil for live CPU %"}
        if hasattr(os, "getloadavg"):
            out["cpu"]["load_avg"] = list(os.getloadavg())
        try:
            import shutil as sh

            total, used, free = sh.disk_usage(os.path.abspath(os.sep))
            out["disks"].append(
                {
                    "mount": os.path.abspath(os.sep),
                    "total_gb": _bytes_gb(total),
                    "used_gb": _bytes_gb(used),
                    "free_gb": _bytes_gb(free),
                    "percent": round(100 * used / total, 1) if total else None,
                }
            )
        except Exception:
            pass
        if sys.platform == "win32":
            # PowerShell free mem
            ps = _run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_OperatingSystem) | "
                    "Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json",
                ]
            )
            try:
                j = json.loads(ps)
                tot = float(j["TotalVisibleMemorySize"]) * 1024
                free = float(j["FreePhysicalMemory"]) * 1024
                out["memory"] = {
                    "total_gb": _bytes_gb(tot),
                    "available_gb": _bytes_gb(free),
                    "used_gb": _bytes_gb(tot - free),
                    "percent": round(100 * (tot - free) / tot, 1) if tot else None,
                }
            except Exception:
                out["memory"] = {"note": "unavailable"}

    out["gpu"] = _gpu_snapshot()
    return out


def _gpu_snapshot() -> list[dict[str, Any]]:
    gpus: list[dict[str, Any]] = []
    # NVIDIA
    nvs = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout=4,
    ).strip()
    if nvs and "NVIDIA-SMI" not in nvs.upper() and "not found" not in nvs.lower():
        for line in nvs.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                gpus.append(
                    {
                        "vendor": "nvidia",
                        "name": parts[0],
                        "util_percent": _f(parts[1]),
                        "mem_used_mb": _f(parts[2]),
                        "mem_total_mb": _f(parts[3]),
                        "temp_c": _f(parts[4]) if len(parts) > 4 else None,
                    }
                )
    # AMD Windows — best effort via PowerShell adapter name
    if sys.platform == "win32" and not gpus:
        ps = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json",
            ]
        )
        try:
            data = json.loads(ps)
            if isinstance(data, dict):
                data = [data]
            for d in data or []:
                name = d.get("Name") or ""
                if "Microsoft" in name and "Basic" in name:
                    continue
                gpus.append(
                    {
                        "vendor": "amd" if "AMD" in name or "Radeon" in name else "other",
                        "name": name,
                        "adapter_ram_gb": _bytes_gb(d.get("AdapterRAM") or 0) or None,
                        "driver": d.get("DriverVersion"),
                        "util_percent": None,
                        "note": "Live AMD util needs Adrenalin/ROCm tools; inference via WSL Ollama",
                    }
                )
        except Exception:
            pass
    # WSL rocminfo hint (name only if wsl present)
    if sys.platform == "win32":
        roc = _run(
            [
                "wsl",
                "-d",
                "Debian",
                "--",
                "bash",
                "-lc",
                "export PATH=/opt/rocm/bin:/usr/bin; "
                "export HSA_ENABLE_DXG_DETECTION=1; "
                "export LD_LIBRARY_PATH=/opt/rocm/lib:/usr/lib/wsl/lib; "
                "rocminfo 2>/dev/null | grep -E 'Marketing Name:|Device Type:' | head -20",
            ],
            timeout=12,
        )
        if "GPU" in roc and "Radeon" in roc:
            gpus.append(
                {
                    "vendor": "amd-wsl-rocm",
                    "name": "WSL ROCm agent detected",
                    "detail": roc.strip()[:500],
                    "note": "Use Ollama in WSL for GPU LLM; VS Code does not drive AMD GPU",
                }
            )
    return gpus


def _f(x: str) -> float | None:
    try:
        return float(x)
    except Exception:
        return None


def _dir_size(path: Path, max_files: int = 80_000) -> tuple[int, int]:
    total = 0
    n = 0
    try:
        for root, dirs, files in os.walk(path):
            # skip reparse points-ish on windows by catching errors
            for f in files:
                n += 1
                if n > max_files:
                    return total, n
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    continue
    except OSError:
        pass
    return total, n


def project_impact(project_path: str) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        return {"error": f"Not a directory: {root}"}

    heavy: list[dict[str, Any]] = []
    total_bytes = 0
    file_count = 0

    # Top-level sizes (faster overview)
    top_levels: list[dict[str, Any]] = []
    try:
        for child in root.iterdir():
            if child.name in (".", ".."):
                continue
            if child.is_file():
                try:
                    sz = child.stat().st_size
                except OSError:
                    sz = 0
                top_levels.append(
                    {"name": child.name, "type": "file", "size_gb": _bytes_gb(sz), "size_bytes": sz}
                )
                total_bytes += sz
                file_count += 1
            elif child.is_dir():
                sz, n = _dir_size(child)
                total_bytes += sz
                file_count += n
                entry = {
                    "name": child.name,
                    "type": "dir",
                    "size_gb": _bytes_gb(sz),
                    "size_bytes": sz,
                    "files_sampled": n,
                    "heavy": child.name in HEAVY_DIR_NAMES or child.name.startswith("."),
                }
                top_levels.append(entry)
                if entry["heavy"] or sz > 50 * 1024**2:
                    heavy.append(entry)
    except OSError as e:
        return {"error": str(e), "path": str(root)}

    top_levels.sort(key=lambda x: x.get("size_bytes") or 0, reverse=True)
    heavy.sort(key=lambda x: x.get("size_bytes") or 0, reverse=True)

    manifests = _read_manifests(root)
    suggestions = _suggestions(root, heavy, manifests, total_bytes)

    reclaimable = sum(
        h["size_bytes"]
        for h in heavy
        if h["name"]
        in {
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".tox",
            "dist",
            "build",
            ".next",
            ".turbo",
            "coverage",
            ".parcel-cache",
        }
    )

    return {
        "path": str(root),
        "total_gb": _bytes_gb(total_bytes),
        "total_bytes": total_bytes,
        "file_count_approx": file_count,
        "top_levels": top_levels[:40],
        "heavy_dirs": heavy[:30],
        "reclaimable_safe_gb": _bytes_gb(reclaimable),
        "manifests": manifests,
        "suggestions": suggestions,
    }


def _read_manifests(root: Path) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for name in MANIFESTS:
        p = root / name
        if not p.is_file():
            # shallow search one level
            matches = list(root.glob(name)) + list(root.glob(f"*/{name}"))
            if not matches:
                continue
            p = matches[0]
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:50_000]
        except OSError:
            continue
        info: dict[str, Any] = {"path": str(p.relative_to(root)), "bytes": p.stat().st_size}
        if name == "package.json":
            try:
                j = json.loads(text)
                deps = {**j.get("dependencies", {}), **j.get("devDependencies", {})}
                info["dependency_count"] = len(deps)
                info["deps_sample"] = list(deps.keys())[:40]
            except Exception:
                info["note"] = "parse error"
        elif name.startswith("requirements") or name == "requirements.txt":
            lines = [
                ln.strip()
                for ln in text.splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            info["dependency_count"] = len(lines)
            info["deps_sample"] = lines[:40]
            info["mentions_torch"] = any("torch" in ln.lower() for ln in lines)
            info["mentions_tensorflow"] = any("tensorflow" in ln.lower() for ln in lines)
        elif name == "pyproject.toml":
            info["mentions_torch"] = "torch" in text.lower()
            info["dependency_count"] = len(re.findall(r'^\s*"[^"]+"\s*=', text, re.M))
        found[name] = info
    return found


def _suggestions(
    root: Path, heavy: list[dict], manifests: dict, total_bytes: int
) -> list[dict[str, str]]:
    tips: list[dict[str, str]] = []
    for h in heavy:
        name = h["name"]
        gb = h.get("size_gb") or 0
        if name == "node_modules" and gb and gb > 0.2:
            tips.append(
                {
                    "severity": "medium",
                    "action": f"Remove/reinstall node_modules ({gb} GB)",
                    "command": "rm -rf node_modules && npm ci   # or pnpm/yarn",
                    "why": "Usually regenerable from lockfile; largest JS disk hog",
                }
            )
        if name in {".venv", "venv"} and gb and gb > 0.5:
            tips.append(
                {
                    "severity": "medium",
                    "action": f"Recreate Python venv ({gb} GB)",
                    "command": "rm -rf .venv && python -m venv .venv && pip install -r requirements.txt",
                    "why": "Virtualenvs are local; safe if requirements are pinned",
                }
            )
        if name == ".git" and gb and gb > 1:
            tips.append(
                {
                    "severity": "low",
                    "action": f"Git repo is large ({gb} GB) — consider git gc / LFS audit",
                    "command": "git gc --aggressive --prune=now",
                    "why": "History and LFS objects accumulate",
                }
            )
        if name in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}:
            tips.append(
                {
                    "severity": "safe",
                    "action": f"Delete cache dir {name} ({gb} GB)",
                    "command": f"rm -rf {name}",
                    "why": "Caches rebuild automatically",
                }
            )
    if total_bytes > 5 * 1024**3:
        tips.append(
            {
                "severity": "info",
                "action": "Project exceeds ~5 GB — move datasets/models to D: or external disk",
                "command": "# move large data out of system SSD; keep code on C:",
                "why": "Reduces OS disk pressure and backup size",
            }
        )
    if any(m.get("mentions_torch") for m in manifests.values()):
        tips.append(
            {
                "severity": "info",
                "action": "Torch detected in manifests — GPU wheels are large (CUDA/ROCm)",
                "command": "pip show torch | findstr /i location   # Windows\npip show torch | grep Location",
                "why": "System Python site-packages may hold multi-GB GPU builds",
            }
        )
    if not tips:
        tips.append(
            {
                "severity": "info",
                "action": "No heavy regenerable dirs found at top level",
                "command": "",
                "why": "Project looks lean or data is nested deeper",
            }
        )
    return tips


def system_footprint() -> dict[str, Any]:
    """WSL, Docker, Python, torch, Ollama, AetherStack-related disk."""
    info: dict[str, Any] = {
        "os": platform.platform(),
        "hostname": platform.node(),
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "installations": [],
        "paths": [],
    }

    # Docker
    docker_v = _run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=5).strip()
    if docker_v and "error" not in docker_v.lower():
        info["installations"].append({"name": "Docker", "version": docker_v.splitlines()[0][:40]})
        # disk usage summary
        du = _run(["docker", "system", "df", "--format", "{{json .}}"], timeout=15)
        info["docker_df_raw"] = du[:2000] if du else None

    # WSL
    if sys.platform == "win32":
        wsl_list = _run(["wsl", "-l", "-v"], timeout=8)
        info["wsl_list"] = wsl_list
        if "NAME" in wsl_list or "Debian" in wsl_list or "Ubuntu" in wsl_list:
            info["installations"].append({"name": "WSL", "detail": "installed"})
        # common vhdx locations
        local = os.environ.get("LOCALAPPDATA", "")
        user = os.environ.get("USERPROFILE", "")
        vhdx_roots = [
            Path(r"D:\wsl"),
            Path(user) / "AppData" / "Local" / "wsl" if user else None,
            # Shallow only under Packages (full rglob can hit broken reparse/junctions)
            Path(local) / "Packages" if local else None,
        ]
        for base in vhdx_roots:
            if not base or not base.exists():
                continue
            try:
                if base.name.lower() == "packages":
                    # only one level of package dirs + known LocalState paths
                    for pkg in base.iterdir():
                        if not pkg.is_dir():
                            continue
                        for cand in (
                            pkg / "LocalState" / "ext4.vhdx",
                            pkg / "LocalState" / "rootfs" / "ext4.vhdx",
                        ):
                            if cand.is_file():
                                try:
                                    sz = cand.stat().st_size
                                    info["paths"].append(
                                        {
                                            "kind": "wsl_vhdx",
                                            "path": str(cand),
                                            "size_gb": _bytes_gb(sz),
                                        }
                                    )
                                except OSError:
                                    pass
                else:
                    for vhdx in base.glob("**/ext4.vhdx"):
                        try:
                            sz = vhdx.stat().st_size
                            info["paths"].append(
                                {
                                    "kind": "wsl_vhdx",
                                    "path": str(vhdx),
                                    "size_gb": _bytes_gb(sz),
                                }
                            )
                        except OSError:
                            continue
            except OSError:
                continue

    # Ollama models
    home = Path.home()
    for p in [
        home / ".ollama" / "models",
        Path(os.environ.get("USERPROFILE", "")) / ".ollama" / "models",
        Path("/usr/share/ollama"),
    ]:
        if p and p.exists():
            sz, n = _dir_size(p, max_files=20_000)
            info["paths"].append(
                {"kind": "ollama_models", "path": str(p), "size_gb": _bytes_gb(sz), "files": n}
            )
            info["installations"].append({"name": "Ollama models dir", "path": str(p)})

    # Python / torch
    torch_info = _run(
        [sys.executable, "-c", "import torch; print(torch.__version__); print(torch.cuda.is_available())"],
        timeout=10,
    )
    if torch_info and "Error" not in torch_info and "No module" not in torch_info:
        lines = [ln.strip() for ln in torch_info.splitlines() if ln.strip()]
        info["installations"].append(
            {
                "name": "PyTorch",
                "version": lines[0] if lines else "?",
                "cuda_available": lines[1] if len(lines) > 1 else "?",
            }
        )
    else:
        info["installations"].append(
            {"name": "PyTorch", "present": False, "note": "not importable in this Python"}
        )

    # pip show sizes-ish
    for pkg in ("torch", "tensorflow", "onnxruntime", "transformers"):
        show = _run([sys.executable, "-m", "pip", "show", pkg], timeout=8)
        if "Name:" in show:
            loc = ""
            ver = ""
            for ln in show.splitlines():
                if ln.startswith("Location:"):
                    loc = ln.split(":", 1)[1].strip()
                if ln.startswith("Version:"):
                    ver = ln.split(":", 1)[1].strip()
            entry: dict[str, Any] = {"name": f"pip:{pkg}", "version": ver, "location": loc}
            if loc:
                pkg_dir = Path(loc) / pkg
                if pkg_dir.exists():
                    sz, _ = _dir_size(pkg_dir, max_files=30_000)
                    entry["size_gb"] = _bytes_gb(sz)
            info["installations"].append(entry)

    # NVIDIA / ROCm tools
    if shutil.which("nvidia-smi"):
        info["installations"].append({"name": "nvidia-smi", "present": True})
    if sys.platform == "win32":
        info["installations"].append(
            {
                "name": "AMD note",
                "detail": "Win11 VS Code does not use AMD GPU for LLMs; use WSL Ollama + ROCm/DXG",
            }
        )

    # AetherStack stack path
    here = Path(__file__).resolve().parent.parent
    if (here / "docker-compose.yml").exists():
        info["installations"].append({"name": "AetherStack repo", "path": str(here)})

    return info


def full_report(project_path: str | None = None) -> dict[str, Any]:
    return {
        "live": live_metrics(),
        "system": system_footprint(),
        "project": project_impact(project_path) if project_path else None,
    }
