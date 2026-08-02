#!/usr/bin/env bash
# AetherStack — macOS / Ubuntu / native Linux start script
# Usage: ./start.sh   (or double-click if your file manager allows executing .sh)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

cyan()  { printf '\033[36m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }

# Docker's and Ollama's own progress output is only a single redrawing line when
# attached to an interactive TTY. Piped through a log, a non-interactive shell, or
# the VSCode extension's spawned process, each update prints as its own new line
# instead of overwriting the last one. This filter re-parses the structured
# progress events (Docker's --progress=plain JSON-ish lines and Ollama's NDJSON
# pull stream both carry current/completed + total byte counts) and redraws a
# single line, then appends the final byte count to $2 so the caller can report a
# grand total downloaded at the end of the run.
progress_filter() {
  local label="$1" totals_file="${2:-}"
  if command -v python3 >/dev/null 2>&1; then
    # The Python source lives in its own file (scripts/progress-filter.py) rather
    # than a heredoc here: a heredoc attached to this same `python3` invocation
    # would become that process's stdin, swallowing the live piped progress data
    # this function is supposed to be filtering.
    python3 "$ROOT/scripts/progress-filter.py" "$label" "$totals_file"
  else
    # No python3 available — fall back to passing output through unfiltered
    # rather than silently dropping it.
    cat
  fi
}

OS_NAME="$(uname -s 2>/dev/null || echo unknown)"
case "$OS_NAME" in
  Darwin) OS_HINT="macOS" ;;
  Linux)  OS_HINT="Linux" ;;
  *)      OS_HINT="$OS_NAME" ;;
esac

cyan ""
cyan "  AetherStack  ($OS_HINT)"
cyan "  Multi-model LLM control plane"
cyan ""

# curl is a hard prerequisite for everything below (Docker install, Ollama
# provisioning, health checks) — bootstrap it on Linux if a minimal image
# shipped without it, same auto-install philosophy as Docker.
if ! command -v curl >/dev/null 2>&1 && [[ "$OS_NAME" == "Linux" ]] && [[ "${AETHER_AUTO_INSTALL_DOCKER:-1}" != "0" ]] && command -v sudo >/dev/null 2>&1; then
  yellow "  curl not found; installing..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y -qq curl
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y -q curl
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y -q curl
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm curl
  fi
fi
if ! command -v curl >/dev/null 2>&1; then
  red "  ERROR: curl is required and could not be installed automatically."
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  yellow "  Created .env from .env.example — add API keys when ready."
fi

docker_ollama_url="${OLLAMA_BASE_URL:-$(sed -n 's/^[[:space:]]*OLLAMA_BASE_URL[[:space:]]*=[[:space:]]*//p' .env | tail -1 | tr -d '\r' | sed "s/^[\"']//;s/[\"']$//")}"
docker_ollama_url="${docker_ollama_url:-http://host.docker.internal:11434}"
configured_fallback_port="${AETHER_OLLAMA_PORT:-$(sed -n 's/^[[:space:]]*AETHER_OLLAMA_PORT[[:space:]]*=[[:space:]]*//p' .env | tail -1 | tr -d '\r' | sed "s/^[\"']//;s/[\"']$//")}"
configured_fallback_port="${configured_fallback_port:-11434}"
if [[ "$docker_ollama_url" =~ ^https?://ollama(:11434)?/?$ ]]; then
  docker_ollama_url="http://127.0.0.1:${configured_fallback_port}"
fi
host_ollama_url="${docker_ollama_url//host.docker.internal/127.0.0.1}"
host_ollama_url="${host_ollama_url//gateway.docker.internal/127.0.0.1}"
host_ollama_url="${host_ollama_url%/}"

set_env_value() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp "$ROOT/.env.tmp.XXXXXX")"
  awk -v key="$key" -v value="$value" '
    BEGIN { replaced = 0 }
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      if (!replaced) print key "=" value
      replaced = 1
      next
    }
    { print }
    END { if (!replaced) print key "=" value }
  ' .env > "$tmp"
  mv "$tmp" .env
}

