@echo off
chcp 65001 >nul
setlocal
set PYTHONIOENCODING=utf-8

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%\..\..\..") do set "REPO_ROOT=%%~fI"

set "PYTHON_EXE=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] python executable not found: "%PYTHON_EXE%"
    exit /b 1
)

cd /d "%REPO_ROOT%\DB_OCIO_Webview"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "RUN_DATE=%%I"
set "LOG=market_research\output\collect_%RUN_DATE%.log"

echo [%date% %time%] collect start >> "%LOG%"

echo === 1. Daily news collection === >> "%LOG%"
"%PYTHON_EXE%" -c "from market_research.collect.macro_data import load_news_all; load_news_all()" >> "%LOG%" 2>&1

echo === 1b. Macro indicators update === >> "%LOG%"
"%PYTHON_EXE%" -c "from market_research.collect.macro_data import run; run()" >> "%LOG%" 2>&1

echo === 2. Blog incremental update === >> "%LOG%"
"%PYTHON_EXE%" -m market_research.collect.naver_blog >> "%LOG%" 2>&1

echo === 3. Monthly digest rebuild === >> "%LOG%"
"%PYTHON_EXE%" -c "from market_research.pipeline.digest_builder import build_monthly_digest; from datetime import date; t=date.today(); build_monthly_digest(t.year, t.month)" >> "%LOG%" 2>&1

echo === 4. Vector index rebuild === >> "%LOG%"
"%PYTHON_EXE%" -c "from market_research.analyze.news_vectordb import build_index; from datetime import date; t=date.today(); build_index(f'{t.year}-{t.month:02d}')" >> "%LOG%" 2>&1

echo === 5. Report cache rebuild === >> "%LOG%"
"%PYTHON_EXE%" -c "from market_research.pipeline.report_cache_builder import build_report_cache; from datetime import date; t=date.today(); build_report_cache(t.year, t.month)" >> "%LOG%" 2>&1

echo [%date% %time%] collect end >> "%LOG%"
endlocal
