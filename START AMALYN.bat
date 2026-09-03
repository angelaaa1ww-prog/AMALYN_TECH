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

cd /d "%~dp0"
cd AMALYN_AI

call ..\amalyn_env\Scripts\activate.bat

echo  [ENGINE] Launching AI Engine...
echo  [BROWSER] Opening Dashboard...
echo.

start "" "%~dp0amalyn_env\Scripts\python.exe" launcher.py

echo  AMALYN is running.
echo  Close this window to stop AMALYN.
echo.
pause