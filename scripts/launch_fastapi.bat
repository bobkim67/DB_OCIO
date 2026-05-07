@echo off
title FastAPI :8000
cd /d "%~dp0.."
echo ====================================
echo  FastAPI    http://127.0.0.1:8000
echo  Stop with Ctrl+C
echo ====================================
api\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
echo.
echo [server stopped]
pause
