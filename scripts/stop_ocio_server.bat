@echo off
REM =====================================================================
REM Stop the OCIO dashboard server (port 8020).
REM
REM 2026-08-11: the watchdog was removed, so this is now a plain stop -
REM nothing restarts the server afterwards. Start it again with
REM scripts\launch_dashboard.bat.
REM =====================================================================
echo Stopping server on port 8020...
for /f "delims=" %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 8020 -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1"') do taskkill /F /PID %%p >nul 2>&1
echo Done. Restart with scripts\launch_dashboard.bat
pause
