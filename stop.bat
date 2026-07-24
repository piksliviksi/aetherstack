@echo off
title AetherStack - stop
cd /d "%~dp0"
echo Stopping AetherStack...
docker compose down
echo Done.
pause
