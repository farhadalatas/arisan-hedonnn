@echo off
setlocal
set "PORT=8081"
set "APP=arisan-hedonnn-v4.html"
set "URL=http://127.0.0.1:%PORT%/%APP%"
cd /d "%~dp0"
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if errorlevel 1 start "Arisan Hedonnn Server" /min "%~dp0start-arisan-server.cmd"
timeout /t 2 /nobreak >nul
set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not defined CHROME (
  echo Google Chrome tidak ditemukan. Buka manual: %URL%
  pause
  exit /b 1
)
start "" "%CHROME%" "%URL%"
endlocal
