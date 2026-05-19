@echo off
REM Delegates to build.ps1 — double-clicking this file will run the build.
PowerShell -ExecutionPolicy Bypass -File "%~dp0build.ps1"
pause
