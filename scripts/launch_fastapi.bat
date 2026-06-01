@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

REM ----- pick free port — env value is a starting point only, real bind-check follows -----
if defined OCIO_API_PORT (
    set "API_START=%OCIO_API_PORT%"
) else (
    set "API_START=8000"
)
for /f "tokens=1" %%P in ('api\.venv\Scripts\python.exe scripts\pick_free_port.py --start !API_START! --write .runtime_ports.json --keys api --merge') do set "API_PORT=%%P"

if not defined API_PORT (
    echo [launch_fastapi] failed to determine port. falling back to 8000.
    set "API_PORT=8000"
)

title FastAPI :!API_PORT!
echo ====================================
echo  FastAPI    http://127.0.0.1:!API_PORT!
echo  Stop with Ctrl+C
echo ====================================
api\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port !API_PORT! --reload
echo.
echo [server stopped]
pause
endlocal
