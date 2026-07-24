# List LiteLLM models (sends master key — browsers do not)
$Root = Split-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)
$envFile = Join-Path $Root ".env"
$key = "sk-aether-local"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*LITELLM_MASTER_KEY=(.+)\s*$') { $key = $Matches[1].Trim() }
  }
}
$headers = @{ Authorization = "Bearer $key" }
try {
  $r = Invoke-RestMethod -Uri "http://127.0.0.1:4000/v1/models" -Headers $headers
  $r.data | ForEach-Object { $_.id }
} catch {
  Write-Host "Failed: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "Is the stack running? start.bat / docker compose up -d"
  exit 1
}
