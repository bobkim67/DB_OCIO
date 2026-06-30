@echo off
title DB OCIO Dashboard (LAN :8020)
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

REM ===== fixed LAN port =====
set "PORT=8020"

echo ====================================
echo  DB OCIO Dashboard Launcher (LAN :%PORT%)
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

REM ----- PDF collection prompt (only when daily_update will run) -----
set "OCIO_NAVER_PDF=Y"
if "%RUN_DU%"=="1" (
    choice /C YN /T 10 /D Y /M "  Collect naver_research PDFs too ^(slower ~5-6min^)? Default Y in 10s"
    if !errorlevel! equ 2 set "OCIO_NAVER_PDF=N"
    echo       naver PDF collection : !OCIO_NAVER_PDF!
    echo.
)

REM ===== restart: stop ONLY the server holding %PORT% (other ports / apps untouched) =====
echo Restarting LAN server on port %PORT% ^(other ports left running^) ...
for /f "delims=" %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1"') do taskkill /F /PID %%p >nul 2>&1
timeout /t 1 /nobreak >nul

REM ===== [1/3] build React SPA (web\dist) so FastAPI serves it on the same port =====
echo [1/3] Building frontend (web\dist) ...
pushd web
call npm run build
popd
if not exist "web\dist\index.html" (
  echo [ERROR] build failed - web\dist\index.html not found.
  pause
  exit /b 1
)

REM ===== [2/3] daily_update (optional, separate window) =====
if "%RUN_DU%"=="1" (
    echo [2/3] Starting Daily Update in a separate window ...
    start "Daily Update" "%~dp0launch_daily_update.bat"
) else (
    echo [2/3] Daily Update SKIPPED ^(declined / timeout^)
)

REM ===== current LAN IP (192.168 / 10 / 172) =====
set "IP="
for /f "delims=" %%i in ('powershell -NoProfile -Command "(@(Get-NetIPAddress -AddressFamily IPv4).IPAddress -match '^(192\.168|10|172)\.')[0]"') do set "IP=%%i"
if not defined IP set "IP=localhost"

echo ============================================================
echo    DB OCIO Dashboard - serving (caches warm up in background)
echo ------------------------------------------------------------
echo    Local : http://localhost:%PORT%/
echo    LAN   : http://%IP%:%PORT%/      (open this on in-house PCs)
echo    Close this window to STOP the server.
echo ============================================================
echo.

REM open local browser shortly after the server binds
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 6; Start-Process 'http://localhost:%PORT%/'"

echo [3/3] Starting server (host 0.0.0.0:%PORT%) ...
REM server warms its caches in the background on startup (OCIO_WARMUP_ON_STARTUP default on)
api\.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port %PORT%

echo.
echo Server stopped. Press any key to close.
pause >nul
endlocal
