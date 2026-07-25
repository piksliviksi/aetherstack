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
cyan "  Starting containers (Open WebUI, LiteLLM, Redis)..."
"${DC[@]}" up -d

sleep 2
"${DC[@]}" ps

if curl -sf --max-time 2 http://127.0.0.1:11434/ >/dev/null 2>&1; then
  green "  Ollama: OK on http://127.0.0.1:11434"
else
  yellow "  Note: Ollama not on :11434."
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
green "  Hub:       http://localhost:8766  (matrix + memory)"
green "  Redis:     localhost:6379"
green "  --------------------------------"
cyan "  Stop: ./stop.sh"
if [[ "$OS_NAME" == "Darwin" ]]; then
  cyan "  Guide: docs/TUTORIAL-MACOS.md"
fi
echo ""

# Open browser if possible (macOS: open · Linux: xdg-open)
if [[ "$OS_NAME" == "Darwin" ]] && command -v open >/dev/null 2>&1; then
  open "http://localhost:3000" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost:3000" >/dev/null 2>&1 || true
elif command -v sensible-browser >/dev/null 2>&1; then
  sensible-browser "http://localhost:3000" >/dev/null 2>&1 || true
fi
