#!/usr/bin/env bash
# Force-install Ollama's AMD ROCm compute backend in WSL.
#
# Why: stock install.sh only pulls ollama-linux-amd64-rocm when lspci sees AMD.
# On WSL + ROCDXG, the GPU is Agent 2 via rocminfo / /dev/dxg — not a PCI amdgpu
# device — so the ROCm libs are skipped and inference stays on CPU.
#
# Usage (inside Debian WSL):
#   cd /path/to/aetherstack && sudo bash ./scripts/install-ollama-rocm-wsl.sh
# From Windows:
#   .\scripts\auto-install.ps1 -Enable -Yes -IncludeElevated
set -euo pipefail

export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
ARCH="amd64"
BASE="https://ollama.com/download"
NAME="ollama-linux-${ARCH}-rocm"
DEST="/usr/local"
LIBDIR="${DEST}/lib/ollama"

echo "==> AetherStack: install Ollama ROCm package (AMD compute engines)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if [[ ! -e /dev/dxg ]]; then
  echo "WARNING: /dev/dxg missing — ROCDXG may not be available." >&2
fi

if command -v rocminfo >/dev/null 2>&1; then
  export HSA_ENABLE_DXG_DETECTION=1
  export LD_LIBRARY_PATH="/opt/rocm/lib:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  echo "==> rocminfo GPU agents:"
  rocminfo 2>/dev/null | grep -E "Marketing Name:|Device Type:|Compute Unit:|Name:.*gfx" | head -20 || true
fi

if ! command -v zstd >/dev/null 2>&1; then
  echo "==> Installing zstd..."
  apt-get update -qq && apt-get install -y -qq zstd
fi

# Base ollama binary if missing
if [[ ! -x /usr/local/bin/ollama ]]; then
  echo "==> Base Ollama missing — installing stock package first..."
  curl -fsSL https://ollama.com/install.sh | sh
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Downloading ${NAME}.tar.zst (large; AMD HIP/ROCm runner libs)..."
if curl --fail --silent --head --location "${BASE}/${NAME}.tar.zst" >/dev/null 2>&1; then
  curl --fail --show-error --location --progress-bar \
    "${BASE}/${NAME}.tar.zst" -o "${TMP}/${NAME}.tar.zst"
  echo "==> Extracting into ${DEST}..."
  zstd -d -c "${TMP}/${NAME}.tar.zst" | tar -xf - -C "${DEST}"
else
  echo "==> .tar.zst not found, trying .tgz..."
  curl --fail --show-error --location --progress-bar \
    "${BASE}/${NAME}.tgz" -o "${TMP}/${NAME}.tgz"
  tar -xzf "${TMP}/${NAME}.tgz" -C "${DEST}"
fi

# Normalize layout: archives may use lib/ollama/rocm or lib/ollama/rocm_v7_2
echo "==> Library tree:"
ls -la "${LIBDIR}" 2>/dev/null | head -25 || true
if [[ -d "${LIBDIR}/rocm" ]]; then
  echo "OK: ${LIBDIR}/rocm present"
  ls "${LIBDIR}/rocm" | head -15
elif compgen -G "${LIBDIR}/rocm_*" >/dev/null 2>&1; then
  echo "OK: versioned ROCm runners present:"
  ls -d "${LIBDIR}"/rocm_* 2>/dev/null
  ls "${LIBDIR}"/rocm_* 2>/dev/null | head -5
  # Convenience symlink for scripts that check .../rocm
  if [[ ! -e "${LIBDIR}/rocm" ]]; then
    first="$(ls -d "${LIBDIR}"/rocm_* 2>/dev/null | head -1)"
    if [[ -n "$first" ]]; then
      ln -sfn "$(basename "$first")" "${LIBDIR}/rocm"
      echo "Symlink ${LIBDIR}/rocm -> $(basename "$first")"
    fi
  fi
else
  # Search for hip/rocm ggml
  echo "Looking for ROCm ggml libs..."
  find "${DEST}" -iname '*rocm*' -o -iname '*hip*' 2>/dev/null | head -30 || true
fi

# Wire systemd for AMD compute (CUs via HSA/DXG)
mkdir -p /etc/systemd/system/ollama.service.d
cat >/etc/systemd/system/ollama.service.d/aether-amd-compute.conf <<'EOF'
[Service]
# Reach Docker / Windows host
Environment=OLLAMA_HOST=0.0.0.0:11434
Environment=OLLAMA_ORIGINS=*
# AMD compute via ROCm + ROCDXG (DXCore) in WSL
Environment=HSA_ENABLE_DXG_DETECTION=1
# RDNA2 consumer (RX 6600 XT gfx1032 → report as gfx1030 for HIP)
Environment=HSA_OVERRIDE_GFX_VERSION=10.3.0
Environment=LD_LIBRARY_PATH=/opt/rocm/lib:/usr/lib/wsl/lib
Environment=PATH=/opt/rocm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/wsl/lib
# Prefer HIP/ROCm over broken CUDA/Vulkan probes
Environment=OLLAMA_VULKAN=false
Environment=HIP_VISIBLE_DEVICES=0
Environment=ROCR_VISIBLE_DEVICES=0
# llama.cpp automatic memory fitting hangs on ROCm/DXG before model load.
Environment=LLAMA_ARG_FIT=off
# Optional: force library path for ollama runners
# Environment=OLLAMA_LLM_LIBRARY=rocm
EOF

# dids for RX 6600 XT (Navi 23)
mkdir -p /opt/rocm/share/rocdxg
if [[ -d /opt/rocm/share/rocdxg ]]; then
  if ! grep -q '0x73FF' /opt/rocm/share/rocdxg/dids.conf 2>/dev/null; then
    echo '0x73FF,10,3,2' >> /opt/rocm/share/rocdxg/dids.conf
  fi
fi

# Profile for interactive shells
cat >/etc/profile.d/aether-rocm.sh <<'EOF'
# AetherStack / ROCm on WSL — AMD compute engines
export HSA_ENABLE_DXG_DETECTION=1
export HSA_OVERRIDE_GFX_VERSION=10.3.0
export LD_LIBRARY_PATH="/opt/rocm/lib:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="/opt/rocm/bin${PATH:+:$PATH}"
export HIP_VISIBLE_DEVICES=0
export ROCR_VISIBLE_DEVICES=0
EOF
chmod 644 /etc/profile.d/aether-rocm.sh

id ollama &>/dev/null && usermod -aG video,render ollama 2>/dev/null || true

systemctl daemon-reload
systemctl enable ollama 2>/dev/null || true
systemctl restart ollama
sleep 3

echo "==> Ollama service:"
systemctl is-active ollama || true
curl -sS http://127.0.0.1:11434/ || true
echo

echo "==> GPU discovery log (expect library=rocm or hip, not only cpu):"
journalctl -u ollama -n 40 --no-pager 2>/dev/null | grep -iE "gpu|rocm|hip|vram|library|inference compute|discover" || true

echo ""
echo "Done. Test compute:"
echo "  ollama run tinyllama 'hi'"
echo "  ollama ps   # PROCESSOR should show GPU, not 100% CPU"
echo "  Windows Task Manager → GPU → Compute_0/1 activity"
