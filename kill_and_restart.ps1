#!/usr/bin/env pwsh
# Kill ARGO and restart with audio fixes

Write-Host "Stopping all Python processes..."
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

Start-Sleep -Seconds 2

Write-Host "Installing soundfile..."
cd i:\argo
& ".\.venv\Scripts\pip.exe" install soundfile -q

Write-Host "Starting ARGO with audio enabled..."
$env:VOICE_ENABLED="true"
$env:PIPER_ENABLED="true"

& ".\.venv\Scripts\python.exe" wrapper/argo.py
