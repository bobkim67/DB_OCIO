@echo off
REM =====================================================================
REM Stop OCIO dashboard COMPLETELY: watchdog first, then the server.
REM (With the watchdog running, just closing the server window is not
REM  enough - it restarts within ~15s. Use this to really stop it.)
REM =====================================================================
echo Stopping watchdog...
REM Tell ocio_watchdog_run.cmd this stop is INTENTIONAL so its restart loop does
REM not undo it. Must be written BEFORE the kill - the wrapper reads the flag the
REM moment its child dies. (Without this the wrapper would revive the watchdog in
REM 10s and "stop everything" would silently stop working.)
if not exist "%~dp0..\.cache" mkdir "%~dp0..\.cache"
>"%~dp0..\.cache\watchdog_stop.flag" echo stop requested by stop_ocio_server.bat

REM leave a trace in logs\watchdog.log (this stop is intentional, not a crash)
REM and clear the heartbeat so the next start does not report an unclean end.
powershell -NoProfile -Command "$r='%~dp0..'; Add-Content -Path (Join-Path $r 'logs\watchdog.log') -Encoding UTF8 -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' | stop_ocio_server.bat - watchdog + server stopped by user'); Remove-Item (Join-Path $r 'logs\watchdog.heartbeat') -Force -ErrorAction SilentlyContinue"
REM $PID exclusion: this very command line contains 'ocio_watchdog', so without it
REM the killer can kill itself first and leave the real watchdog running.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | Where-Object { $_.CommandLine -match 'ocio_watchdog\.ps1' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo Stopping server on port 8020...
for /f "delims=" %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 8020 -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1"') do taskkill /F /PID %%p >nul 2>&1

echo Done. (autostart entry remains - watchdog returns at next logon;
echo  run install_watchdog_autostart.bat to re-arm now, or delete
echo  ocio_watchdog.vbs from shell:startup to remove autostart.)
pause
