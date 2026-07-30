#!/usr/bin/env bash
# AetherStack — stop all compose services
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if docker compose version >/dev/null 2>&1; then
  docker compose --profile '*' down
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose --profile '*' down
else
  echo "docker compose not found" >&2
  exit 1
fi


pid_file="$ROOT/.aetherstack/managed-ollama.pid"
command_file="$ROOT/.aetherstack/managed-ollama.command"
if [[ "$(uname -s 2>/dev/null || true)" == "Darwin" && -f "$pid_file" && -f "$command_file" ]]; then
  pid="$(tr -dc '0-9' < "$pid_file")"
  expected="$(cat "$command_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    actual="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if [[ "$actual" == *"$expected"* && "$actual" == *"serve"* ]]; then
      echo "Stopping AetherStack-managed host Ollama..."
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    else
      echo "Managed Ollama PID $pid no longer matches its recorded command; leaving it untouched." >&2
    fi
  fi
  rm -f "$pid_file" "$command_file"
fi
echo "AetherStack stopped."
