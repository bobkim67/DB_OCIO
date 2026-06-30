@echo off
title Daily Update :market_research
cd /d "%~dp0.."

REM ====================================================================
REM  Direct daily_update runner. Called from launch_dashboard.bat after
REM  the user explicitly opts in (Y at the prompt). No idempotent guard
REM  here -- the dispatcher decides whether to invoke this script.
REM ====================================================================

REM PDF collection: dispatcher sets OCIO_NAVER_PDF (Y/N). N -> skip PDF download.
set "PDF_FLAG="
if /I "%OCIO_NAVER_PDF%"=="N" set "PDF_FLAG=--naver-no-pdf"
set "PDF_MSG=included"
if /I "%OCIO_NAVER_PDF%"=="N" set "PDF_MSG=skipped"

echo ====================================
echo  Daily Update RUNNING
echo  python -m market_research.pipeline.daily_update %PDF_FLAG%
echo  naver_research PDF : %PDF_MSG%
echo  Estimated 5~10 min, LLM cost ~$0.10
echo  Stop with Ctrl+C
echo ====================================
echo.

"%~dp0..\..\.venv\Scripts\python.exe" -m market_research.pipeline.daily_update %PDF_FLAG%
set RC=%errorlevel%

echo.
echo ====================================
if %RC% equ 0 (
    echo  Daily Update FINISHED OK
) else (
    echo  Daily Update FAILED  rc=%RC%
)
echo ====================================
pause
