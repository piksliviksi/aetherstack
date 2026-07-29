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

function Ensure-Docker {
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $docker) {
    Write-Host "  ERROR: Docker not found. Install Docker Desktop:" -ForegroundColor Red
    Write-Host "  https://docs.docker.com/desktop/setup/install/windows-install/" -ForegroundColor Yellow
    exit 1
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
docker compose up -d
if ($LASTEXITCODE -ne 0) {
  Write-Host "  ERROR: docker compose failed." -ForegroundColor Red
  exit 1
}

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
