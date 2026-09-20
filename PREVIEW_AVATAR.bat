@echo off
cd /d "I:\argo"
echo Starting the avatar portrait preview.
echo This is a throwaway static server - it does not touch the voice stack.
echo.
start "ARGO avatar preview server" ".venv\Scripts\python.exe" "tools\motion_lab_server.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8777/avatar-portrait-preview.html"
echo.
echo Opened http://127.0.0.1:8777/avatar-portrait-preview.html
echo Leave the "ARGO avatar preview server" window open while you look.
echo.
echo Press any key to close this window.
pause >nul
