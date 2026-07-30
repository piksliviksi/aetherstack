#!/usr/bin/env bash
# AetherStack — macOS / Ubuntu / native Linux start script
# Usage: ./start.sh   (or double-click if your file manager allows executing .sh)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

cyan()  { printf '\033[36m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }

OS_NAME="$(uname -s 2>/dev/null || echo unknown)"
case "$OS_NAME" in
  Darwin) OS_HINT="macOS" ;;
  Linux)  OS_HINT="Linux" ;;
  *)      OS_HINT="$OS_NAME" ;;
esac

cyan ""
cyan "  AetherStack  ($OS_HINT)"
cyan "  Multi-model LLM control plane"
cyan ""

if [[ ! -f .env ]]; then
  cp .env.example .env
  yellow "  Created .env from .env.example — add API keys when ready."
fi

docker_ollama_url="${OLLAMA_BASE_URL:-$(sed -n 's/^[[:space:]]*OLLAMA_BASE_URL[[:space:]]*=[[:space:]]*//p' .env | tail -1 | tr -d '\r' | sed "s/^[\"']//;s/[\"']$//")}"
docker_ollama_url="${docker_ollama_url:-http://host.docker.internal:11434}"
host_ollama_url="${docker_ollama_url//host.docker.internal/127.0.0.1}"
host_ollama_url="${host_ollama_url//gateway.docker.internal/127.0.0.1}"
host_ollama_url="${host_ollama_url%/}"

# Scan host before bring-up (Ollama / Docker / ports)
if [[ -x "$ROOT/scripts/scan-system.sh" ]] || [[ -f "$ROOT/scripts/scan-system.sh" ]]; then
  cyan "  Scanning system…"
  bash "$ROOT/scripts/scan-system.sh" || yellow "  Scan script warning (continuing)."
fi

if ! command -v docker >/dev/null 2>&1; then
  red "  ERROR: Docker not found."
  if [[ "$OS_NAME" == "Darwin" ]]; then
    yellow "  macOS: install Docker Desktop — docs/TUTORIAL-MACOS.md"
    yellow "  https://docs.docker.com/desktop/setup/install/mac-install/"
  else
    yellow "  Ubuntu/Linux: see docs/TUTORIAL-UBUNTU.md"
  fi
  exit 1
fi

# Prefer docker compose plugin; fall back to docker-compose
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  red "  ERROR: docker compose plugin not found."
  exit 1
fi

# Ensure docker daemon is running
if ! docker info >/dev/null 2>&1; then
  yellow "  Docker daemon not running — trying to start..."
  if [[ "$OS_NAME" == "Darwin" ]]; then
    # Docker Desktop on macOS
    open -a Docker 2>/dev/null || true
    yellow "  Waiting for Docker Desktop..."
    for _ in $(seq 1 30); do
      if docker info >/dev/null 2>&1; then break; fi
      sleep 2
    done
  elif command -v systemctl >/dev/null 2>&1; then
    sudo systemctl start docker 2>/dev/null || true
    sleep 2
  fi
  if ! docker info >/dev/null 2>&1; then
    red "  ERROR: cannot reach Docker daemon. Start Docker Desktop / dockerd and retry."
    if [[ "$OS_NAME" == "Darwin" ]]; then
      yellow "  macOS: open Docker Desktop from Applications, wait until it is Running."
    fi
    exit 1
  fi
fi

# host.docker.internal is set in compose (needed on Docker Desktop Mac/Win + some Linux)
cyan "  Starting containers (Open WebUI, LiteLLM, Redis, Postgres, Hub)..."
if ! curl -sf --max-time 2 "$host_ollama_url/api/tags" >/dev/null 2>&1; then
  yellow "  Host Ollama is unavailable; starting the bundled CPU fallback."
  export OLLAMA_BASE_URL="http://ollama:11434"
  host_ollama_url="http://127.0.0.1:11434"
  "${DC[@]}" --profile with-ollama-container up -d --build
else
  "${DC[@]}" up -d --build
fi

ollama_deadline=$((SECONDS + 90))
until curl -sf --max-time 2 "$host_ollama_url/api/tags" >/dev/null 2>&1; do
  if (( SECONDS >= ollama_deadline )); then red "  ERROR: Ollama did not become ready at $host_ollama_url"; exit 1; fi
  sleep 2
