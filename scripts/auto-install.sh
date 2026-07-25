#!/usr/bin/env bash
# AetherStack optional auto-install (Linux/macOS). Default dry-run; pass --yes to apply.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
HUB_URL="${HUB_URL:-http://127.0.0.1:8766}"
YES=0
ENABLE=0
for a in "$@"; do
  case "$a" in
    --yes|-y) YES=1 ;;
    --enable) ENABLE=1 ;;
    --disable) curl -sf -X POST "$HUB_URL/api/bootstrap" -H 'Content-Type: application/json' -d '{"enabled":false}' || true; exit 0 ;;
  esac
done

echo "AetherStack auto-install (optional)"
if [[ -f scripts/scan-system.sh ]]; then bash scripts/scan-system.sh || true; fi

if [[ "$ENABLE" -eq 1 ]]; then
  curl -sf -X POST "$HUB_URL/api/bootstrap" -H 'Content-Type: application/json' -d '{"enabled":true}' || true
  echo "Hub auto-install enabled"
fi

echo "Plan:"
curl -sf "$HUB_URL/api/bootstrap?refresh=1" | python3 -m json.tool 2>/dev/null | head -80 || echo "(hub offline)"

if [[ "$YES" -eq 0 ]]; then
  echo "Dry-run only. Re-run: ./scripts/auto-install.sh --enable --yes"
  curl -sf -X POST "$HUB_URL/api/bootstrap/run" -H 'Content-Type: application/json' \
    -d '{"confirm":true,"dry_run":true,"only_safe":true}' >/dev/null 2>&1 || true
  exit 0
fi

python3 -m pip install --user -q redis PyYAML psutil 2>/dev/null || true
if command -v docker >/dev/null; then
  docker compose up -d redis litellm aether-hub open-webui
fi
if curl -sf --max-time 2 http://127.0.0.1:11434/ >/dev/null; then
  for m in tinyllama nomic-embed-text; do
    if ! curl -sf http://127.0.0.1:11434/api/tags | grep -q "$m"; then
      echo "ollama pull $m"
      ollama pull "$m" || curl -sf -X POST http://127.0.0.1:11434/api/pull \
        -H 'Content-Type: application/json' -d "{\"name\":\"$m\",\"stream\":false}" || true
    fi
  done
fi

curl -sf -X POST "$HUB_URL/api/bootstrap" -H 'Content-Type: application/json' -d '{"enabled":true}' || true
curl -sf -X POST "$HUB_URL/api/bootstrap/run" -H 'Content-Type: application/json' \
  -d '{"confirm":true,"dry_run":false,"only_safe":true}' | python3 -m json.tool 2>/dev/null | head -40 || true
echo "Done."
