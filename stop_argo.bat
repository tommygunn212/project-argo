@echo off
setlocal
cd /d "I:\argo"

powershell -NoProfile -Command "Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.Path -like '*argo*'} | Stop-Process -Force -ErrorAction SilentlyContinue"
echo Stopped ARGO Python processes.

endlocal
