@echo off
title AMALYN TECH AI — Server
color 0B
echo.
echo  ================================================
echo   AMALYN TECH AI — Starting Server
echo  ================================================
echo.

cd /d "%~dp0"

:: Prefer the bundled environment so the declared dependencies are used.
set "PYTHON=%~dp0..\amalyn_env\Scripts\python.exe"
if not exist "%PYTHON%" (
    py -3.11 --version >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] Python 3.11 not found and the bundled environment is missing.
        pause
        exit /b 1
    )
    set "PYTHON="
)

:: Kill any old instance on port 8000
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000"') do (
    taskkill /PID %%p /F >nul 2>&1
)

echo  [OK] Starting AMALYN API on http://localhost:8000
echo  [OK] Open your browser to: http://localhost:8000
echo.
echo  Press Ctrl+C to stop the server.
echo.

:: Start the server
if defined PYTHON (
    "%PYTHON%" api.py
) else (
    py -3.11 api.py
)

pause
