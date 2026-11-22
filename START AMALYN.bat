@echo off
title AMALYN TECH
color 0A
echo.
echo  =============================================
echo    AMALYN TECH - AI Audio Intelligence
echo  =============================================
echo.
echo  Starting AMALYN...
echo.

cd /d "%~dp0\AMALYN_AI"

for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000"') do (
    taskkill /PID %%p /F >nul 2>&1
)

set "PYTHON=%~dp0\amalyn_env\Scripts\python.exe"
if not exist "%PYTHON%" (
    py -3.11 api.py
) else (
    start "" /D "%~dp0\AMALYN_AI" "%PYTHON%" api.py
)

set "READY="
for /l %%i in (1,1,60) do (
    if not defined READY (
        curl -s -f http://127.0.0.1:8000/health >nul 2>&1
        if not errorlevel 1 (
            set "READY=1"
            start "" http://127.0.0.1:8000/
            echo  [OK] AMALYN is ready. Browser opened.
        ) else (
            timeout /t 1 /nobreak >nul
        )
    )
)

if not defined READY (
    echo  [ERROR] AMALYN did not start within 60 seconds.
)
pause