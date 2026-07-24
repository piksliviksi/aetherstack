#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PROJECT="${1:-}"
PORT="${PORT:-8765}"

if ! python3 -c "import psutil" 2>/dev/null; then
  echo "Installing psutil (recommended)..."
  python3 -m pip install --user -q psutil || true
fi

ARGS=(server.py --port "$PORT" --no-browser)
if [[ -n "$PROJECT" ]]; then
  ARGS+=(--project "$PROJECT")
fi
if [[ -n "${AETHERSTACK_ENGINE_TOKEN:-}" ]]; then
  ARGS+=(--token "$AETHERSTACK_ENGINE_TOKEN")
  echo "Auth token: enabled (X-Aether-Token)"
fi
echo "Starting Project Engine on http://127.0.0.1:$PORT"
exec python3 "${ARGS[@]}"
