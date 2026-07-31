# AetherStack - Windows 11 start script (double-click start.bat)
# Requires: Docker Desktop. Optional: host Ollama for local models.
# Optional: -AutoInstall  to install missing safe packages after start

param(
  [switch]$AutoInstall,
  [switch]$AutoInstallElevated,
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Get-DotEnvValue([string]$Name) {
  $path = Join-Path $Root ".env"
  if (-not (Test-Path $path)) { return $null }
  $line = Get-Content -LiteralPath $path | Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } | Select-Object -Last 1
  if (-not $line) { return $null }
  return (($line -split "=", 2)[1].Trim()).Trim('"').Trim("'")
}

function Get-HostOllamaUrl {
  $value = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL } else { Get-DotEnvValue "OLLAMA_BASE_URL" }
  if (-not $value) { $value = "http://127.0.0.1:11434" }
  if ($value -match '^https?://ollama(?::11434)?/?$') {
    $fallbackPort = if ($env:AETHER_OLLAMA_PORT) { $env:AETHER_OLLAMA_PORT } else { Get-DotEnvValue "AETHER_OLLAMA_PORT" }
    if (-not $fallbackPort) { $fallbackPort = "11434" }
    return "http://127.0.0.1:$fallbackPort"
  }
  return ($value -replace "host\.docker\.internal", "127.0.0.1" -replace "gateway\.docker\.internal", "127.0.0.1").TrimEnd('/')
}

function Write-Banner {
  Write-Host ""
  Write-Host "  AetherStack" -ForegroundColor Cyan
  Write-Host "  Multi-model LLM control plane" -ForegroundColor DarkCyan
  Write-Host ""
}

function Invoke-SystemScan {
  $scan = Join-Path $Root "scripts\scan-system.ps1"
  if (Test-Path $scan) {
    Write-Host "  Scanning system (Ollama / GPU / WSL / ports)..." -ForegroundColor DarkCyan
    try {
      & powershell -NoProfile -ExecutionPolicy Bypass -File $scan
    } catch {
      Write-Host "  Scan warning: $_" -ForegroundColor Yellow
    }
  }
}

function Ensure-EnvFile {
  if (-not (Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
    Write-Host "  Created .env from .env.example - add API keys when ready." -ForegroundColor Yellow
  }
}

function Install-DockerDesktop {
  if ($env:AETHER_AUTO_INSTALL_DOCKER -eq "0") { return $false }
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    Write-Host "  winget is unavailable; cannot auto-install Docker Desktop." -ForegroundColor Yellow
    return $false
  }
  Write-Host "  Docker is absent. Installing Docker Desktop via winget..." -ForegroundColor Cyan
  winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements --silent
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  winget install of Docker Desktop failed (exit $LASTEXITCODE)." -ForegroundColor Yellow
    return $false
  }
  Write-Host "  Installed Docker Desktop." -ForegroundColor Green
  return $true
}

function Ensure-Docker {
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $docker) {
    Write-Host "  Docker not found." -ForegroundColor Yellow
    if (-not (Install-DockerDesktop)) {
      Write-Host "  ERROR: Docker not found and automatic install did not complete." -ForegroundColor Red
      Write-Host "  Install Docker Desktop manually: https://docs.docker.com/desktop/setup/install/windows-install/" -ForegroundColor Yellow
      Write-Host "  Set AETHER_AUTO_INSTALL_DOCKER=0 to skip auto-install and only get this message." -ForegroundColor Yellow
      exit 1
    }
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
      Write-Host "  Docker Desktop was installed but a new terminal is needed to pick up PATH; re-run .\start.ps1." -ForegroundColor Yellow
      exit 1
    }
  }

  docker info 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0) { return }

  Write-Host "  Starting Docker Desktop..." -ForegroundColor Yellow
  $candidates = @(
    "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
    "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
  )
  $exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $exe) {
    Write-Host "  ERROR: Docker Desktop not installed." -ForegroundColor Red
    exit 1
  }
  Start-Process $exe | Out-Null

  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 3
    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
      Write-Host "  Docker is ready." -ForegroundColor Green
      return
    }
    Write-Host "  waiting for Docker... $($i * 3)s" -ForegroundColor DarkGray
  }
  Write-Host "  ERROR: Docker did not become ready in time. Open Docker Desktop and retry." -ForegroundColor Red
  exit 1
}

function Test-Ollama {
  try {
    $r = Invoke-WebRequest -Uri "$script:HostOllamaUrl/api/tags" -UseBasicParsing -TimeoutSec 2
    return $true
  } catch {
    return $false
  }
}

