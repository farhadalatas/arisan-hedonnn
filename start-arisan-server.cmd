@echo off
setlocal

set "PORT=8081"
set "PYTHON=C:\Users\farha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "ARISAN_PORT=%PORT%"

cd /d "%~dp0"

echo.
echo ========================================
echo   Arisan Hedonnn - Local Server
echo ========================================
echo.
echo Jangan tutup window ini selama acara berjalan.
echo Kalau Windows Firewall muncul, pilih Allow access.
echo.
echo Link lokal di laptop:
echo http://127.0.0.1:%PORT%/
echo.
echo Link WiFi yang bisa dicoba dari HP/device lain:
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /C:"IPv4"') do (
  for /f "tokens=1" %%B in ("%%A") do echo http://%%B:%PORT%/
)
echo.
echo Server mulai...
echo.

"%PYTHON%" "%~dp0arisan-local-server.py"

echo.
echo Server berhenti.
pause
