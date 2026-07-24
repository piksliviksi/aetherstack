param(
  [string]$Project = "",
  [int]$Port = 8765
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

$args = @("server.py", "--port", "$Port")
if ($Project) { $args += @("--project", $Project) }
Write-Host "Starting Project Engine on http://127.0.0.1:$Port" -ForegroundColor Cyan
python @args
