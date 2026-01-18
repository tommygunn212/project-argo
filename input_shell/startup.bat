@echo off
REM ARGO Input Shell Startup Script

echo.
echo ================================================================================
echo   ARGO INPUT SHELL (v1.4.2) - LOCAL TESTING ONLY
echo ================================================================================
echo.
echo   No background listening
echo   All actions require explicit confirmation
echo   Frozen layers NOT modified
echo   Only execute_and_confirm() used for execution
echo.
echo ================================================================================
echo.

REM Check if in correct directory
if not exist "app.py" (
    echo ERROR: Please run this script from the input_shell directory
    echo Usage: cd i:\argo\input_shell ^&^& startup.bat
    pause
    exit /b 1
)

REM Install dependencies if needed
echo Checking dependencies...
pip install -q -r requirements.txt

REM Start FastAPI server
echo.
echo Starting server on http://127.0.0.1:8000
echo.
echo Press Ctrl+C to stop
echo.

python app.py
