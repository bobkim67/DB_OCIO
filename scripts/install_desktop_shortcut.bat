@echo off
title Install Desktop Shortcut

echo Installing "DB OCIO Dashboard" shortcut on Desktop ...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_install_shortcut.ps1"

echo.
echo Done. Double-click "DB OCIO Dashboard" on Desktop to start.
pause
