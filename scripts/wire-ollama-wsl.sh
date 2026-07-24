#!/bin/bash
# Wire Ollama systemd service for AMD ROCm/DXG on WSL + listen for Docker
set -euo pipefail
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"

sudo tee /etc/systemd/system/ollama.service >/dev/null <<'EOF'
[Unit]
Description=Ollama Service (AetherStack / ROCm WSL)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3

# Listen on all interfaces so Windows Docker / host can reach via localhost forwarding
Environment=OLLAMA_HOST=0.0.0.0:11434
Environment=OLLAMA_ORIGINS=*

# AMD ROCm via ROCDXG (DXCore) in WSL
Environment=HSA_ENABLE_DXG_DETECTION=1
Environment=LD_LIBRARY_PATH=/opt/rocm/lib:/usr/lib/wsl/lib
Environment=PATH=/opt/rocm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/wsl/lib

# Optional RDNA2 override for some ROCm apps (uncomment if needed):
# Environment=HSA_OVERRIDE_GFX_VERSION=10.3.0

[Install]
WantedBy=default.target
EOF

# Ensure ollama user can read ROCm libs and /dev/dxg
sudo usermod -aG video,render ollama 2>/dev/null || true
# dxg is world RW typically (crw-rw-rw-); no extra group needed

# Persist dids for RX 6600 XT
sudo mkdir -p /opt/rocm/share/rocdxg
echo '0x73FF,10,3,2' | sudo tee /opt/rocm/share/rocdxg/dids.conf >/dev/null

# Profile env for interactive shells
sudo cp /mnt/d/llm/stack/scripts/wsl-rocm-env.sh /etc/profile.d/aether-rocm.sh
sudo chmod 644 /etc/profile.d/aether-rocm.sh

sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl restart ollama
sleep 2
systemctl is-active ollama
curl -sS http://127.0.0.1:11434/ || true
echo
# Show whether GPU agent is still visible under same env
export HSA_ENABLE_DXG_DETECTION=1
export LD_LIBRARY_PATH=/opt/rocm/lib:/usr/lib/wsl/lib
/opt/rocm/bin/rocminfo 2>&1 | grep -E "Marketing Name:|Device Type:|gfx1032|Warning:" || true
echo "wire-ollama done"
