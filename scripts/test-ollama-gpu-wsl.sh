#!/usr/bin/env bash
# Long-timeout first load test for ROCm Ollama in WSL
set -euo pipefail
export HSA_ENABLE_DXG_DETECTION=1
export HSA_OVERRIDE_GFX_VERSION=10.3.0
export LD_LIBRARY_PATH="/opt/rocm/lib:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export HIP_VISIBLE_DEVICES=0
export ROCR_VISIBLE_DEVICES=0
export OLLAMA_VULKAN=false

sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/aether-load-timeout.conf >/dev/null <<'EOF'
[Service]
Environment=OLLAMA_LOAD_TIMEOUT=15m0s
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
sleep 4

echo "version: $(curl -sS --max-time 3 http://127.0.0.1:11434/api/version)"
echo "rocm dirs: $(ls -d /usr/local/lib/ollama/rocm* 2>/dev/null || true)"

rm -f /tmp/gen-out.json /tmp/gen-curl.log
curl -sS --max-time 600 http://127.0.0.1:11434/api/generate \
  -d '{"model":"tinyllama","prompt":"hi","stream":false,"options":{"num_predict":8}}' \
  -o /tmp/gen-out.json > /tmp/gen-curl.log 2>&1 &
CPID=$!
echo "curl pid=$CPID"

for i in $(seq 1 40); do
  sleep 15
  if [[ -s /tmp/gen-out.json ]]; then
    echo "response after ${i}*15s"
    python3 - <<'PY'
import json
d=json.load(open("/tmp/gen-out.json"))
print("resp", (d.get("response") or "")[:120])
print("eval_count", d.get("eval_count"))
print("eval_duration", d.get("eval_duration"))
print("load_duration", d.get("load_duration"))
PY
    ollama ps || true
    sudo journalctl -u ollama -n 12 --no-pager | tail -12
    exit 0
  fi
  if ! kill -0 "$CPID" 2>/dev/null; then
    echo "curl exited early"
    cat /tmp/gen-curl.log || true
    break
  fi
  last=$(sudo journalctl -u ollama -n 1 --no-pager --output=cat 2>/dev/null | tail -1 | cut -c1-140)
  echo "wait $i: $last"
done

echo "TIMEOUT or failed"
cat /tmp/gen-curl.log || true
sudo journalctl -u ollama -n 30 --no-pager | tail -30
exit 1
