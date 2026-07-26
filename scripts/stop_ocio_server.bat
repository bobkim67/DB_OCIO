@echo off
REM =====================================================================
REM Stop OCIO dashboard COMPLETELY: watchdog first, then the server.
REM (With the watchdog running, just closing the server window is not
REM  enough - it restarts within ~15s. Use this to really stop it.)
REM =====================================================================
echo Stopping watchdog...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | Where-Object { $_.CommandLine -match 'ocio_watchdog' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo Stopping server on port 8020...
for /f "delims=" %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 8020 -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1"') do taskkill /F /PID %%p >nul 2>&1

echo Done. (autostart entry remains - watchdog returns at next logon;
echo  run install_watchdog_autostart.bat to re-arm now, or delete
echo  ocio_watchdog.vbs from shell:startup to remove autostart.)
pause
