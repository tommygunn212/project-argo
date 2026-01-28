@echo off
setlocal
cd /d "I:\argo"

start "" http://localhost:8000
start "ARGO Backend" cmd /k "I:\argo\.venv\Scripts\python.exe I:\argo\main.py"

endlocal
