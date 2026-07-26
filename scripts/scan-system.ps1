# AetherStack — host system scan (Windows + WSL). Run BEFORE / with stack start.
# Writes .aetherstack/system-scan.json and POSTs to hub if up.
param(
  [string]$Distro = "Debian",
  [string]$HubUrl = "http://127.0.0.1:8766",
  [switch]$JsonOnly
)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not (Test-Path (Join-Path $Root "docker-compose.yml"))) {
  $Root = Get-Location
}
Set-Location $Root

function Test-Url([string]$u, [int]$timeoutSec = 2) {
  try {
    $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec $timeoutSec
    return @{ ok = $true; status = [int]$r.StatusCode }
  } catch {
    return @{ ok = $false; error = $_.Exception.Message }
  }
}

$scan = [ordered]@{
  ts              = (Get-Date).ToUniversalTime().ToString("o")
  host            = $env:COMPUTERNAME
  os              = [System.Environment]::OSVersion.VersionString
  docker          = $null
  windows_ollama  = $null
  wsl             = $null
  ports           = @{}
  gpu_windows     = @()
  flags           = [ordered]@{}
}

# Docker
try {
  $ps = docker ps --format "{{.Names}}" 2>$null
  $scan.docker = @{
    ok       = $LASTEXITCODE -eq 0
    containers = @($ps)
  }
} catch {
  $scan.docker = @{ ok = $false; error = "$_" }
}

# Windows GPU
try {
  $scan.gpu_windows = @(
    Get-CimInstance Win32_VideoController | ForEach-Object {
      @{ name = $_.Name; driver = $_.DriverVersion }
    }
  )
} catch {}

# Port 11434 listeners
try {
  $scan.ports["11434"] = @(
    Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
      $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
      @{ pid = $_.OwningProcess; process = $p.ProcessName; path = $p.Path }
    }
  )
} catch {}

# Windows Ollama
$winOllamaProc = Get-Process -Name "ollama","ollama app" -ErrorAction SilentlyContinue
$winTags = Test-Url "http://127.0.0.1:11434/api/tags" 3
$winModels = @()
if ($winTags.ok) {
  try {
    $t = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
    $winModels = @($t.models | ForEach-Object { $_.name })
  } catch {}
}
$scan.windows_ollama = @{
  process_running = [bool]$winOllamaProc
  localhost_tags  = $winTags
  models          = $winModels
}

# WSL Debian
$wsl = [ordered]@{ distro = $Distro; available = $false }
try {
  $null = wsl -d $Distro -- echo ok 2>$null
  if ($LASTEXITCODE -eq 0) {
    $wsl.available = $true
    $wsl.ip = (wsl -d $Distro -- hostname -I).Trim().Split()[0]
    $wsl.ollama_active = (wsl -d $Distro -- bash -lc "systemctl is-active ollama 2>/dev/null || true").Trim()
    $wsl.dxg = (wsl -d $Distro -- bash -lc "test -e /dev/dxg && echo yes || echo no").Trim()
    $wsl.rocminfo_gpu = (wsl -d $Distro -- bash -lc "rocminfo 2>/dev/null | grep -E 'Marketing Name:.*Radeon|Device Type:.*GPU' | head -6 || true").Trim()
    $wsl.ollama_rocm_libs = (wsl -d $Distro -- bash -lc "if test -d /usr/local/lib/ollama/rocm || ls -d /usr/local/lib/ollama/rocm_* >/dev/null 2>&1; then echo yes; else echo no; fi").Trim()
    $wsl.ollama_lib_dirs = (wsl -d $Distro -- bash -lc "ls /usr/local/lib/ollama 2>/dev/null | tr '\n' ' '").Trim()
    $wsl.amd_compute_units = (wsl -d $Distro -- bash -lc "export HSA_ENABLE_DXG_DETECTION=1 HSA_OVERRIDE_GFX_VERSION=10.3.0 LD_LIBRARY_PATH=/opt/rocm/lib:/usr/lib/wsl/lib; rocminfo 2>/dev/null | awk '/Device Type:.*GPU/{g=1} g&&/Compute Unit:/{print; exit}'").Trim()
    $wsl.amd_gpu_name = (wsl -d $Distro -- bash -lc "export HSA_ENABLE_DXG_DETECTION=1 LD_LIBRARY_PATH=/opt/rocm/lib:/usr/lib/wsl/lib; rocminfo 2>/dev/null | awk '/Device Type:.*GPU/{g=1} g&&/Marketing Name:/{print; exit}'").Trim()
    if ($wsl.ip) {
      $wslTags = Test-Url "http://$($wsl.ip):11434/api/tags" 3
      $wsl.direct_tags = $wslTags
      if ($wslTags.ok) {
        try {
          $t = Invoke-RestMethod "http://$($wsl.ip):11434/api/tags" -TimeoutSec 3
          $wsl.models = @($t.models | ForEach-Object { $_.name })
        } catch { $wsl.models = @() }
      }
    }
  }
} catch {
  $wsl.error = "$_"
}
$scan.wsl = $wsl

