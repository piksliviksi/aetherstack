#!/usr/bin/env bash
# Report AMD compute engines visible to ROCm/Ollama (WSL or bare metal Linux).
set -euo pipefail
export HSA_ENABLE_DXG_DETECTION="${HSA_ENABLE_DXG_DETECTION:-1}"
export HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION:-10.3.0}"
export LD_LIBRARY_PATH="/opt/rocm/lib:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="/opt/rocm/bin${PATH:+:$PATH}"

echo "AetherStack AMD compute status"
echo "=============================="
echo "host: $(hostname)  kernel: $(uname -r)"
echo "dxg: $(test -e /dev/dxg && echo present || echo missing)"
echo "kfd: $(test -e /dev/kfd && echo present || echo missing)"
echo "dri: $(ls /dev/dri 2>/dev/null | tr '\n' ' ' || echo none)"
echo

if command -v rocminfo >/dev/null 2>&1; then
  echo "--- ROCm agents (compute engines) ---"
  rocminfo 2>/dev/null | awk '
    /Agent [0-9]+/ { agent=$0 }
    /Marketing Name:/ { name=$0 }
    /Device Type:/ { type=$0 }
    /Compute Unit:/ { cu=$0 }
    /Name:.*gfx/ { gfx=$0 }
    /Device Type:.*GPU/ {
      print agent
      print name
      print type
      print cu
      print gfx
      print "---"
    }
  '
else
  echo "rocminfo: not installed"
fi

echo "--- Ollama runner libs ---"
if [[ -d /usr/local/lib/ollama/rocm ]]; then
  echo "ROCm package: YES (/usr/local/lib/ollama/rocm)"
  ls /usr/local/lib/ollama/rocm 2>/dev/null | head -8
else
  echo "ROCm package: NO — run scripts/install-ollama-rocm-wsl.sh"
  ls /usr/local/lib/ollama 2>/dev/null | head -15 || true
fi

echo
echo "--- Ollama process ---"
if curl -sf --max-time 2 http://127.0.0.1:11434/api/ps >/tmp/aether-ops.json 2>/dev/null; then
  python3 - <<'PY' 2>/dev/null || cat /tmp/aether-ops.json
import json
d=json.load(open("/tmp/aether-ops.json"))
for m in d.get("models") or []:
    print(m.get("name"), "processor=", m.get("processor") or m.get("details",{}).get("processor"), "size=", m.get("size"))
if not d.get("models"):
    print("(no models loaded — run a generate first)")
PY
else
  echo "Ollama API not reachable on :11434"
fi

echo
echo "Env: HSA_ENABLE_DXG_DETECTION=$HSA_ENABLE_DXG_DETECTION HSA_OVERRIDE_GFX_VERSION=$HSA_OVERRIDE_GFX_VERSION"
