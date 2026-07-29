# Ensure WSL Debian Ollama (ROCm/DXG) is reachable on Windows localhost:11434.
# Stops Windows Ollama if it owns the port (CPU/Vulkan path fights ROCm path).
param(
  [string]$Distro = "Debian"
)
$ErrorActionPreference = "Continue"

function Test-Ollama([string]$url = "http://127.0.0.1:11434/") {
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
    return $r.StatusCode -eq 200
  } catch { return $false }
}

# Prefer WSL ROCm: stop native Windows Ollama so it does not bind :11434
$winOllama = Get-Process -Name "ollama","ollama app" -ErrorAction SilentlyContinue
if ($winOllama) {
  Write-Host "Stopping Windows Ollama so WSL ROCm can own :11434..." -ForegroundColor Yellow
  $winOllama | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 1
}

# Start WSL ollama
wsl -d $Distro -- bash -lc "sudo systemctl start ollama 2>/dev/null; systemctl is-active ollama" | Out-Host
$wslip = (wsl -d $Distro -- hostname -I).Trim().Split()[0]
if (-not $wslip) { throw "Cannot resolve WSL IP for $Distro" }
Write-Host "WSL IP: $wslip"

if (Test-Ollama "http://${wslip}:11434/") {
  Write-Host "WSL Ollama OK on ${wslip}:11434" -ForegroundColor Green
} else {
  Write-Host "WSL Ollama not answering on ${wslip}:11434" -ForegroundColor Red
}

if (-not (Test-Ollama "http://127.0.0.1:11434/")) {
  Write-Host "localhost:11434 not forwarded - setting netsh portproxy..." -ForegroundColor Yellow
  netsh interface portproxy delete v4tov4 listenport=11434 listenaddress=127.0.0.1 2>$null | Out-Null
  netsh interface portproxy add v4tov4 listenport=11434 listenaddress=127.0.0.1 connectport=11434 connectaddress=$wslip | Out-Null
  Start-Sleep -Seconds 1
}

if (Test-Ollama) {
  Write-Host "OK: http://127.0.0.1:11434 -> WSL Ollama (use this for Docker host.docker.internal)" -ForegroundColor Green
  try {
    $tags = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
    $tags.models | ForEach-Object { Write-Host "  model: $($_.name)" }
  } catch {}
  exit 0
} else {
  Write-Host "FAILED: could not reach Ollama on localhost:11434" -ForegroundColor Red
  Write-Host "Try: admin PowerShell, or wsl --shutdown then re-run." -ForegroundColor DarkYellow
  exit 1
}
