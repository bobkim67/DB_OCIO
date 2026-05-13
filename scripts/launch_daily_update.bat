@echo off
title Daily Update :market_research
cd /d "%~dp0.."

REM ====================================================================
REM  Direct daily_update runner. Called from launch_dashboard.bat after
REM  the user explicitly opts in (Y at the prompt). No idempotent guard
REM  here -- the dispatcher decides whether to invoke this script.
REM ====================================================================

echo ====================================
echo  Daily Update RUNNING
echo  python -m market_research.pipeline.daily_update
echo  Estimated 5~10 min, LLM cost ~$0.10
echo  Stop with Ctrl+C
echo ====================================
echo.

"%~dp0..\..\.venv\Scripts\python.exe" -m market_research.pipeline.daily_update
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