configured_master_key="${LITELLM_MASTER_KEY:-$(sed -n 's/^[[:space:]]*LITELLM_MASTER_KEY[[:space:]]*=[[:space:]]*//p' .env | tail -1 | tr -d '\r' | sed "s/^[\"']//;s/[\"']$//")}"
if [[ -z "$configured_master_key" || "$configured_master_key" == "sk-aether-local" ]]; then
  if command -v openssl >/dev/null 2>&1; then
    configured_master_key="sk-$(openssl rand -hex 32)"
  elif command -v python3 >/dev/null 2>&1; then
    configured_master_key="$(python3 -c 'import secrets; print("sk-" + secrets.token_hex(32))')"
  else
    configured_master_key="sk-$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
  fi
  set_env_value "LITELLM_MASTER_KEY" "$configured_master_key"
  yellow "  Generated a private local gateway key."
fi
export LITELLM_MASTER_KEY="$configured_master_key"

port_is_available() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    ! lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v ss >/dev/null 2>&1; then
    ! ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"
  elif command -v netstat >/dev/null 2>&1; then
    ! netstat -an 2>/dev/null | grep -E "[.:]$port[[:space:]].*LISTEN" >/dev/null
  else
    ! curl -s --connect-timeout 1 "http://127.0.0.1:$port/" >/dev/null 2>&1
  fi
}

select_fallback_port() {
  local candidate
  for candidate in "$configured_fallback_port" 11434 11436 11437 11438 11439 11440 11441 11442 11443 11444; do
    [[ "$candidate" =~ ^[0-9]+$ ]] || continue
    (( candidate >= 1024 && candidate <= 65535 )) || continue
    if port_is_available "$candidate"; then printf '%s\n' "$candidate"; return 0; fi
  done
  return 1
}

select_cli_bridge_port() {
  local configured="${AETHER_CLI_BRIDGE_PORT:-8767}" candidate
  for candidate in "$configured" 8767 8768 8769 8770 8771 8772 8773 8774 8775 8776 8777; do
    [[ "$candidate" =~ ^[0-9]+$ ]] || continue
    (( candidate >= 1024 && candidate <= 65535 )) || continue
    if port_is_available "$candidate"; then printf '%s\n' "$candidate"; return 0; fi
  done
  return 1
}

find_host_ollama() {
  # The configured/default port can be squatted by an unrelated process;
  # probe common alternate ports for a real host Ollama before concluding
  # none is reachable and falling back to the bundled container.
  if curl -sf --max-time 2 "$host_ollama_url/api/tags" >/dev/null 2>&1; then
    printf '%s\n' "$host_ollama_url"
    return 0
  fi
  local port
  for port in 11434 11435 11436 11437 11438 11439 11440; do
    if curl -sf --max-time 2 "http://127.0.0.1:$port/api/tags" >/dev/null 2>&1; then
      printf 'http://127.0.0.1:%s\n' "$port"
      return 0
    fi
  done
  return 1
}