# Flags for hub recommendations
$scan.flags.windows_ollama_and_wsl_both = (
  $scan.windows_ollama.process_running -and
  $wsl.available -and
  $wsl.ollama_active -eq "active"
)
$scan.flags.ollama_missing_rocm_libs = ($wsl.ollama_rocm_libs -eq "no")
$scan.flags.localhost_11434_broken = (-not $winTags.ok) -and ($wsl.direct_tags.ok -eq $true)
$scan.flags.wsl_ollama_ip = $wsl.ip
$scan.flags.radeon_visible_to_rocminfo = ($wsl.rocminfo_gpu -match "Radeon")
$scan.flags.localhost_11434_ok = [bool]$winTags.ok

# Compose services
$scan.services = @{
  "3000_webui"  = (Test-Url "http://127.0.0.1:3000/" 2).ok
  "4000_litellm" = (Test-Url "http://127.0.0.1:4000/v1/models" 2).ok  # may 401
  "6379_redis"  = $null
  "8766_hub"    = (Test-Url "http://127.0.0.1:8766/api/health" 2).ok
  "8765_engine" = (Test-Url "http://127.0.0.1:8765/api/health" 2).ok
}
try {
  $tcp = New-Object System.Net.Sockets.TcpClient
  $iar = $tcp.BeginConnect("127.0.0.1", 6379, $null, $null)
  $ok = $iar.AsyncWaitHandle.WaitOne(1000, $false)
  if ($ok -and $tcp.Connected) { $scan.services["6379_redis"] = $true } else { $scan.services["6379_redis"] = $false }
  $tcp.Close()
} catch { $scan.services["6379_redis"] = $false }

# Persist
$outDir = Join-Path $Root ".aetherstack"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$outPath = Join-Path $outDir "system-scan.json"
($scan | ConvertTo-Json -Depth 8) | Set-Content -Path $outPath -Encoding utf8

# POST host facts into hub if available
$hostScan = @{
  windows_ollama_and_wsl_both = $scan.flags.windows_ollama_and_wsl_both
  ollama_missing_rocm_libs    = $scan.flags.ollama_missing_rocm_libs
  localhost_11434_broken      = $scan.flags.localhost_11434_broken
  wsl_ollama_ip               = $scan.flags.wsl_ollama_ip
  radeon_visible_to_rocminfo  = $scan.flags.radeon_visible_to_rocminfo
  windows_models              = $scan.windows_ollama.models
  wsl_models                  = $wsl.models
  gpu_windows                 = $scan.gpu_windows
  containers                  = $scan.docker.containers
  raw_path                    = $outPath
}
if ($scan.services["8766_hub"]) {
  try {
    $body = @{ host_scan = $hostScan } | ConvertTo-Json -Depth 6
    Invoke-RestMethod -Method POST -Uri "$HubUrl/api/discover" -Body $body -ContentType "application/json" -TimeoutSec 10 | Out-Null
  } catch {}
}

if ($JsonOnly) {
  $scan | ConvertTo-Json -Depth 8
  exit 0
}

Write-Host ""
Write-Host "  AetherStack system scan" -ForegroundColor Cyan
Write-Host "  =======================" -ForegroundColor DarkCyan
Write-Host "  Docker:   $($scan.docker.ok)  containers: $($scan.docker.containers -join ', ')" 
Write-Host "  GPU Win:  $(($scan.gpu_windows | ForEach-Object { $_.name }) -join ' | ')"
Write-Host "  Ollama localhost:11434: $($winTags.ok)  models: $($winModels -join ', ')"
if ($wsl.available) {
  Write-Host "  WSL $Distro IP: $($wsl.ip)  ollama=$($wsl.ollama_active)  dxg=$($wsl.dxg)  rocm_libs=$($wsl.ollama_rocm_libs)"
  Write-Host "  WSL models: $($wsl.models -join ', ')"
  if ($wsl.amd_gpu_name -or $wsl.amd_compute_units) {
    Write-Host "  AMD compute: $($wsl.amd_gpu_name) $($wsl.amd_compute_units)" -ForegroundColor Cyan
  }
  if ($wsl.rocminfo_gpu) {
    $rg = ($wsl.rocminfo_gpu -replace "[\r\n]+", " / ")
    Write-Host "  rocminfo: $rg" -ForegroundColor DarkGray
  }
  if ($wsl.ollama_rocm_libs -eq "no" -and $wsl.dxg -eq "yes") {
    Write-Host "  ! AMD CUs visible but Ollama has no ROCm runners - install-ollama-rocm-wsl.sh" -ForegroundColor Yellow
  }
}
Write-Host "  Services: webui=$($scan.services['3000_webui']) litellm_port=$($scan.services['4000_litellm']) redis=$($scan.services['6379_redis']) hub=$($scan.services['8766_hub'])"
Write-Host ""
if ($scan.flags.windows_ollama_and_wsl_both) {
  Write-Host "  ! Both Windows and WSL Ollama active - prefer WSL ROCm on Radeon." -ForegroundColor Yellow
}
if ($scan.flags.ollama_missing_rocm_libs) {
  Write-Host "  ! Ollama in WSL has no ROCm runners (rocm/rocm_v*) - GPU idle until package is installed." -ForegroundColor Yellow
}
if ($scan.flags.localhost_11434_broken) {
  Write-Host "  ! localhost:11434 broken but WSL Ollama OK - run: .\scripts\ensure-wsl-ollama.ps1" -ForegroundColor Yellow
}
Write-Host "  Wrote $outPath" -ForegroundColor Green
Write-Host "  Hub discover: $HubUrl/api/discover" -ForegroundColor DarkCyan
Write-Host ""
