# AetherStack — Windows 11 start script (double-click start.bat)
# Requires: Docker Desktop. Optional: host Ollama for local models.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Write-Banner {
  Write-Host ""
  Write-Host "  AetherStack" -ForegroundColor Cyan
  Write-Host "  Multi-model LLM control plane" -ForegroundColor DarkCyan
  Write-Host ""
}

function Ensure-EnvFile {
  if (-not (Test-Path (Join-Path $Root ".env"))) {
    Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env")
    Write-Host "  Created .env from .env.example — add API keys when ready." -ForegroundColor Yellow
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
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:11434/" -UseBasicParsing -TimeoutSec 2
    return $true
  } catch {
    return $false
  }
}

Write-Banner
Ensure-EnvFile
Ensure-Docker

Write-Host "  Starting containers (Open WebUI, LiteLLM, Redis)..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) {
  Write-Host "  ERROR: docker compose failed." -ForegroundColor Red
  exit 1
}

Start-Sleep -Seconds 3
docker compose ps

if (-not (Test-Ollama)) {
  Write-Host ""
  Write-Host "  Note: Ollama is not responding on :11434." -ForegroundColor Yellow
  Write-Host "  Install/start host Ollama for local models: https://ollama.com" -ForegroundColor Yellow
  Write-Host "  Or: docker compose --profile with-ollama-container up -d" -ForegroundColor Yellow
} else {
  Write-Host "  Ollama: OK on http://127.0.0.1:11434" -ForegroundColor Green
}

Write-Host ""
Write-Host "  --------------------------------" -ForegroundColor DarkGray
Write-Host "  Chat UI:   http://localhost:3000" -ForegroundColor Green
Write-Host "  LiteLLM:   http://localhost:4000/v1" -ForegroundColor Green
Write-Host "  Redis:     localhost:6379" -ForegroundColor Green
Write-Host "  --------------------------------" -ForegroundColor DarkGray
Write-Host "  Hub matrix/memory: http://localhost:8766" -ForegroundColor DarkCyan
Write-Host "  Models list (if master key empty): http://localhost:4000/v1/models" -ForegroundColor DarkCyan
Write-Host "  With key: curl ... -H `"Authorization: Bearer YOUR_KEY`"" -ForegroundColor DarkGray
Write-Host "  Stop: double-click stop.bat" -ForegroundColor DarkCyan
Write-Host ""

# Open chat UI
Start-Process "http://localhost:3000"
