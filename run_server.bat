@echo off
REM ARGO Server - Windows Batch Launcher
REM Runs server with proper Windows process isolation

cd /d "%~dp0input_shell"
echo.
echo ================================================================================
echo ARGO SERVER - WINDOWS MODE
echo ================================================================================
echo.
echo Server: http://127.0.0.1:8000
echo Mode: Native Windows process (isolated from parent shell)
echo.

python -m uvicorn app:app --host 127.0.0.1 --port 8000 --log-level info

pause
