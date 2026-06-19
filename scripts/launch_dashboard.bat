@echo off
setlocal EnableDelayedExpansion
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

REM ----- pre-pick ports so child launchers and browser stay in sync -----
pushd "%~dp0.."
for /f "tokens=1,2" %%A in ('api\.venv\Scripts\python.exe scripts\pick_free_port.py --start 8000 --start 5173 --write .runtime_ports.json --keys api web') do (
    set "OCIO_API_PORT=%%A"
    set "OCIO_WEB_PORT=%%B"
)
popd

if not defined OCIO_API_PORT set "OCIO_API_PORT=8000"
if not defined OCIO_WEB_PORT set "OCIO_WEB_PORT=5173"

echo  FastAPI port : !OCIO_API_PORT!  ^(default 8000^)
echo  Vite port    : !OCIO_WEB_PORT!  ^(default 5173^)
echo.

REM warmup CLI pre-builds disk caches; disable server startup warmup to avoid duplication
set "OCIO_WARMUP_ON_STARTUP=false"

REM ----- launch servers: one Windows Terminal window with tabs if available, else separate windows -----
set "HAVE_WT=0"
where wt >nul 2>nul && set "HAVE_WT=1"

if "!HAVE_WT!"=="1" (
    echo [1-3/5] Starting FastAPI + Vite as Windows Terminal tabs ...
    set WT_ARGS=new-tab --title "FastAPI :!OCIO_API_PORT!" cmd /k "%~dp0launch_fastapi.bat"
    set WT_ARGS=!WT_ARGS! ; new-tab --title "Vite :!OCIO_WEB_PORT!" cmd /k "%~dp0launch_vite.bat"
    if "%RUN_DU%"=="1" (
        echo       + Daily Update tab
        set WT_ARGS=!WT_ARGS! ; new-tab --title "Daily Update" cmd /k "%~dp0launch_daily_update.bat"
    ) else (
        echo       Daily Update SKIPPED ^(declined / timeout^)
    )
    start "" wt !WT_ARGS!
) else (
    echo [1/5] Starting FastAPI ...
    start "FastAPI :!OCIO_API_PORT!" "%~dp0launch_fastapi.bat"
    echo [2/5] Starting Vite ...
    start "Vite :!OCIO_WEB_PORT!" "%~dp0launch_vite.bat"
    if "%RUN_DU%"=="1" (
        echo [3/5] Starting Daily Update ...
        start "Daily Update" "%~dp0launch_daily_update.bat"
    ) else (
        echo [3/5] Daily Update SKIPPED ^(declined / timeout^)
    )
)

echo [4/5] Warming up caches ^(holdings/transactions/Brinson, default params^) ...
echo       progress below; browser opens when warmup completes.
pushd "%~dp0.."
api\.venv\Scripts\python.exe -m api.warmup_cli
popd

echo.
echo [5/5] Opening browser ...
REM child launchers may have shifted to a different free port if the pre-picked
REM one was grabbed by a stale process. Re-read the actual port from runtime json.
pushd "%~dp0.."
for /f "tokens=1" %%P in ('api\.venv\Scripts\python.exe -c "import json; print(json.load(open('.runtime_ports.json'))['web'])" 2^>nul') do set "FINAL_WEB=%%P"
for /f "tokens=1" %%P in ('api\.venv\Scripts\python.exe -c "import json; print(json.load(open('.runtime_ports.json'))['api'])" 2^>nul') do set "FINAL_API=%%P"
popd
if not defined FINAL_WEB set "FINAL_WEB=%OCIO_WEB_PORT%"
if not defined FINAL_API set "FINAL_API=%OCIO_API_PORT%"
start "" "http://127.0.0.1:!FINAL_WEB!"

echo.
echo Done.
echo  - FastAPI window  ^(port !FINAL_API!^)
echo  - Vite window     ^(port !FINAL_WEB!^)
if "%RUN_DU%"=="1" echo  - Daily Update    (running in background)
echo  - Browser opened  http://127.0.0.1:!FINAL_WEB!
echo.
echo This launcher window will close in 3 seconds.
echo Stop servers with Ctrl+C in each window.
timeout /t 3 /nobreak >nul
endlocal
