#!/usr/bin/env bash
# List LiteLLM models with master key (browser alone cannot pass Authorization)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY=""
if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a; source "$ROOT/.env"; set +a
  KEY="${LITELLM_MASTER_KEY:-}"
fi
if [[ -z "$KEY" ]]; then
  echo "LITELLM_MASTER_KEY is missing. Run start.sh once." >&2
  exit 1
fi
curl -sS "http://127.0.0.1:4000/v1/models" \
  -H "Authorization: Bearer ${KEY}" | python3 -c "import sys,json; d=json.load(sys.stdin); print('\n'.join(m['id'] for m in d.get('data',[])))" 2>/dev/null \
  || curl -sS "http://127.0.0.1:4000/v1/models" -H "Authorization: Bearer ${KEY}"