function Find-HostOllama {
  # The configured/default port can be squatted by an unrelated process (seen
  # in practice with svchost on Ollama's default 11434); probe common alternate
  # ports for a real host Ollama before concluding none is reachable and
  # falling back to the bundled container.
  if (Test-Ollama) { return $script:HostOllamaUrl }
  foreach ($port in 11434, 11435, 11436, 11437, 11438, 11439, 11440) {
    try {
      $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/tags" -UseBasicParsing -TimeoutSec 2
      if ($r.StatusCode -eq 200) { return "http://127.0.0.1:$port" }
    } catch {}
  }
  return $null
}

function Set-DotEnvValue([string]$Name, [string]$Value) {
  $path = Join-Path $Root ".env"
  $lines = if (Test-Path $path) { @(Get-Content -LiteralPath $path) } else { @() }
  $found = $false
  $next = foreach ($line in $lines) {
    if ($line -match "^\s*$([regex]::Escape($Name))\s*=") {
      if (-not $found) { "$Name=$Value" }
      $found = $true
    } else { $line }
  }
  if (-not $found) { $next += "$Name=$Value" }
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllLines($path, [string[]]$next, $utf8NoBom)
}

function Test-LocalPortAvailable([int]$Port) {
  $listener = $null
  try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start()
    return $true
  } catch {
    return $false
  } finally {
    if ($listener) { $listener.Stop() }
  }
}

function Select-FallbackOllamaPort {
  $configured = if ($env:AETHER_OLLAMA_PORT) { $env:AETHER_OLLAMA_PORT } else { Get-DotEnvValue "AETHER_OLLAMA_PORT" }
  $candidates = @($configured, 11434, 11436, 11437, 11438, 11439, 11440, 11441, 11442, 11443, 11444) |
    Where-Object { $_ -and "$_" -match '^\d+$' } |
    Select-Object -Unique
  foreach ($candidate in $candidates) {
    $port = [int]$candidate
    if ($port -ge 1024 -and $port -le 65535 -and (Test-LocalPortAvailable $port)) { return $port }
  }
  throw "No free loopback port is available for the bundled Ollama fallback (tried 11434 and 11436-11444)."
}

function Wait-Ollama {
  $deadline = (Get-Date).AddSeconds(90)
  do {
    if (Test-Ollama) { return }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt $deadline)
  throw "Ollama did not become ready at $script:HostOllamaUrl"
}

