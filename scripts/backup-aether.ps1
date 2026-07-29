# AetherStack backup - project or global memory/research export.
# Destinations: local folder (default), optional AWS S3 / Azure Blob via hub config.
param(
  [ValidateSet("global", "project")]
  [string]$Scope = "global",
  [string]$ProjectPath = "",
  [string]$ProjectId = "",
  [string]$SessionId = "",
  [string]$HubUrl = "http://127.0.0.1:8766",
  [string[]]$Destinations = @("local"),  # local, aws, azure
  [switch]$IncludePrivate,
  [switch]$ConfigureAuto,
  [int]$AutoIntervalSec = 86400,
  [string]$LocalDir = "",
  [string]$S3Bucket = "",
  [string]$AzureContainer = ""
)
$ErrorActionPreference = "Continue"

if ($ConfigureAuto -or $LocalDir -or $S3Bucket -or $AzureContainer) {
  $cfg = @{ auto = @{ enabled = [bool]$ConfigureAuto; interval_sec = $AutoIntervalSec; scope = $Scope } }
  if ($LocalDir) { $cfg.local = @{ enabled = $true; path = $LocalDir } }
  if ($S3Bucket) { $cfg.aws = @{ enabled = $true; bucket = $S3Bucket } }
  if ($AzureContainer) { $cfg.azure = @{ enabled = $true; container = $AzureContainer } }
  try {
    $r = Invoke-RestMethod -Method POST -Uri "$HubUrl/api/backup/config" -ContentType "application/json" `
      -Body ($cfg | ConvertTo-Json -Depth 6) -TimeoutSec 30
    Write-Host "Config updated" -ForegroundColor Green
    $r | ConvertTo-Json -Depth 4 | Write-Host
  } catch {
    Write-Host "Config failed: $_" -ForegroundColor Red
  }
}

$body = @{
  scope = $Scope
  destinations = $Destinations
  include_private = [bool]$IncludePrivate
}
if ($ProjectPath) { $body.project_path = $ProjectPath }
if ($ProjectId) { $body.project_id = $ProjectId }
if ($SessionId) { $body.session_id = $SessionId }

Write-Host "Running backup scope=$Scope dest=$($Destinations -join ',')" -ForegroundColor Cyan
try {
  $res = Invoke-RestMethod -Method POST -Uri "$HubUrl/api/backup" -ContentType "application/json" `
    -Body ($body | ConvertTo-Json -Depth 6) -TimeoutSec 120
  $res | ConvertTo-Json -Depth 6
  if (-not $res.ok) { exit 1 }
} catch {
  Write-Host "Backup failed (is hub up?): $_" -ForegroundColor Red
  exit 1
}
