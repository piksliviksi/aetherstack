# AetherStack - optional auto-install of missing packages / models / services.
# Default: DRY RUN. Use -Yes to apply. Use -Enable to turn on auto-install flag for hub.
param(
  [switch]$Yes,           # apply changes
  [switch]$Enable,        # POST hub enabled=true
  [switch]$Disable,
  [switch]$SafeOnly,      # only safe actions (default on apply)
  [switch]$IncludeElevated, # allow ROCm reinstall / portproxy / stop Win Ollama
  [string]$HubUrl = "http://127.0.0.1:8766",
  [string]$Distro = "Debian"
)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
if (-not $PSBoundParameters.ContainsKey("SafeOnly")) { $SafeOnly = -not $IncludeElevated }

function Get-DotEnvValue([string]$Name) {
  $path = Join-Path $Root ".env"
  if (-not (Test-Path $path)) { return $null }
  $line = Get-Content -LiteralPath $path | Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } | Select-Object -Last 1
  if (-not $line) { return $null }
  return (($line -split "=", 2)[1].Trim()).Trim('"').Trim("'")
}
$dockerOllamaUrl = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL } else { Get-DotEnvValue "OLLAMA_BASE_URL" }
if (-not $dockerOllamaUrl) { $dockerOllamaUrl = "http://host.docker.internal:11434" }
$HostOllamaUrl = ($dockerOllamaUrl -replace "host\.docker\.internal", "127.0.0.1" -replace "gateway\.docker\.internal", "127.0.0.1").TrimEnd('/')

Write-Host ""
Write-Host "  AetherStack auto-install" -ForegroundColor Cyan
Write-Host "  (optional - dry-run unless -Yes)" -ForegroundColor DarkCyan
Write-Host ""

# 1) Host scan first
$scanScript = Join-Path $Root "scripts\scan-system.ps1"
if (Test-Path $scanScript) {
  Write-Host "  Running system scan..." -ForegroundColor DarkCyan
  & powershell -NoProfile -ExecutionPolicy Bypass -File $scanScript 2>$null
}

# 2) Hub enable/disable
function Hub-Post($path, $obj) {
  try {
    $body = $obj | ConvertTo-Json -Depth 8 -Compress
    return Invoke-RestMethod -Method POST -Uri "$HubUrl$path" -Body $body -ContentType "application/json" -TimeoutSec 120
  } catch {
    Write-Host "  Hub $path failed: $($_.Exception.Message)" -ForegroundColor Yellow
    return $null
  }
}

if ($Disable) {
  Hub-Post "/api/bootstrap" @{ enabled = $false } | Out-Null
  Write-Host "  Auto-install disabled on hub." -ForegroundColor Green
}
if ($Enable) {
  Hub-Post "/api/bootstrap" @{ enabled = $true } | Out-Null
  Write-Host "  Auto-install ENABLED on hub." -ForegroundColor Green
}

# 3) Get plan from hub or local heuristics
$plan = $null
try {
  $plan = Invoke-RestMethod -Uri "$HubUrl/api/bootstrap?refresh=1" -TimeoutSec 30
} catch {
  Write-Host "  Hub not up - local plan only." -ForegroundColor Yellow
}

if ($plan -and $plan.actions) {
  Write-Host "  Plan: $($plan.action_count) action(s) (safe=$($plan.safe_count))" -ForegroundColor Cyan
  foreach ($a in $plan.actions) {
    $tag = if ($a.safe) { "safe" } else { "elevated" }
    Write-Host "   [$tag] $($a.title) - $($a.reason)" -ForegroundColor DarkGray
  }
} else {
  Write-Host "  No hub plan; applying local essentials if -Yes." -ForegroundColor DarkGray
}

if (-not $Yes) {
  Write-Host ""
  Write-Host "  Dry-run only. Re-run with -Yes to apply, e.g.:" -ForegroundColor Yellow
  Write-Host "    .\scripts\auto-install.ps1 -Enable -Yes" -ForegroundColor Yellow
  Write-Host "    .\scripts\auto-install.ps1 -Yes -IncludeElevated   # ROCm / portproxy" -ForegroundColor Yellow
  Write-Host ""
  # still ask hub for dry_run
  Hub-Post "/api/bootstrap/run" @{ confirm = $true; dry_run = $true; only_safe = $true } | Out-Null
  exit 0
}

# 4) Apply host-side actions
Write-Host "  Applying..." -ForegroundColor Cyan

# Python deps for host engine
$pyPkgs = @("redis", "PyYAML", "psutil")
foreach ($p in $pyPkgs) {
  python -c "import $($p -replace 'PyYAML','yaml' -replace 'redis','redis' -replace 'psutil','psutil')" 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  pip install $p" -ForegroundColor DarkCyan
    python -m pip install --user -q $p 2>&1 | Out-Null
  }
}

# Docker compose core
if (Get-Command docker -ErrorAction SilentlyContinue) {
  Write-Host "  docker compose up -d redis litellm aether-hub open-webui" -ForegroundColor DarkCyan
  docker compose up -d redis litellm aether-hub open-webui 2>&1 | Select-Object -Last 15
}

