@echo off
title AetherStack
cd /d "%~dp0"
echo.
echo  ========================================
echo   AetherStack - starting...
echo  ========================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
  echo.
  echo  Start failed. Press any key to close.
  pause >nul
  exit /b 1
)
echo.
echo  Press any key to close this window (stack keeps running).
pause >nul