done

env_ollama_models="$(sed -n 's/^[[:space:]]*AETHER_OLLAMA_MODELS[[:space:]]*=[[:space:]]*//p' .env | tail -1 | tr -d '\r' | sed "s/^[\"']//;s/[\"']$//")"
wanted_models="${AETHER_OLLAMA_MODELS:-${env_ollama_models:-qwen2.5-coder:1.5b,nomic-embed-text}}"
IFS=',' read -r -a startup_models <<< "$wanted_models"
for model in "${startup_models[@]}"; do
  model="${model//[[:space:]]/}"
  [[ -z "$model" ]] && continue
  if [[ ! "$model" =~ ^[A-Za-z0-9._:/-]+$ ]]; then red "  ERROR: invalid Ollama model name: $model"; exit 1; fi
  cyan "  Ensuring Ollama model: $model"
  curl -fsS --max-time 900 -X POST "$host_ollama_url/api/pull" -H 'Content-Type: application/json' -d "{\"name\":\"$model\",\"stream\":false}" >/dev/null
done
"${DC[@]}" restart aether-hub litellm >/dev/null

deadline=$((SECONDS + 120))
pending=""
while (( SECONDS < deadline )); do
  pending=""
  curl -sf --max-time 3 http://127.0.0.1:3000/ >/dev/null || pending="$pending Open-WebUI"
  curl -sf --max-time 3 http://127.0.0.1:4000/health/liveliness >/dev/null || pending="$pending LiteLLM"
  curl -sf --max-time 3 http://127.0.0.1:8766/api/health >/dev/null || pending="$pending AetherHub"
  [[ -z "$pending" ]] && break
  sleep 2
done
if [[ -n "$pending" ]]; then
  red "  ERROR: services did not become ready:$pending"
  "${DC[@]}" ps
  exit 1
fi
"${DC[@]}" ps

if curl -sf --max-time 2 "$host_ollama_url/api/tags" >/dev/null 2>&1; then
  green "  Ollama: OK on $host_ollama_url"
else
  yellow "  Note: Ollama not reachable at $host_ollama_url."
  yellow "  Install host Ollama (recommended — Metal on Apple Silicon): https://ollama.com"
  yellow "  Or: ${DC[*]} --profile with-ollama-container up -d"
  if [[ "$OS_NAME" == "Linux" ]]; then
    yellow "  AMD Linux: ${DC[*]} -f docker-compose.yml -f docker-compose.amd.yml --profile with-ollama-container up -d"
  fi
fi

echo ""
green "  --------------------------------"
green "  Chat UI:   http://localhost:3000"
green "  LiteLLM:   http://localhost:4000"
green "  Hub/scan:  http://localhost:8766  (discover first)"
green "  Redis:     localhost:6379"
green "  --------------------------------"
cyan "  Scan API:  http://localhost:8766/api/discover"
cyan "  Stop: ./stop.sh"
# Post the pre-start scan without repeating GPU probes.
if [[ -f "$ROOT/.aetherstack/system-scan.json" ]]; then
  scan_payload="$(python3 -c 'import json,sys; print(json.dumps({"host_scan":json.load(open(sys.argv[1]))}))' "$ROOT/.aetherstack/system-scan.json" 2>/dev/null || true)"
  [[ -n "$scan_payload" ]] && curl -sf -X POST http://127.0.0.1:8766/api/discover -H 'Content-Type: application/json' -d "$scan_payload" >/dev/null || true
fi
if [[ "$OS_NAME" == "Darwin" ]]; then
  cyan "  Guide: docs/TUTORIAL-MACOS.md"
fi
echo ""

# Open browser if possible (macOS: open · Linux: xdg-open)
if [[ "${AETHER_NO_BROWSER:-0}" == "1" ]]; then
  :
elif [[ "$OS_NAME" == "Darwin" ]] && command -v open >/dev/null 2>&1; then
  open "http://localhost:3000" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost:3000" >/dev/null 2>&1 || true
elif command -v sensible-browser >/dev/null 2>&1; then
  sensible-browser "http://localhost:3000" >/dev/null 2>&1 || true
fi
