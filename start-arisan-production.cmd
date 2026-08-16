@echo off
setlocal
cd /d "%~dp0"

if not defined ARISAN_ALLOWED_HOSTS (
  echo ERROR: ARISAN_ALLOWED_HOSTS belum diatur ke domain production.
  pause
  exit /b 1
)

set "ARISAN_ENV=production"
set "ARISAN_HOST=127.0.0.1"
set "ARISAN_SECURE_COOKIE=1"
if not defined ARISAN_PORT set "ARISAN_PORT=8081"

where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0arisan-local-server.py"
  exit /b %errorlevel%
)

python "%~dp0arisan-local-server.py"
