@echo off
setlocal
set "PORT=8081"
set "URL=http://127.0.0.1:%PORT%/"
cd /d "%~dp0"

netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if errorlevel 1 (
  start "Arisan Hedonnn Server" /min "%~dp0start-arisan-server.cmd"
)

set /a ATTEMPT=0
:WAIT_SERVER
set /a ATTEMPT+=1
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing '%URL%' -TimeoutSec 1; if($r.StatusCode -eq 200){exit 0} } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 goto OPEN_CHROME
if %ATTEMPT% GEQ 15 goto SERVER_FAILED
powershell -NoProfile -Command "Start-Sleep -Seconds 1" >nul 2>&1
goto WAIT_SERVER

:OPEN_CHROME
set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not defined CHROME goto CHROME_MISSING
start "" "%CHROME%" "%URL%"
exit /b 0

:SERVER_FAILED
echo Server Arisan belum berhasil aktif di port %PORT%.
echo Coba klik STOP ARISAN, lalu jalankan START ARISAN lagi.
pause
exit /b 1

:CHROME_MISSING
echo Google Chrome tidak ditemukan.
echo Buka alamat ini secara manual: %URL%
pause
exit /b 1
