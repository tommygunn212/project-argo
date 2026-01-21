@echo off
REM ARGO GUI Launcher - One-button interface with status lights and log display

REM Activate virtual environment
call I:\argo\.venv\Scripts\activate.bat

REM Run GUI
python I:\argo\gui_launcher.py

REM Keep window open if there's an error
if errorlevel 1 pause
