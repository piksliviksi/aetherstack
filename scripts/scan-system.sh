#!/usr/bin/env bash
# AetherStack host system scan (Linux/macOS). Writes .aetherstack/system-scan.json
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p .aetherstack
HUB_URL="${HUB_URL:-http://127.0.0.1:8766}"
docker_ollama_url="${OLLAMA_BASE_URL:-$(sed -n 's/^[[:space:]]*OLLAMA_BASE_URL[[:space:]]*=[[:space:]]*//p' .env 2>/dev/null | tail -1 | tr -d '\r' | sed "s/^[\"']//;s/[\"']$//")}"
docker_ollama_url="${docker_ollama_url:-http://host.docker.internal:11434}"
host_ollama_url="${docker_ollama_url//host.docker.internal/127.0.0.1}"
host_ollama_url="${host_ollama_url//gateway.docker.internal/127.0.0.1}"
host_ollama_url="${host_ollama_url%/}"

json_escape() { python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo '""'; }

ollama_models="[]"
tags_file="$(mktemp "${TMPDIR:-/tmp}/aether-ollama-tags.XXXXXX")"
trap 'rm -f "$tags_file"' EXIT
if curl -sf --max-time 2 "$host_ollama_url/api/tags" >"$tags_file" 2>/dev/null; then
  ollama_models=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps([m.get('name') for m in d.get('models',[])]))" "$tags_file" 2>/dev/null || echo '[]')
  ollama_ok=true
else
  ollama_ok=false
fi

docker_ok=false
containers="[]"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker_ok=true
  containers=$(docker ps --format '{{.Names}}' 2>/dev/null | python3 -c 'import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))' 2>/dev/null || echo '[]')
fi

hub_ok=false
curl -sf --max-time 2 "$HUB_URL/api/health" >/dev/null 2>&1 && hub_ok=true

export AETHER_SCAN_DOCKER_OK="$docker_ok"
export AETHER_SCAN_CONTAINERS="$containers"
export AETHER_SCAN_OLLAMA_OK="$ollama_ok"
export AETHER_SCAN_OLLAMA_BASE_URL="$host_ollama_url"
export AETHER_SCAN_OLLAMA_MODELS="$ollama_models"
export AETHER_SCAN_HUB_OK="$hub_ok"
export AETHER_SCAN_HUB_URL="$HUB_URL"

python3 - <<'PY'
import json, time, os, platform, socket
def env_bool(name):
    return os.environ.get(name, "false").lower() == "true"

def env_json(name, fallback):
    try:
        return json.loads(os.environ.get(name, fallback))
    except Exception:
        return json.loads(fallback)

report = {
  "ts": time.time(),
  "host": socket.gethostname(),
  "os": platform.platform(),
  "ram_gb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3), 1),
  "docker": {"ok": env_bool("AETHER_SCAN_DOCKER_OK"), "containers": env_json("AETHER_SCAN_CONTAINERS", "[]")},
  "containers": env_json("AETHER_SCAN_CONTAINERS", "[]"),
  "ollama": {
      "localhost_ok": env_bool("AETHER_SCAN_OLLAMA_OK"),
      "base_url": os.environ.get("AETHER_SCAN_OLLAMA_BASE_URL", ""),
      "models": env_json("AETHER_SCAN_OLLAMA_MODELS", "[]"),
  },
  "hub": {"ok": env_bool("AETHER_SCAN_HUB_OK"), "url": os.environ.get("AETHER_SCAN_HUB_URL", "http://127.0.0.1:8766")},
}
path = ".aetherstack/system-scan.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)
print("Wrote", path)
print(json.dumps(report, indent=2)[:2000])
# push to hub
if env_bool("AETHER_SCAN_HUB_OK"):
    import urllib.request
    body = json.dumps({"host_scan": report}).encode()
    req = urllib.request.Request(os.environ.get("AETHER_SCAN_HUB_URL", "http://127.0.0.1:8766") + "/api/discover", data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        print("Posted host_scan to hub")
    except Exception as e:
        print("hub post failed", e)
PY
