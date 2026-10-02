@echo off
title Helpdesk Copilot
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo  Helpdesk Copilot
echo  -----------
echo  First launch on a new PC may install Python, Node.js, and dependencies.
echo  Internet is required. This can take 10-20 minutes. Please wait.
echo.

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PowerShell was not found.
    echo This launcher requires Windows PowerShell.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo The launcher exited with error code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