start_macos_host_ollama() {
  [[ "$OS_NAME" == "Darwin" ]] || return 1
  [[ "${AETHER_AUTO_INSTALL_OLLAMA:-1}" != "0" ]] || return 1
  [[ "$host_ollama_url" =~ ^https?://(127\.0\.0\.1|localhost)(:[0-9]+)?$ ]] || return 1

  local cli="" candidate tools_root staging archive bind pid log
  for candidate in \
    "$(command -v ollama 2>/dev/null || true)" \
    "/Applications/Ollama.app/Contents/Resources/ollama" \
    "$HOME/Applications/Ollama.app/Contents/Resources/ollama" \
    "$HOME/Library/Application Support/AetherStack/tools/Ollama.app/Contents/Resources/ollama"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then cli="$candidate"; break; fi
  done

  if [[ -z "$cli" ]]; then
    command -v curl >/dev/null 2>&1 || { yellow "  Host Ollama is absent and curl is unavailable; using the CPU container fallback."; return 1; }
    command -v ditto >/dev/null 2>&1 || { yellow "  Host Ollama is absent and macOS ditto is unavailable; using the CPU container fallback."; return 1; }
    tools_root="${AETHERSTACK_TOOL_DIR:-$HOME/Library/Application Support/AetherStack/tools}"
    mkdir -p "$tools_root"
    if [[ -e "$tools_root/Ollama.app" ]]; then
      red "  ERROR: $tools_root/Ollama.app exists but has no executable CLI."
      red "  Remove or repair that local tool, then press Start again."
      return 1
    fi
    staging="$(mktemp -d "${TMPDIR:-/tmp}/aetherstack-ollama.XXXXXX")"
    archive="$staging/Ollama-darwin.zip"
    cyan "  Host Ollama is absent. Downloading the official macOS app for Metal inference..."
    if ! curl --fail --location --progress-bar --retry 3 \
      https://ollama.com/download/Ollama-darwin.zip -o "$archive"; then
      rm -rf "$staging"
      yellow "  Ollama download failed; using the CPU container fallback."
      return 1
    fi
    ditto -x -k "$archive" "$staging/unpacked"
    candidate="$staging/unpacked/Ollama.app/Contents/Resources/ollama"
    if [[ ! -x "$candidate" ]]; then
      rm -rf "$staging"
      yellow "  Official Ollama archive did not contain the expected CLI; using the CPU container fallback."
      return 1
    fi
    if command -v codesign >/dev/null 2>&1 && ! codesign --verify --deep --strict "$staging/unpacked/Ollama.app" >/dev/null 2>&1; then
      rm -rf "$staging"
      red "  ERROR: downloaded Ollama.app failed the macOS code-signature check."
      return 1
    fi
    mv "$staging/unpacked/Ollama.app" "$tools_root/Ollama.app"
    rm -rf "$staging"
    cli="$tools_root/Ollama.app/Contents/Resources/ollama"
    green "  Verified host Ollama installed under $tools_root/Ollama.app"
  fi

  mkdir -p "$ROOT/.aetherstack"
  bind="${host_ollama_url#http://}"
  bind="${bind#https://}"
  log="$ROOT/.aetherstack/managed-ollama.log"
  cyan "  Starting host Ollama at $host_ollama_url (Apple Metal when supported)..."
  nohup env OLLAMA_HOST="$bind" "$cli" serve >"$log" 2>&1 < /dev/null &
  pid=$!
  printf '%s\n' "$pid" > "$ROOT/.aetherstack/managed-ollama.pid"
  printf '%s\n' "$cli" > "$ROOT/.aetherstack/managed-ollama.command"
  for _ in $(seq 1 45); do
    if curl -sf --max-time 2 "$host_ollama_url/api/tags" >/dev/null 2>&1; then
      green "  Host Ollama is ready."
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
    sleep 2
  done
  yellow "  Host Ollama did not become ready; see $log. Using the CPU container fallback."
  kill "$pid" 2>/dev/null || true
  rm -f "$ROOT/.aetherstack/managed-ollama.pid" "$ROOT/.aetherstack/managed-ollama.command"
  return 1
}

install_linux_docker() {
  [[ "$OS_NAME" == "Linux" ]] || return 1
  [[ "${AETHER_AUTO_INSTALL_DOCKER:-1}" != "0" ]] || return 1
  command -v curl >/dev/null 2>&1 || { yellow "  Docker is absent and curl is unavailable; install Docker manually."; return 1; }
  command -v sudo >/dev/null 2>&1 || { yellow "  Docker is absent and sudo is unavailable; install Docker manually."; return 1; }
  local script
  script="$(mktemp "${TMPDIR:-/tmp}/aetherstack-get-docker.XXXXXX.sh")"
  cyan "  Docker is absent. Installing via the official convenience script (get.docker.com)..."
  if ! curl -fsSL https://get.docker.com -o "$script"; then
    rm -f "$script"; yellow "  Docker install script download failed."; return 1
  fi
  if ! sudo sh "$script"; then
    rm -f "$script"; red "  ERROR: Docker install script failed."; return 1
  fi
  rm -f "$script"
  sudo systemctl enable --now docker 2>/dev/null || true
  command -v docker >/dev/null 2>&1 || return 1
  if ! id -nG "$USER" 2>/dev/null | grep -qw docker; then
    sudo usermod -aG docker "$USER" 2>/dev/null || true
    if ! docker info >/dev/null 2>&1 && command -v sg >/dev/null 2>&1; then
      yellow "  Applying the new docker group membership for this run (re-exec via sg)..."
      exec sg docker -c "$(printf '%q ' "$0" "$@")"
    fi
    yellow "  Added $USER to the docker group — log out/in (or reboot) so future runs don't need sudo."
  fi
  green "  Installed Docker."
  return 0
}

install_macos_docker() {
  [[ "$OS_NAME" == "Darwin" ]] || return 1
  [[ "${AETHER_AUTO_INSTALL_DOCKER:-1}" != "0" ]] || return 1
  if command -v brew >/dev/null 2>&1; then
    cyan "  Docker is absent. Installing Docker Desktop via Homebrew..."
    brew install --cask docker || { yellow "  Homebrew cask install failed."; return 1; }
  else
    command -v curl >/dev/null 2>&1 || { yellow "  Docker is absent and curl/Homebrew are unavailable; install Docker Desktop manually."; return 1; }
    command -v hdiutil >/dev/null 2>&1 || { yellow "  Docker is absent and hdiutil is unavailable; install Docker Desktop manually."; return 1; }
    local arch dmg_url staging dmg mount_point
    arch="$(uname -m)"
    if [[ "$arch" == "arm64" ]]; then
      dmg_url="https://desktop.docker.com/mac/main/arm64/Docker.dmg"
    else
      dmg_url="https://desktop.docker.com/mac/main/amd64/Docker.dmg"
    fi
    staging="$(mktemp -d "${TMPDIR:-/tmp}/aetherstack-docker.XXXXXX")"
    dmg="$staging/Docker.dmg"
    cyan "  Docker is absent. Downloading Docker Desktop ($arch)..."
    if ! curl --fail --location --progress-bar --retry 3 "$dmg_url" -o "$dmg"; then
      rm -rf "$staging"; yellow "  Docker Desktop download failed."; return 1
    fi
    mount_point="$staging/mnt"
    mkdir -p "$mount_point"
    if ! hdiutil attach "$dmg" -mountpoint "$mount_point" -nobrowse -quiet; then
      rm -rf "$staging"; yellow "  Failed to mount the Docker Desktop image."; return 1
    fi
    if [[ ! -d "$mount_point/Docker.app" ]]; then
      hdiutil detach "$mount_point" -quiet 2>/dev/null || true
      rm -rf "$staging"; yellow "  Docker Desktop image did not contain Docker.app."; return 1
    fi
    if command -v codesign >/dev/null 2>&1 && ! codesign --verify --deep --strict "$mount_point/Docker.app" >/dev/null 2>&1; then
      hdiutil detach "$mount_point" -quiet 2>/dev/null || true
      rm -rf "$staging"; red "  ERROR: downloaded Docker.app failed the macOS code-signature check."; return 1
    fi
    cp -R "$mount_point/Docker.app" /Applications/Docker.app 2>/dev/null || cp -R "$mount_point/Docker.app" "$HOME/Applications/Docker.app"
    hdiutil detach "$mount_point" -quiet 2>/dev/null || true
    rm -rf "$staging"
    green "  Installed Docker Desktop."
  fi
  open -a Docker 2>/dev/null || true
  yellow "  Docker Desktop is starting for the first time — it may ask you to approve a privileged network helper; approve it, then re-run ./start.sh if this run times out."
  for _ in $(seq 1 30); do
    command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 && return 0
    sleep 2
  done
  command -v docker >/dev/null 2>&1
}

# Scan host before bring-up (Ollama / Docker / ports)
if [[ -x "$ROOT/scripts/scan-system.sh" ]] || [[ -f "$ROOT/scripts/scan-system.sh" ]]; then
  cyan "  Scanning system…"
  bash "$ROOT/scripts/scan-system.sh" || yellow "  Scan script warning (continuing)."
fi

if ! command -v docker >/dev/null 2>&1; then
  yellow "  Docker not found."
  installed=0
  if [[ "$OS_NAME" == "Darwin" ]]; then
    install_macos_docker && installed=1
  elif [[ "$OS_NAME" == "Linux" ]]; then
    install_linux_docker && installed=1
  fi
  if [[ "$installed" -ne 1 ]] || ! command -v docker >/dev/null 2>&1; then
    red "  ERROR: Docker not found and automatic install did not complete."
    if [[ "$OS_NAME" == "Darwin" ]]; then
      yellow "  macOS: install Docker Desktop — docs/TUTORIAL-MACOS.md"
      yellow "  https://docs.docker.com/desktop/setup/install/mac-install/"
    else
      yellow "  Ubuntu/Linux: see docs/TUTORIAL-UBUNTU.md"
    fi
    yellow "  Set AETHER_AUTO_INSTALL_DOCKER=0 to skip auto-install and only get this message."
    exit 1
  fi
fi

# Prefer docker compose plugin; fall back to docker-compose
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  red "  ERROR: docker compose plugin not found."
  exit 1
fi

# Ensure docker daemon is running
if ! docker info >/dev/null 2>&1; then
  yellow "  Docker daemon not running — trying to start..."
  if [[ "$OS_NAME" == "Darwin" ]]; then
    # Docker Desktop on macOS
    open -a Docker 2>/dev/null || true
    yellow "  Waiting for Docker Desktop..."
    for _ in $(seq 1 30); do
      if docker info >/dev/null 2>&1; then break; fi
      sleep 2
    done
  elif command -v systemctl >/dev/null 2>&1; then
    sudo systemctl start docker 2>/dev/null || true
    sleep 2
  fi
  if ! docker info >/dev/null 2>&1; then
    red "  ERROR: cannot reach Docker daemon. Start Docker Desktop / dockerd and retry."
    if [[ "$OS_NAME" == "Darwin" ]]; then
      yellow "  macOS: open Docker Desktop from Applications, wait until it is Running."
    fi
    exit 1
  fi
fi

# On Apple Silicon, provision and launch host Ollama before deciding whether
# the Linux-VM CPU fallback is necessary. The app is installed in user space,
# code-signature checked, and only the process started here is lifecycle-owned.
if ! curl -sf --max-time 2 "$host_ollama_url/api/tags" >/dev/null 2>&1; then
  start_macos_host_ollama || true
fi

mkdir -p "$ROOT/.aetherstack"
TOTALS_FILE="$ROOT/.aetherstack/download-totals"
: > "$TOTALS_FILE"

# Detect authenticated host CLI subscriptions (Codex CLI, Claude CLI, Grok CLI)
# so LiteLLM/the Hub can use them. Previously this only ever happened when the
# VSCode extension itself was open — a plain `./start.sh` run never started the
# bridge server, so those subscriptions were silently invisible to the stack
# even when the user was fully logged in to all three. Best-effort: skip
# quietly if Node isn't installed rather than failing the whole stack start.
CLI_BRIDGE_PID_FILE="$ROOT/.aetherstack/cli-bridge.pid"
CLI_BRIDGE_LOG="$ROOT/.aetherstack/cli-bridge.log"
CLI_BRIDGE_SESSION_FILE="$ROOT/.aetherstack/cli-bridge.screen"
stop_managed_cli_bridge() {
  if [[ -f "$CLI_BRIDGE_SESSION_FILE" ]] && command -v screen >/dev/null 2>&1; then
    old_session="$(cat "$CLI_BRIDGE_SESSION_FILE" 2>/dev/null || true)"
    [[ -n "$old_session" ]] && screen -S "$old_session" -X quit >/dev/null 2>&1 || true
  fi
  if [[ -f "$CLI_BRIDGE_PID_FILE" ]]; then
    old_bridge_pid="$(tr -dc '0-9' < "$CLI_BRIDGE_PID_FILE")"
    if [[ "$old_bridge_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_bridge_pid" 2>/dev/null; then
      kill "$old_bridge_pid" 2>/dev/null || true
    fi
  fi
  rm -f "$CLI_BRIDGE_PID_FILE" "$CLI_BRIDGE_SESSION_FILE"
}
start_managed_cli_bridge() {
  : > "$CLI_BRIDGE_LOG"
  if command -v screen >/dev/null 2>&1; then
    cli_bridge_session="aether-cli-$AETHER_CLI_BRIDGE_PORT"
    screen -S "$cli_bridge_session" -X quit >/dev/null 2>&1 || true
    screen -dmS "$cli_bridge_session" env \
      AETHER_CLI_BRIDGE_TOKEN="$AETHER_CLI_BRIDGE_TOKEN" \
      AETHER_CLI_BRIDGE_PORT="$AETHER_CLI_BRIDGE_PORT" \
      AETHER_STACK_ROOT="$ROOT" \
      node "$ROOT/scripts/cli-bridge-daemon.js"
    printf '%s\n' "$cli_bridge_session" > "$CLI_BRIDGE_SESSION_FILE"
  else
    AETHER_STACK_ROOT="$ROOT" nohup node "$ROOT/scripts/cli-bridge-daemon.js" \
      </dev/null >"$CLI_BRIDGE_LOG" 2>&1 &
    cli_bridge_pid=$!
    echo "$cli_bridge_pid" > "$CLI_BRIDGE_PID_FILE"
    disown "$cli_bridge_pid" 2>/dev/null || true
  fi
}
cli_bridge_ready() {
  curl -fsS --max-time 3 \
    -H "Authorization: Bearer $AETHER_CLI_BRIDGE_TOKEN" \
    "http://127.0.0.1:$AETHER_CLI_BRIDGE_PORT/health" >/dev/null 2>&1
}
stop_managed_cli_bridge
if command -v node >/dev/null 2>&1; then
  cyan "  Detecting host CLI subscriptions (Codex, Claude Code, Grok)…"
  cli_bridge_port="$(select_cli_bridge_port)" || { red "  ERROR: no free loopback port for the host CLI bridge (tried 8767-8777)."; exit 1; }
  if [[ "$cli_bridge_port" != "${AETHER_CLI_BRIDGE_PORT:-8767}" ]]; then
    yellow "  Port ${AETHER_CLI_BRIDGE_PORT:-8767} is occupied; using CLI bridge port $cli_bridge_port."
  fi
  export AETHER_CLI_BRIDGE_TOKEN="${AETHER_CLI_BRIDGE_TOKEN:-$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')}"
  export AETHER_CLI_BRIDGE_PORT="$cli_bridge_port"
  export AETHER_CLI_BRIDGE_URL="http://host.docker.internal:$cli_bridge_port"
  start_managed_cli_bridge
  sleep 1
  if [[ -s "$CLI_BRIDGE_LOG" ]]; then sed 's/^/  /' "$CLI_BRIDGE_LOG"; fi
else
  yellow "  Node.js not found — skipping host CLI subscription detection (Codex/Claude/Grok). Install Node to enable it."
fi

# host.docker.internal is set in compose (needed on Docker Desktop Mac/Win + some Linux)
cyan "  Starting containers (Open WebUI, LiteLLM, Redis, Postgres, Hub)..."
use_container_ollama=0
found_host_ollama="$(find_host_ollama || true)"
if [[ -n "$found_host_ollama" && "$found_host_ollama" != "$host_ollama_url" ]]; then
  yellow "  Host Ollama found at $found_host_ollama (configured port unreachable)."
  set_env_value "OLLAMA_BASE_URL" "${found_host_ollama//127.0.0.1/host.docker.internal}"
  host_ollama_url="$found_host_ollama"
fi
if [[ -z "$found_host_ollama" ]]; then
  use_container_ollama=1
  yellow "  Host Ollama is unavailable; starting the bundled CPU fallback."
  fallback_port="$(select_fallback_port)" || { red "  ERROR: no free loopback port for bundled Ollama (tried 11434 and 11436-11444)."; exit 1; }
  if [[ "$fallback_port" != "11434" ]]; then yellow "  Port 11434 is occupied; using fallback port $fallback_port."; fi
  set_env_value "OLLAMA_BASE_URL" "http://ollama:11434"
  set_env_value "AETHER_OLLAMA_PORT" "$fallback_port"
  export OLLAMA_BASE_URL="http://ollama:11434"
  export AETHER_OLLAMA_PORT="$fallback_port"
  host_ollama_url="http://127.0.0.1:$fallback_port"
  "${DC[@]}" --profile with-ollama-container --progress=json up -d --build 2>&1 | progress_filter "  Pulling/building images" "$TOTALS_FILE"
  compose_status="${PIPESTATUS[0]}"
else
  "${DC[@]}" --progress=json up -d --build 2>&1 | progress_filter "  Pulling/building images" "$TOTALS_FILE"
  compose_status="${PIPESTATUS[0]}"
fi
if (( compose_status != 0 )); then red "  ERROR: docker compose up failed"; exit 1; fi

ollama_deadline=$((SECONDS + 90))
until curl -sf --max-time 2 "$host_ollama_url/api/tags" >/dev/null 2>&1; do
  if (( SECONDS >= ollama_deadline )); then red "  ERROR: Ollama did not become ready at $host_ollama_url"; exit 1; fi
  sleep 2
done

env_ollama_models="$(sed -n 's/^[[:space:]]*AETHER_OLLAMA_MODELS[[:space:]]*=[[:space:]]*//p' .env | tail -1 | tr -d '\r' | sed "s/^[\"']//;s/[\"']$//")"
wanted_models="${AETHER_OLLAMA_MODELS:-${env_ollama_models:-qwen2.5-coder:1.5b,nomic-embed-text}}"
IFS=',' read -r -a startup_models <<< "$wanted_models"
for model in "${startup_models[@]}"; do
  model="${model//[[:space:]]/}"
  [[ -z "$model" ]] && continue
  if [[ ! "$model" =~ ^[A-Za-z0-9._:/-]+$ ]]; then red "  ERROR: invalid Ollama model name: $model"; exit 1; fi
  cyan "  Ensuring Ollama model: $model"
  if (( use_container_ollama )); then
    "${DC[@]}" --profile with-ollama-container exec -T ollama ollama pull "$model"
  elif command -v ollama >/dev/null 2>&1; then
    ollama pull "$model"
  else
    # Ollama's streaming NDJSON includes layer names, byte totals, and completed
    # bytes. progress_filter redraws that stream as a single line with a running
    # byte total instead of one new line per update (the same fix applied to the
    # docker compose pull/build step above), and reports the final total into
    # $TOTALS_FILE for the end-of-run summary.
    curl -fsS --no-buffer --max-time 900 -X POST "$host_ollama_url/api/pull" \
      -H 'Content-Type: application/json' -d "{\"name\":\"$model\",\"stream\":true}" \
      | progress_filter "  Pulling $model" "$TOTALS_FILE"
    pull_status="${PIPESTATUS[0]}"
    if (( pull_status != 0 )); then red "  ERROR: failed to pull Ollama model $model"; exit 1; fi
  fi
done
if [[ -n "${AETHER_CLI_BRIDGE_TOKEN:-}" && -n "${AETHER_CLI_BRIDGE_PORT:-}" ]]; then
  if ! cli_bridge_ready; then
    yellow "  Host CLI bridge stopped during startup; restarting it on port $AETHER_CLI_BRIDGE_PORT."
    start_managed_cli_bridge
    sleep 1
    if [[ -s "$CLI_BRIDGE_LOG" ]]; then sed 's/^/  /' "$CLI_BRIDGE_LOG"; fi
    if ! cli_bridge_ready; then
      red "  ERROR: host CLI bridge failed to stay running; see $CLI_BRIDGE_LOG."
      exit 1
    fi
  fi
fi
"${DC[@]}" restart aether-hub litellm >/dev/null

deadline=$((SECONDS + 120))
pending=""
while (( SECONDS < deadline )); do
  pending=""
  curl -sf --max-time 3 http://127.0.0.1:3000/healthz >/dev/null || pending="$pending Open-WebUI"
  curl -sf --max-time 3 http://127.0.0.1:4000/health/liveliness >/dev/null || pending="$pending LiteLLM"
  curl -sf --max-time 3 http://127.0.0.1:8766/api/health >/dev/null || pending="$pending AetherHub"
  [[ -z "$pending" ]] && break
  # Compose's depends_on/service_healthy sequencing can race on a first build:
  # a dependent container (observed: open-webui-proxy, which publishes :3000)
  # can get left in "Created" instead of started once its dependency finally
  # passes its health check. A cheap, idempotent `up -d` reconciles anything
  # left behind without re-pulling or rebuilding, each time through this wait.
  "${DC[@]}" up -d >/dev/null 2>&1 || true
  sleep 2
done
if [[ -n "$pending" ]]; then
  red "  ERROR: services did not become ready:$pending"
  "${DC[@]}" ps
  exit 1
fi
"${DC[@]}" ps

if curl -sf --max-time 2 "$host_ollama_url/api/tags" >/dev/null 2>&1; then
  green "  Ollama: OK on $host_ollama_url"
else
  yellow "  Note: Ollama not reachable at $host_ollama_url."
  yellow "  Install host Ollama (recommended — Metal on Apple Silicon): https://ollama.com"
  yellow "  Or: ${DC[*]} --profile with-ollama-container up -d"
  if [[ "$OS_NAME" == "Linux" ]]; then
    yellow "  AMD Linux: ${DC[*]} -f docker-compose.yml -f docker-compose.amd.yml --profile with-ollama-container up -d"
  fi
fi

total_downloaded_bytes="$(awk '{s+=$1} END{print s+0}' "$TOTALS_FILE" 2>/dev/null || echo 0)"
if (( total_downloaded_bytes > 0 )); then
  cyan "  Downloaded this run: $(awk -v b="$total_downloaded_bytes" 'BEGIN{u="B KB MB GB"; split(u,a," "); i=1; while (b>=1024 && i<4){b/=1024; i++} printf "%.1f%s", b, a[i]}')"
fi

echo ""
green "  --------------------------------"
green "  Chat UI:   http://localhost:3000"
green "  LiteLLM:   http://localhost:4000"
green "  Hub/scan:  http://localhost:8766  (discover first)"
green "  Redis:     localhost:6379"
green "  --------------------------------"
cyan "  Scan API:  http://localhost:8766/api/discover"
cyan "  Stop: ./stop.sh"
# Post the pre-start scan without repeating GPU probes.
if [[ -f "$ROOT/.aetherstack/system-scan.json" ]]; then
  scan_payload="$(python3 -c 'import json,sys; print(json.dumps({"host_scan":json.load(open(sys.argv[1]))}))' "$ROOT/.aetherstack/system-scan.json" 2>/dev/null || true)"
  [[ -n "$scan_payload" ]] && curl -sf -X POST http://127.0.0.1:8766/api/discover -H 'Content-Type: application/json' -d "$scan_payload" >/dev/null || true
fi
if [[ "$OS_NAME" == "Darwin" ]]; then
  cyan "  Guide: docs/TUTORIAL-MACOS.md"
fi
echo ""

# Open browser if possible (macOS: open · Linux: xdg-open)
if [[ "${AETHER_NO_BROWSER:-0}" == "1" ]]; then
  :
elif [[ "$OS_NAME" == "Darwin" ]] && command -v open >/dev/null 2>&1; then
  open "http://localhost:3000" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost:3000" >/dev/null 2>&1 || true
elif command -v sensible-browser >/dev/null 2>&1; then
  sensible-browser "http://localhost:3000" >/dev/null 2>&1 || true
fi
