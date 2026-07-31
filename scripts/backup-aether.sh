#!/usr/bin/env bash
# AetherStack backup — project or global; local / AWS / Azure via hub.
set -euo pipefail
HUB="${AETHER_HUB:-http://127.0.0.1:8766}"
SCOPE="${1:-global}"
DEST="${2:-local}"

curl -sS -X POST "$HUB/api/backup" \
  -H "Content-Type: application/json" \
  -d "{\"scope\":\"$SCOPE\",\"destinations\":[\"$DEST\"],\"project_path\":\"${PROJECT_PATH:-}\",\"include_private\":${INCLUDE_PRIVATE:-false}}" \
  | python3 -m json.tool 2>/dev/null || cat