# Ollama models
function Test-Ollama { try { Invoke-WebRequest "$HostOllamaUrl/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true } catch { return $false } }
if (-not (Test-Ollama)) {
  Write-Host "  Ollama is not reachable at $HostOllamaUrl." -ForegroundColor Yellow
  Write-Host "  Start host Ollama first. Use -IncludeElevated only to try experimental WSL ROCm setup." -ForegroundColor Yellow
}
if (Test-Ollama) {
  if ($env:AETHER_OLLAMA_MODELS) {
    $wantText = $env:AETHER_OLLAMA_MODELS
  } else {
    try { $ramGb = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB } catch { $ramGb = 0 }
    $wantText = if ($ramGb -ge 10) { "llama3.1:8b,nomic-embed-text" } else { "tinyllama,nomic-embed-text" }
  }
  $want = @($wantText -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  try {
    $tags = (Invoke-RestMethod "$HostOllamaUrl/api/tags" -TimeoutSec 5).models.name
  } catch { $tags = @() }
  foreach ($m in $want) {
    $have = $tags | Where-Object { $_ -eq $m -or $_ -like "${m}:*" -or ($_ -split ":")[0] -eq $m }
    if (-not $have) {
      Write-Host "  ollama pull $m  (may take a while)" -ForegroundColor DarkCyan
      if (Get-Command ollama -ErrorAction SilentlyContinue) {
        ollama pull $m 2>&1 | Select-Object -Last 5
      } else {
        # API pull
        try {
          Invoke-RestMethod -Method POST "$HostOllamaUrl/api/pull" -Body (@{name=$m; stream=$false} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 3600 | Out-Null
          Write-Host "  pulled $m via API" -ForegroundColor Green
        } catch { Write-Host "  pull failed: $_" -ForegroundColor Yellow }
      }
    } else {
      Write-Host "  model ok: $m" -ForegroundColor Green
    }
  }
} else {
  Write-Host "  Ollama still down - skip model pulls." -ForegroundColor Yellow
}

# Elevated / host_tools
if ($IncludeElevated) {
  Write-Host "  Elevated actions..." -ForegroundColor Yellow
  # dual ollama
  $win = Get-Process -Name "ollama","ollama app" -ErrorAction SilentlyContinue
  $wslActive = (wsl -d $Distro -- bash -lc "systemctl is-active ollama 2>/dev/null" 2>$null)
  if ($win -and $wslActive -match "active") {
    Write-Host "  Stopping Windows Ollama for explicitly requested experimental WSL ROCm setup..." -ForegroundColor Yellow
    $win | Stop-Process -Force -ErrorAction SilentlyContinue
  }
  # portproxy
  $ens = Join-Path $Root "scripts\ensure-wsl-ollama.ps1"
  if (Test-Path $ens) { & powershell -NoProfile -ExecutionPolicy Bypass -File $ens 2>&1 | Out-Host }
  # ROCm ollama package - required to use AMD compute units (not stock install on WSL)
  $rocm = (wsl -d $Distro -- bash -lc "if test -d /usr/local/lib/ollama/rocm || ls -d /usr/local/lib/ollama/rocm_* >/dev/null 2>&1; then echo yes; else echo no; fi" 2>$null)
  if ($rocm -match "no") {
    Write-Host "  Installing Ollama ROCm backend for AMD compute engines (large download)..." -ForegroundColor Yellow
    $wslRoot = (wsl -d $Distro -- wslpath -a $Root 2>$null | Select-Object -First 1).Trim()
    if (-not $wslRoot) { throw "Cannot map the selected AetherStack runtime into WSL." }
    $script = "$wslRoot/scripts/install-ollama-rocm-wsl.sh"
    # Prefer repo path if mounted; fall back to copy
    wsl -d $Distro -- bash -lc "if [ -f '$script' ]; then sudo bash '$script'; else curl -fsSL https://ollama.com/download/ollama-linux-amd64-rocm.tar.zst -o /tmp/rocm.tzst && sudo mkdir -p /usr/local && sudo zstd -d -c /tmp/rocm.tzst | sudo tar -xf - -C /usr/local; fi" 2>&1 | Select-Object -Last 30
  } else {
    Write-Host "  Ollama ROCm libs present." -ForegroundColor Green
  }
  if (-not $wslRoot) { $wslRoot = (wsl -d $Distro -- wslpath -a $Root 2>$null | Select-Object -First 1).Trim() }
  wsl -d $Distro -- bash -lc "bash '$wslRoot/scripts/amd-compute-status.sh' 2>/dev/null || true" 2>&1 | Select-Object -Last 25
}

# 5) Tell hub to apply safe leftovers + refresh
if ($Enable -or $Yes) {
  Hub-Post "/api/bootstrap" @{ enabled = $true } | Out-Null
  $run = Hub-Post "/api/bootstrap/run" @{
    confirm   = $true
    dry_run   = $false
    only_safe = [bool]$SafeOnly
  }
  if ($run) {
    Write-Host "  Hub applied=$($run.applied) failed=$($run.failed) deferred=$($run.deferred)" -ForegroundColor Green
  }
}

# Final scan
if (Test-Path $scanScript) {
  Write-Host "  Re-scan..." -ForegroundColor DarkCyan
  & powershell -NoProfile -ExecutionPolicy Bypass -File $scanScript 2>$null
}
try {
  $d = Invoke-RestMethod "$HubUrl/api/discover?refresh=1" -TimeoutSec 20
  Write-Host "  Discover: ollama=$($d.summary.ollama_ok) models=$($d.summary.ollama_models) litellm=$($d.summary.litellm_ok)" -ForegroundColor Green
} catch {}

Write-Host ""
Write-Host "  Done. Review: http://127.0.0.1:8766/api/bootstrap" -ForegroundColor Cyan
Write-Host ""
