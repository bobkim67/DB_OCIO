@echo off
title Vite :5173
set "PATH=C:\Program Files\nodejs;%PATH%"
cd /d "%~dp0..\web"
echo ====================================
echo  Vite       http://127.0.0.1:5173
echo  Stop with Ctrl+C
echo ====================================
call node_modules\.bin\vite.cmd --host 127.0.0.1 --port 5173
echo.
echo [server stopped]
pause
