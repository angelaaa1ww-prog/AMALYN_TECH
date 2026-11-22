@echo off
setlocal
title AMALYN TECH
cd /d "%~dp0"

echo =============================================
echo   AMALYN TECH - Starting
echo =============================================

for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000"') do (
    taskkill /PID %%p /F >nul 2>&1
)

set "PYTHON=%~dp0amalyn_env\Scripts\python.exe"
if not exist "%PYTHON%" (
    where py >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python 3.11 was not found.
        pause
        exit /b 1
    )
    set "PYTHON=py -3.11"
)

start "AMALYN Server" /D "%~dp0AMALYN_AI" "%PYTHON%" api.py

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ready=$false; for($i=0;$i-lt60;$i++){try{$r=Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 2;if($r.status){$ready=$true;break}}catch{Start-Sleep -Milliseconds 500}}; if($ready){Start-Process 'http://127.0.0.1:8000/'}else{Write-Error 'AMALYN did not become ready'}"

if errorlevel 1 (
    echo [ERROR] AMALYN did not start within 60 seconds.
    echo Check the AMALYN Server window for the Python error.
    pause
    exit /b 1
)

echo [OK] AMALYN is ready.
exit /b 0
