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

bridge_session_file="$ROOT/.aetherstack/cli-bridge.screen"
bridge_pid_file="$ROOT/.aetherstack/cli-bridge.pid"
if [[ -f "$bridge_session_file" ]] && command -v screen >/dev/null 2>&1; then
  bridge_session="$(cat "$bridge_session_file" 2>/dev/null || true)"
  [[ -n "$bridge_session" ]] && screen -S "$bridge_session" -X quit >/dev/null 2>&1 || true
fi
if [[ -f "$bridge_pid_file" ]]; then
  bridge_pid="$(tr -dc '0-9' < "$bridge_pid_file")"
  if [[ "$bridge_pid" =~ ^[0-9]+$ ]] && kill -0 "$bridge_pid" 2>/dev/null; then
    kill "$bridge_pid" 2>/dev/null || true
  fi
fi
rm -f "$bridge_session_file" "$bridge_pid_file"


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
