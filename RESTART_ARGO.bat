@echo off
cd /d "I:\argo"
echo Restarting ARGO stack - this drains the current voice worker safely
echo and starts everything fresh. This can take up to a minute.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "I:\argo\scripts\start_argo_stack.ps1"
echo.
echo Done. Press any key to close this window.
pause >nul
