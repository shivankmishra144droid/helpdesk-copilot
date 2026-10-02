@echo off
title Helpdesk Copilot - Stop
setlocal EnableExtensions
cd /d "%~dp0"

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PowerShell was not found.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1" -Stop
pause
exit /b %ERRORLEVEL%
