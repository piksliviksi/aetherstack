$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
Write-Host "Stopping AetherStack..." -ForegroundColor Yellow
docker compose down
Write-Host "Done." -ForegroundColor Green
