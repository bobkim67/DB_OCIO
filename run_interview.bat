@echo off
chcp 65001 >nul
cd /d "C:\Users\user\Downloads\python\DB_OCIO_Webview"
"C:\Users\user\Downloads\python\.venv\Scripts\python.exe" -m market_research.report.cli build --edit
pause
