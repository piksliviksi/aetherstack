#!/usr/bin/env bash
# Pull and save Compose images for offline ISO inclusion (E0 stub helpers).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$ROOT/distro/sbom/aether-images.tar}"
cd "$ROOT"

export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-distro-bake-only}"

echo "Pulling images via compose..."
docker compose -f docker-compose.yml pull || true
# build local services
docker compose -f docker-compose.yml build || true

echo "Saving to $OUT (may be large)..."
mkdir -p "$(dirname "$OUT")"
# shellcheck disable=SC2046
images=$(docker compose -f docker-compose.yml config --images 2>/dev/null | sort -u || true)
if [[ -z "${images}" ]]; then
  echo "No images listed; abort save"
  exit 1
fi
# docker save needs image ids that exist locally
# shellcheck disable=SC2086
docker save -o "$OUT" $images
echo "Wrote $OUT"
ls -lh "$OUT"
