@echo off
REM =====================================================================
REM  OCIO watchdog launcher that CAPTURES THE EXIT CODE.
REM
REM  Why: the watchdog has been killed from outside three times, always
REM  just after midnight (2026-07-29 00:23 / 08-04 00:58 / 08-07 01:18).
REM  Resource metrics in the heartbeat ruled out a leak, but they cannot
REM  tell us WHO killed it. Process-termination auditing (4689), Sysmon and
REM  ETW all need admin rights, which this account does not have.
REM
REM  The exit code is the one clue we can still get without admin:
REM     -1           0xFFFFFFFF  .NET Process.Kill / PowerShell Stop-Process -Force
REM                              (measured 2026-08-07 with a controlled kill)
REM     1            taskkill /F default
REM     -1073741510  0xC000013A  Ctrl+C / console close
REM     1073807364   0x40010004  debugger terminate
REM     0            clean exit  -> the script left its loop, NOT a kill
REM     other        killer-specific -> narrows down the culprit
REM
REM  cmd.exe is a different image from powershell.exe, so it may survive
REM  whatever targets the script host. If it dies too we lose nothing.
REM =====================================================================
setlocal
set "ROOT=%~dp0.."
for %%i in ("%ROOT%") do set "ROOT=%%~fi"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\ocio_watchdog.ps1"
set "RC=%ERRORLEVEL%"

REM ISO 8601 'sortable' has no space, so a single for/f token is enough
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format s"') do set "TS=%%t"
>>"%ROOT%\logs\watchdog.log" echo %TS% ^| watchdog process exited rc=%RC% (code meanings: see scripts\ocio_watchdog_run.cmd)
endlocal
