param(
  [string]$Project = "",
  [int]$Port = 8765,
  [string]$Token = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# Prefer venv-less; install psutil if missing
python -c "import psutil" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing psutil (recommended)..." -ForegroundColor Yellow
  python -m pip install --user -q psutil
}

$pyArgs = @("server.py", "--port", "$Port", "--no-browser")
if ($Project) { $pyArgs += @("--project", $Project) }
$tok = if ($Token) { $Token } else { $env:AETHERSTACK_ENGINE_TOKEN }
if ($tok) { $pyArgs += @("--token", $tok) }
Write-Host "Starting Project Engine on http://127.0.0.1:$Port" -ForegroundColor Cyan
if ($tok) { Write-Host "Auth token: enabled (X-Aether-Token)" -ForegroundColor DarkYellow }
python @pyArgs
