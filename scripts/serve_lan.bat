@echo off
title DB OCIO Dashboard (LAN)
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

REM ===== port (override: set OCIO_LAN_PORT=8000) =====
if defined OCIO_LAN_PORT ( set "PORT=%OCIO_LAN_PORT%" ) else ( set "PORT=8000" )

REM ===== stop any server already holding this port =====
echo Stopping existing server on port %PORT% (if any)...
for /f "delims=" %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1"') do taskkill /F /PID %%p >nul 2>&1
timeout /t 1 /nobreak >nul

REM ===== build React SPA (web\dist) so FastAPI can serve it =====
echo [1/2] Building frontend (web\dist) ...
pushd web
call npm run build
popd
if not exist "web\dist\index.html" (
  echo [ERROR] build failed - web\dist\index.html not found.
  pause
  exit /b 1
)

REM ===== current LAN IP (192.168 / 10 / 172) =====
set "IP="
for /f "delims=" %%i in ('powershell -NoProfile -Command "(@(Get-NetIPAddress -AddressFamily IPv4).IPAddress -match '^(192\.168|10|172)\.')[0]"') do set "IP=%%i"
if not defined IP set "IP=localhost"

echo ============================================================
echo    DB OCIO Dashboard - LAN server
echo ------------------------------------------------------------
echo    Local : http://localhost:%PORT%/
echo    LAN   : http://%IP%:%PORT%/     (open this on in-house PCs)
echo    Close this window to STOP the server.
echo ============================================================
echo.

REM ===== open local browser after server warms up =====
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 6; Start-Process 'http://localhost:%PORT%/'"

echo [2/2] Starting server (host 0.0.0.0:%PORT%) ...
api\.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port %PORT%

echo.
echo Server stopped. Press any key to close.
pause >nul
endlocal
