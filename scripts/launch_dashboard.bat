@echo off
title DB OCIO Dashboard Launcher

echo ====================================
echo  DB OCIO Dashboard Launcher
echo ====================================
echo.
echo [1/3] Starting FastAPI ...
start "FastAPI :8000" "%~dp0launch_fastapi.bat"

echo [2/3] Starting Vite ...
start "Vite :5173" "%~dp0launch_vite.bat"

echo [3/3] Opening browser in 5 seconds ...
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:5173"

echo.
echo Done.
echo  - FastAPI window  (port 8000)
echo  - Vite window     (port 5173)
echo  - Browser opened  http://127.0.0.1:5173
echo.
echo This launcher window will close in 3 seconds.
echo Stop servers with Ctrl+C in each window.
timeout /t 3 /nobreak >nul
