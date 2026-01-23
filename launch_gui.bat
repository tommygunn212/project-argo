@echo off
REM ARGO GUI Launcher - One-button interface with status lights and log display

REM Run GUI with venv interpreter (avoid system Python)
I:\argo\.venv\Scripts\python.exe I:\argo\gui_launcher.py

REM Keep window open if there's an error
if errorlevel 1 pause
