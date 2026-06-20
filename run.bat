@echo off
title Dream OS Agent Launcher
cd /d "%~dp0"
echo Starting Dream OS Agent overlay widget...
.venv\Scripts\python.exe main.py
if %errorlevel% neq 0 (
    echo.
    echo [Error] Program exited with error code %errorlevel%.
    echo Check crash_log.txt for more details.
    pause
)
