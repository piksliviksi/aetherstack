#!/usr/bin/env bash
# AetherStack optional auto-install (Linux/macOS). Default dry-run; pass --yes to apply.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
HUB_URL="${HUB_URL:-http://127.0.0.1:8766}"
docker_ollama_url="${OLLAMA_BASE_URL:-$(sed -n 's/^[[:space:]]*OLLAMA_BASE_URL[[:space:]]*=[[:space:]]*//p' .env 2>/dev/null | tail -1 | tr -d '\r' | sed "s/^[\"']//;s/[\"']$//")}"
docker_ollama_url="${docker_ollama_url:-http://host.docker.internal:11434}"
host_ollama_url="${docker_ollama_url//host.docker.internal/127.0.0.1}"
host_ollama_url="${host_ollama_url//gateway.docker.internal/127.0.0.1}"
host_ollama_url="${host_ollama_url%/}"
if [[ -n "${AETHER_OLLAMA_MODELS:-}" ]]; then
  OLLAMA_MODELS="$AETHER_OLLAMA_MODELS"
else
  ram_gb="$(python3 -c 'import os; print(int(os.sysconf("SC_PAGE_SIZE")*os.sysconf("SC_PHYS_PAGES")/(1024**3)))' 2>/dev/null || echo 0)"
  if (( ram_gb >= 10 )); then OLLAMA_MODELS="llama3.1:8b,nomic-embed-text"; else OLLAMA_MODELS="tinyllama,nomic-embed-text"; fi
fi
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
if curl -sf --max-time 2 "$host_ollama_url/api/tags" >/dev/null; then
  IFS=',' read -r -a wanted_models <<< "$OLLAMA_MODELS"
  for m in "${wanted_models[@]}"; do
    m="${m#"${m%%[![:space:]]*}"}"; m="${m%"${m##*[![:space:]]}"}"
    [[ -z "$m" ]] && continue
    if ! curl -sf "$host_ollama_url/api/tags" | grep -q "\"name\":\"$m\|\"name\":\"${m%%:*}:"; then
      echo "ollama pull $m"
      OLLAMA_HOST="$host_ollama_url" ollama pull "$m" || curl -sf -X POST "$host_ollama_url/api/pull" \
        -H 'Content-Type: application/json' -d "{\"name\":\"$m\",\"stream\":false}" || true
    fi
  done
else
  echo "Ollama is not reachable at $host_ollama_url; start host Ollama before pulling models."
fi

curl -sf -X POST "$HUB_URL/api/bootstrap" -H 'Content-Type: application/json' -d '{"enabled":true}' || true
curl -sf -X POST "$HUB_URL/api/bootstrap/run" -H 'Content-Type: application/json' \
  -d '{"confirm":true,"dry_run":false,"only_safe":true}' | python3 -m json.tool 2>/dev/null | head -40 || true
echo "Done."
