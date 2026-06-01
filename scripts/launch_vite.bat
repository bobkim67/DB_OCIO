@echo off
setlocal EnableDelayedExpansion
set "PATH=C:\Program Files\nodejs;%PATH%"
cd /d "%~dp0.."

REM ----- pick free port — env value is a starting point only, real bind-check follows -----
if defined OCIO_WEB_PORT (
    set "WEB_START=%OCIO_WEB_PORT%"
) else (
    set "WEB_START=5173"
)
for /f "tokens=1" %%P in ('api\.venv\Scripts\python.exe scripts\pick_free_port.py --start !WEB_START! --write .runtime_ports.json --keys web --merge') do set "WEB_PORT=%%P"

if not defined WEB_PORT (
    echo [launch_vite] failed to determine port. falling back to 5173.
    set "WEB_PORT=5173"
)

title Vite :!WEB_PORT!
cd web
echo ====================================
echo  Vite       http://127.0.0.1:!WEB_PORT!
echo  Stop with Ctrl+C
echo ====================================
call node_modules\.bin\vite.cmd --host 127.0.0.1 --port !WEB_PORT!
echo.
echo [server stopped]
pause
endlocal
