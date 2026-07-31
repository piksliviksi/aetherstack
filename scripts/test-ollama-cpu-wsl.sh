#!/usr/bin/env bash
set -euo pipefail
DROPIN=/etc/systemd/system/ollama.service.d/aether-cpu-fallback.conf

restore_gpu_service() {
  sudo rm -f "$DROPIN"
  sudo systemctl daemon-reload
  sudo systemctl restart ollama
}

# A CPU-only test must not leave the GPU hidden after it exits.
trap restore_gpu_service EXIT
sudo pkill -f llama-server 2>/dev/null || true
sudo tee /etc/systemd/system/ollama.service.d/aether-cpu-fallback.conf >/dev/null <<'EOF'
[Service]
# Temporary CPU path when ROCm model-fit hangs on first load
Environment=HIP_VISIBLE_DEVICES=
Environment=ROCR_VISIBLE_DEVICES=
Environment=OLLAMA_VULKAN=false
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
sleep 4
echo "version=$(curl -sS --max-time 3 http://127.0.0.1:11434/api/version)"
curl -sS --max-time 180 http://127.0.0.1:11434/api/generate \
  -d '{"model":"tinyllama","prompt":"Say hi","stream":false,"options":{"num_predict":12}}' \
  -o /tmp/cpu-gen.json
python3 - <<'PY'
import json
d=json.load(open("/tmp/cpu-gen.json"))
print("CPU_OK", (d.get("response") or "")[:120])
print("eval_count", d.get("eval_count"))
print("eval_duration_ns", d.get("eval_duration"))
print("load_duration_ns", d.get("load_duration"))
PY
ollama ps
