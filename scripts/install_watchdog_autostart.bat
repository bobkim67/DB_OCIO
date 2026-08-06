@echo off
REM =====================================================================
REM OCIO watchdog autostart installer
REM  - writes ocio_watchdog.vbs into the user's Startup folder (no admin)
REM  - starts the watchdog right now (hidden)
REM  - run once; re-run is harmless (overwrites)
REM =====================================================================
setlocal
set "ROOT=%~dp0.."
for %%i in ("%ROOT%") do set "ROOT=%%~fi"
set "VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ocio_watchdog.vbs"

REM Go through ocio_watchdog_run.cmd so the watchdog's EXIT CODE gets logged
REM when something kills it (see that file for why).
> "%VBS%" echo CreateObject("WScript.Shell").Run "cmd /c ""%ROOT%\scripts\ocio_watchdog_run.cmd""", 0, False

if exist "%VBS%" (
    echo [OK] Startup entry written: %VBS%
) else (
    echo [ERROR] failed to write Startup entry.
    pause
    exit /b 1
)

echo Starting watchdog now (hidden)...
wscript "%VBS%"
echo Done. Watchdog log: %ROOT%\logs\watchdog.log
timeout /t 4 >nul
endlocal
