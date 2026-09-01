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

REM ====================================================================
REM  wiki weekly batch commit -- only after a CLEAN run (rc=0).
REM  A failed run can leave half-written wiki artifacts; committing those
REM  is exactly what the batch policy exists to prevent.
REM  --min-age-days 7 keeps it a WEEKLY batch even if daily_update runs
REM  every day. Manual runs (no flag) commit regardless of age.
REM  Never fatal: a git failure must not mask the daily_update result.
REM ====================================================================
if %RC% equ 0 (
    echo.
    echo [wiki] weekly batch commit check ...
    "%~dp0..\..\.venv\Scripts\python.exe" tools\weekly_wiki_commit.py --min-age-days 7
    if errorlevel 1 echo   [WARN] wiki commit skipped - see message above
)

echo.
echo ====================================
if %RC% equ 0 (
    echo  Daily Update FINISHED OK
) else (
    echo  Daily Update FAILED  rc=%RC%
)
echo ====================================
pause
