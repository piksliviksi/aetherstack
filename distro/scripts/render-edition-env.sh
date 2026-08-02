#!/usr/bin/env bash
# Render key AETHER_* variables from distro/editions/*.yaml to stdout.
# E0: minimal parser without requiring PyYAML (grep/sed friendly YAML).
set -euo pipefail

EDITION="${1:-desktop}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
case "$EDITION" in
  desktop) FILE="$ROOT/distro/editions/desktop.yaml" ;;
  team-server|team) FILE="$ROOT/distro/editions/team-server.yaml" ;;
  cloud|cloud-control-plane) FILE="$ROOT/distro/editions/cloud-control-plane.yaml" ;;
  *) echo "Usage: $0 desktop|team-server|cloud" >&2; exit 2 ;;
esac

[[ -f "$FILE" ]] || { echo "Missing $FILE" >&2; exit 1; }

pick() {
  # first matching key: value (simple YAML lines)
  local key="$1"
  grep -E "^${key}:" "$FILE" | head -1 | sed -E "s/^${key}:[[:space:]]*//;s/[\"']//g;s/[[:space:]]+#.*//;s/[[:space:]]+$//"
}

AE="$(pick aether_edition)"
RA="$(pick require_auth)"
TM="$(pick tenant_mode)"
BH="$(pick bind_host)"

# normalize booleans
case "${RA}" in
  true|True|yes|1) RA=1 ;;
  false|False|no|0) RA=0 ;;
esac

cat <<EOF
# Generated from distro/editions (${EDITION}) — merge into /etc/aetherstack/env
# Do not commit real secrets.
AETHER_EDITION=${AE}
AETHER_REQUIRE_AUTH=${RA}
AETHER_TENANT_MODE=${TM}
AETHER_BIND_HOST=${BH}
EOF
