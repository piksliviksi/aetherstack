#!/usr/bin/env bash
# Validate that team/enterprise compose overlays merge with the base file.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not installed; skip compose validation"
  exit 0
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin missing; skip"
  exit 0
fi

# Provide dummy env so required interpolations succeed
export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-distro-validate-only}"
export AETHER_BIND_HOST="${AETHER_BIND_HOST:-127.0.0.1}"

echo "==> compose config: base"
docker compose -f docker-compose.yml config --quiet

echo "==> compose config: base + team"
docker compose -f docker-compose.yml -f docker-compose.team.yml config --quiet

echo "==> compose config: base + team + enterprise"
docker compose -f docker-compose.yml -f docker-compose.team.yml -f docker-compose.enterprise.yml config --quiet

echo "OK: compose overlays validate"
