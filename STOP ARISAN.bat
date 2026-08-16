@echo off
setlocal
set "PID_FILE=%~dp0arisan-server.pid"
set "PORT=8081"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pidFile='%PID_FILE%'; $port=%PORT%; $stopped=$false; " ^
  "if(Test-Path -LiteralPath $pidFile){ try { $serverPid=[int](Get-Content -LiteralPath $pidFile -Raw); $p=Get-Process -Id $serverPid -ErrorAction Stop; if($p.ProcessName -match 'python'){ Stop-Process -Id $serverPid -Force; $stopped=$true } } catch {} }; " ^
  "if(-not $stopped){ $lines=netstat -ano | Select-String (':' + $port + '\s+.*LISTENING\s+(\d+)'); foreach($line in $lines){ if($line.Matches.Count){ $candidate=[int]$line.Matches[0].Groups[1].Value; try { $cmd=(Get-CimInstance Win32_Process -Filter ('ProcessId=' + $candidate) -ErrorAction Stop).CommandLine; if($cmd -like '*arisan-local-server.py*'){ Stop-Process -Id $candidate -Force; $stopped=$true } } catch {} } } }; " ^
  "if(Test-Path -LiteralPath $pidFile){ Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue }; " ^
  "if($stopped){ Write-Host 'Server Arisan berhasil dihentikan.' -ForegroundColor Green; exit 0 } else { Write-Host 'Server Arisan tidak sedang berjalan.' -ForegroundColor Yellow; exit 0 }"

if not defined ARISAN_NO_PAUSE powershell -NoProfile -Command "Start-Sleep -Seconds 2" >nul 2>&1
exit /b 0