function Ensure-OllamaModels {
  param([switch]$Container)
  $wanted = if ($env:AETHER_OLLAMA_MODELS) { $env:AETHER_OLLAMA_MODELS } else { Get-DotEnvValue "AETHER_OLLAMA_MODELS" }
  if (-not $wanted) { $wanted = "qwen2.5-coder:1.5b,nomic-embed-text" }
  foreach ($model in @($wanted -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
    Write-Host "  Ensuring Ollama model: $model" -ForegroundColor DarkCyan
    if ($Container) {
      docker compose --profile with-ollama-container exec -T ollama ollama pull $model
      if ($LASTEXITCODE -ne 0) { throw "Ollama model pull failed: $model" }
    } elseif (Get-Command ollama -ErrorAction SilentlyContinue) {
      & ollama pull $model
      if ($LASTEXITCODE -ne 0) { throw "Ollama model pull failed: $model" }
    } elseif (Get-Command curl.exe -ErrorAction SilentlyContinue) {
      $body = @{ name = $model; stream = $true } | ConvertTo-Json -Compress
      & curl.exe --fail --show-error --no-buffer --max-time 900 -X POST "$script:HostOllamaUrl/api/pull" -H "Content-Type: application/json" -d $body
      if ($LASTEXITCODE -ne 0) { throw "Ollama model pull failed: $model" }
    } else {
      $body = @{ name = $model; stream = $false } | ConvertTo-Json -Compress
      Invoke-RestMethod -Method Post -Uri "$script:HostOllamaUrl/api/pull" -Body $body -ContentType "application/json" -TimeoutSec 900 | Out-Null
    }
  }
}

function Publish-SystemScan {
  $path = Join-Path $Root ".aetherstack\system-scan.json"
  if (-not (Test-Path $path)) { return }
  try {
    $report = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if (-not $report.PSObject.Properties["containers"]) {
      $report | Add-Member -NotePropertyName containers -NotePropertyValue @($report.docker.containers)
    }
    $body = @{ host_scan = $report } | ConvertTo-Json -Depth 12
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8766/api/discover" -Body $body -ContentType "application/json" -TimeoutSec 30 | Out-Null
  } catch {
    Write-Host "  Host scan publish warning: $_" -ForegroundColor Yellow
  }
}

function Wait-CoreServices {
  $checks = [ordered]@{
    "Open WebUI" = "http://127.0.0.1:3000/"
    "LiteLLM" = "http://127.0.0.1:4000/health/liveliness"
    "AetherHub" = "http://127.0.0.1:8766/api/health"
  }
  $deadline = (Get-Date).AddSeconds(120)
  do {
    $pending = @()
    foreach ($entry in $checks.GetEnumerator()) {
      try { Invoke-WebRequest -Uri $entry.Value -UseBasicParsing -TimeoutSec 3 | Out-Null } catch { $pending += $entry.Key }
    }
    if ($pending.Count -eq 0) { return }
    Start-Sleep -Seconds 2
  } while ((Get-Date) -lt $deadline)
  throw "Services did not become ready: $($pending -join ', '). Run docker compose ps and docker compose logs."
}

Write-Banner
Ensure-EnvFile
$script:HostOllamaUrl = Get-HostOllamaUrl
Ensure-Docker
Invoke-SystemScan

Write-Host "  Starting containers (Open WebUI, LiteLLM, Redis, Hub)..." -ForegroundColor Cyan
$foundHostOllama = Find-HostOllama
if ($foundHostOllama -and $foundHostOllama -ne $script:HostOllamaUrl) {
  Write-Host "  Host Ollama found at $foundHostOllama (configured port unreachable)." -ForegroundColor Yellow
  Set-DotEnvValue "OLLAMA_BASE_URL" ($foundHostOllama -replace "127\.0\.0\.1", "host.docker.internal")
  $script:HostOllamaUrl = $foundHostOllama
}
$useContainerOllama = -not $foundHostOllama
if ($useContainerOllama) {
  Write-Host "  Host Ollama is unavailable; starting the bundled CPU fallback." -ForegroundColor Yellow
  $fallbackPort = Select-FallbackOllamaPort
  if ($fallbackPort -ne 11434) {
    Write-Host "  Port 11434 is occupied; using fallback port $fallbackPort." -ForegroundColor Yellow
  }
  Set-DotEnvValue "OLLAMA_BASE_URL" "http://ollama:11434"
  Set-DotEnvValue "AETHER_OLLAMA_PORT" "$fallbackPort"
  $env:AETHER_OLLAMA_PORT = "$fallbackPort"
  $script:HostOllamaUrl = "http://127.0.0.1:$fallbackPort"
  docker compose --profile with-ollama-container up -d --build
} else {
  docker compose up -d --build
}
if ($LASTEXITCODE -ne 0) {
  Write-Host "  ERROR: docker compose failed." -ForegroundColor Red
  exit 1
}

Wait-Ollama
Ensure-OllamaModels -Container:$useContainerOllama
docker compose restart aether-hub litellm | Out-Null
Wait-CoreServices
docker compose ps

if (-not (Test-Ollama)) {
  Write-Host ""
  Write-Host "  Note: Ollama is not responding at $script:HostOllamaUrl." -ForegroundColor Yellow
  Write-Host "  AMD Radeon on Windows: use host Ollama (Vulkan). WSL ROCm is experimental." -ForegroundColor Yellow
  Write-Host "  Or host Ollama: https://ollama.com" -ForegroundColor Yellow
} else {
  Write-Host "  Ollama: OK on $script:HostOllamaUrl" -ForegroundColor Green
}

# Publish the pre-start scan without repeating slow WSL/GPU probes.
Publish-SystemScan

if ($AutoInstall -or $AutoInstallElevated) {
  Write-Host "  Auto-install missing packages..." -ForegroundColor Cyan
  $ai = Join-Path $Root "scripts\auto-install.ps1"
  if (Test-Path $ai) {
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ai, "-Enable", "-Yes")
    if ($AutoInstallElevated) { $args += "-IncludeElevated" }
    & powershell @args
  }
}

Write-Host ""
Write-Host "  --------------------------------" -ForegroundColor DarkGray
Write-Host "  Chat UI:   http://localhost:3000" -ForegroundColor Green
Write-Host "  LiteLLM:   http://localhost:4000/v1" -ForegroundColor Green
Write-Host "  Hub/scan:  http://localhost:8766   (discover first)" -ForegroundColor Green
Write-Host "  Redis:     localhost:6379" -ForegroundColor Green
Write-Host "  --------------------------------" -ForegroundColor DarkGray
Write-Host "  System scan JSON: .aetherstack\system-scan.json" -ForegroundColor DarkCyan
Write-Host "  Discover API:     http://localhost:8766/api/discover" -ForegroundColor DarkCyan
Write-Host "  Auto-install:     .\scripts\auto-install.ps1 -Enable -Yes" -ForegroundColor DarkCyan
Write-Host "  With key: curl ... -H `"Authorization: Bearer YOUR_KEY`"" -ForegroundColor DarkGray
Write-Host "  Stop: double-click stop.bat" -ForegroundColor DarkCyan
Write-Host ""

# Open chat UI
if (-not $NoBrowser) { Start-Process "http://localhost:3000" }
