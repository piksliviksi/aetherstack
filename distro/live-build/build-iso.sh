#!/usr/bin/env bash
# Scaffold: prepare / document Debian live-build for AetherStack editions.
# Does not yet produce a production ISO (E0).
set -euo pipefail

EDITION="desktop"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DISTRO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--edition desktop|team-server]

Scaffold check for AetherStack Debian ISO build.
Repo root: $ROOT
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --edition) EDITION="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

case "$EDITION" in
  desktop|team-server) ;;
  cloud-control-plane)
    echo "cloud-control-plane is not an ISO flavor; use deploy manifests." >&2
    exit 2
    ;;
  *) echo "Unsupported edition: $EDITION" >&2; exit 2 ;;
esac

echo "==> AetherStack distro ISO scaffold (edition=$EDITION)"
echo "    distro version: $(cat "$DISTRO_ROOT/VERSION")"
echo "    product VERSION: $(cat "$ROOT/VERSION" 2>/dev/null || echo unknown)"

missing=0
for cmd in lb debootstrap; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "    missing tool: $cmd (install live-build / debootstrap on a Debian builder)"
    missing=1
  fi
done

EDITION_FILE="$DISTRO_ROOT/editions/${EDITION}.yaml"
if [[ "$EDITION" == "team-server" ]]; then
  EDITION_FILE="$DISTRO_ROOT/editions/team-server.yaml"
fi
if [[ ! -f "$EDITION_FILE" ]]; then
  # desktop.yaml uses edition key desktop
  if [[ "$EDITION" == "desktop" ]]; then
    EDITION_FILE="$DISTRO_ROOT/editions/desktop.yaml"
  fi
fi
[[ -f "$EDITION_FILE" ]] || { echo "Missing edition file"; exit 1; }
echo "    edition file: $EDITION_FILE"

echo ""
echo "Intended next steps on a Debian builder:"
echo "  mkdir -p ~/aether-os && cd ~/aether-os"
echo "  lb config --distribution bookworm --architectures amd64 --binary-images iso-hybrid ..."
echo "  # merge package lists from distro/live-build/config/package-lists/"
echo "  # rsync $ROOT → config/includes.chroot/opt/aetherstack (exclude .git .env)"
echo "  # install systemd units from distro/systemd/"
echo "  # render env from edition via distro/scripts/render-edition-env.sh $EDITION"
echo "  sudo lb build"
echo ""
if [[ "$missing" -ne 0 ]]; then
  echo "Scaffold OK; live-build tools not installed on this host (expected on macOS)."
  exit 0
fi
echo "live-build tools present. Wire lb config paths then run lb build."
exit 0
