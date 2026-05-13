@echo off
title DB OCIO Dashboard Launcher

echo ====================================
echo  DB OCIO Dashboard Launcher
echo ====================================
echo.

REM ----- Last daily_update status -----
set "RM_FILE=%~dp0..\market_research\data\regime_memory.json"
set "LAST_STATUS=(never)"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "if (Test-Path '%RM_FILE%') { $d = (Get-Item '%RM_FILE%').LastWriteTime.Date; $today = (Get-Date).Date; $days = ($today - $d).Days; if ($days -eq 0) { 'Today (' + $d.ToString('yyyy-MM-dd') + ')' } elseif ($days -eq 1) { 'Yesterday (' + $d.ToString('yyyy-MM-dd') + ')' } else { ('{0} days ago ({1})' -f $days, $d.ToString('yyyy-MM-dd')) } } else { '(never)' }" > "%TEMP%\du_status.txt"
set /p LAST_STATUS=<"%TEMP%\du_status.txt"
del "%TEMP%\du_status.txt" 2>nul

echo  Last daily_update : %LAST_STATUS%
echo  Cost / time       : ~$0.10 / 5~10 min  (Haiku + Sonnet)
echo.
choice /C YN /T 10 /D N /M "Run daily_update now? Default N in 10s"
set "RUN_DU=%errorlevel%"
echo.

echo [1/4] Starting FastAPI ...
start "FastAPI :8000" "%~dp0launch_fastapi.bat"

echo [2/4] Starting Vite ...
start "Vite :5173" "%~dp0launch_vite.bat"

if "%RUN_DU%"=="1" (
    echo [3/4] Starting Daily Update ...
    start "Daily Update" "%~dp0launch_daily_update.bat"
) else (
    echo [3/4] Daily Update SKIPPED ^(declined / timeout^)
)

echo [4/4] Opening browser in 5 seconds ...
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:5173"

echo.
echo Done.
echo  - FastAPI window  (port 8000)
echo  - Vite window     (port 5173)
if "%RUN_DU%"=="1" echo  - Daily Update    (running in background)
echo  - Browser opened  http://127.0.0.1:5173
echo.
echo This launcher window will close in 3 seconds.
echo Stop servers with Ctrl+C in each window.
timeout /t 3 /nobreak >nul
