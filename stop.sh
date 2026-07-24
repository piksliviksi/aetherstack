#!/usr/bin/env bash
# AetherStack — stop all compose services
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if docker compose version >/dev/null 2>&1; then
  docker compose down
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose down
else
  echo "docker compose not found" >&2
  exit 1
fi
echo "AetherStack stopped."
