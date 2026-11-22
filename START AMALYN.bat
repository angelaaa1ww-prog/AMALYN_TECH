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
    where py >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] Python 3.11 was not found.
        pause
        exit /b 1
    )
    echo  [INFO] Using system python launcher.
    py -3.11 api.py
) else (
    "%PYTHON%" api.py
)

powershell -NoProfile -Command "$ready=$false; for($i=0;$i-lt60;$i++){try{$response=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2;if($response.status){$ready=$true;break}}catch{Start-Sleep -Milliseconds 500}}; if($ready){Start-Process 'http://127.0.0.1:8000/'; exit 0}; exit 1"
if errorlevel 1 (
    echo  [ERROR] AMALYN did not start within 60 seconds.
    echo  Close this window, check for Python errors, then run START AMALYN again.
) else (
    echo  [OK] AMALYN is ready. Browser opened.
)
pause
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
    where py >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] Python 3.11 was not found.
        pause
        exit /b 1
    )
    start "" /D "%~dp0\AMALYN_AI" py -3.11 api.py
) else (
    start "" /D "%~dp0\AMALYN_AI" "%PYTHON%" api.py
)

powershell -NoProfile -Command "$ready=$false; for($i=0;$i-lt60;$i++){try{$response=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2;if($response.status){$ready=$true;break}}catch{Start-Sleep -Milliseconds 500}}; if($ready){Start-Process 'http://127.0.0.1:8000/'; exit 0}; exit 1"
if errorlevel 1 (
    echo  [ERROR] AMALYN did not start within 60 seconds.
    echo  Close this window, check for Python errors, then run START AMALYN again.
) else (
    echo  [OK] AMALYN is ready. Browser opened.
)
pause