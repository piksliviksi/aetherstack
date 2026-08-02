#!/usr/bin/env bash
# Boot-smoke placeholder for future ISO/qcow2 artifacts.
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") [--image PATH] [--skip-boot]

When --image is omitted, runs host-side HTTP checks against a running stack
(127.0.0.1). Full QEMU boot will be wired when distro artifacts exist.
EOF
}

IMAGE=""
SKIP_BOOT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --image) IMAGE="${2:?}"; shift 2 ;;
    --skip-boot) SKIP_BOOT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1" >&2; exit 2 ;;
  esac
done

check_url() {
  local url="$1"
  if curl -sf --max-time 3 "$url" >/dev/null; then
    echo "OK  $url"
  else
    echo "FAIL $url"
    return 1
  fi
}

if [[ -n "$IMAGE" && "$SKIP_BOOT" -eq 0 ]]; then
  if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
    echo "qemu-system-x86_64 not installed; cannot boot $IMAGE" >&2
    exit 1
  fi
  echo "QEMU boot automation not implemented yet (E0). Image: $IMAGE"
  exit 0
fi

echo "==> Host stack smoke (expects AetherStack already up)"
fail=0
check_url "http://127.0.0.1:8766/api/health" || fail=1
check_url "http://127.0.0.1:4000/health/liveliness" || fail=1
exit "$fail"
