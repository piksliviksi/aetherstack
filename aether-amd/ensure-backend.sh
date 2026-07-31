#!/usr/bin/env bash
# Apply Aether AMD userspace adapter: device profile + Ollama ROCm backend.
# NOT a kernel driver installer — does not replace AMD Adrenalin / amdgpu.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK="$(cd "$ROOT/.." && pwd)"

echo "Aether AMD adapter — ensure compute backend"
echo "==========================================="

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Need root for dids/systemd/ollama libs: sudo $0" >&2
  exit 1
fi

# Probe (as normal env)
export HSA_ENABLE_DXG_DETECTION=1
export HSA_OVERRIDE_GFX_VERSION=10.3.0
export LD_LIBRARY_PATH="/opt/rocm/lib:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

PROFILE_JSON=""
if command -v python3 >/dev/null; then
  PROFILE_JSON="$(python3 "$ROOT/probe.py" 2>/dev/null || true)"
  echo "$PROFILE_JSON" | python3 -m json.tool 2>/dev/null | head -40 || true
fi

# Apply dids from profile or default RX 6600 XT
DIDS_DIR="/opt/rocm/share/rocdxg"
DIDS_FILE="${DIDS_DIR}/dids.conf"
mkdir -p "$DIDS_DIR"
LINE="0x73FF,10,3,2"
if [[ -n "$PROFILE_JSON" ]]; then
  LINE="$(echo "$PROFILE_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); p=d.get('profile') or {}; print(p.get('rocdxg_dids_line') or '0x73FF,10,3,2')" 2>/dev/null || echo "$LINE")"
  GFX="$(echo "$PROFILE_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); p=d.get('profile') or {}; print(p.get('hsa_override_gfx_version') or '10.3.0')" 2>/dev/null || echo "10.3.0")"
else
  GFX="10.3.0"
fi

if [[ -n "$LINE" ]] && ! grep -qF "$LINE" "$DIDS_FILE" 2>/dev/null; then
  echo "Appending dids: $LINE"
  echo "$LINE" >> "$DIDS_FILE"
fi
# also ship file copy
if [[ -f "$ROOT/dids/rx6600xt.conf" ]]; then
  grep -v '^#' "$ROOT/dids/rx6600xt.conf" | while read -r l; do
    [[ -z "$l" ]] && continue
    grep -qF "$l" "$DIDS_FILE" 2>/dev/null || echo "$l" >> "$DIDS_FILE"
  done
fi

# Force Ollama ROCm package (real compute runner).
# Layout may be lib/ollama/rocm or lib/ollama/rocm_v7_2 (newer packages).
has_rocm=0
if [[ -d /usr/local/lib/ollama/rocm ]]; then
  has_rocm=1
elif compgen -G "/usr/local/lib/ollama/rocm_*" >/dev/null 2>&1; then
  has_rocm=1
fi
if [[ "$has_rocm" -eq 0 ]]; then
  echo "Ollama ROCm runners missing — installing..."
  bash "$STACK/scripts/install-ollama-rocm-wsl.sh"
else
  echo "Ollama ROCm runners: present ($(ls -d /usr/local/lib/ollama/rocm* 2>/dev/null | tr '\n' ' '))"
  # still refresh systemd drop-in
  mkdir -p /etc/systemd/system/ollama.service.d
  cat >/etc/systemd/system/ollama.service.d/aether-amd-compute.conf <<EOF
[Service]
Environment=OLLAMA_HOST=0.0.0.0:11434
Environment=OLLAMA_ORIGINS=*
Environment=HSA_ENABLE_DXG_DETECTION=1
Environment=HSA_OVERRIDE_GFX_VERSION=${GFX}
Environment=LD_LIBRARY_PATH=/opt/rocm/lib:/usr/lib/wsl/lib
Environment=PATH=/opt/rocm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/wsl/lib
Environment=HIP_VISIBLE_DEVICES=0
Environment=ROCR_VISIBLE_DEVICES=0
Environment=OLLAMA_VULKAN=false
# llama.cpp automatic memory fitting hangs on ROCm/DXG before model load.
Environment=LLAMA_ARG_FIT=off
EOF
  systemctl daemon-reload
  systemctl restart ollama || true
fi

# Profile env for shells
cp "$STACK/scripts/wsl-rocm-env.sh" /etc/profile.d/aether-rocm.sh 2>/dev/null || true
chmod 644 /etc/profile.d/aether-rocm.sh 2>/dev/null || true

sleep 2
echo
echo "Post-check:"
python3 "$ROOT/probe.py" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('compute_ready=', d.get('compute_ready')); print('CUs=', d.get('total_compute_units')); print('rocm_runners=', d.get('ollama',{}).get('rocm_runners')); print('actions=', d.get('actions'))" || true

echo
echo "Manual verify: ollama run tinyllama 'hi' && ollama ps"
echo "(Windows Task Manager → GPU → Compute should move if CUs are active)"
