@echo off
REM WinCity Setup — double-click this file to create shortcuts and configure Windows startup
python "%~dp0setup_shortcuts.py"
if %ERRORLEVEL% NEQ 0 (
    py "%~dp0setup_shortcuts.py"
)
pause
