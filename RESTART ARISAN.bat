@echo off
setlocal
cd /d "%~dp0"
set "ARISAN_NO_PAUSE=1"
call "%~dp0STOP ARISAN.bat"
powershell -NoProfile -Command "Start-Sleep -Seconds 2" >nul 2>&1
call "%~dp0START ARISAN.bat"
