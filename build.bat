@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  BatteryBar – build script
REM  Run this once on your Windows 11 machine to produce dist\BatteryBar.exe
REM ─────────────────────────────────────────────────────────────────────────────

echo [1/4] Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller

echo [2/4] Building executable (no console window)...
pyinstaller --onefile --noconsole --name BatteryBar battery_tray.py

echo [3/4] Done!
echo.
echo  Executable is at:  dist\BatteryBar.exe
echo.
echo  To auto-start on login:
echo    1. Press Win+R, type: shell:startup
echo    2. Copy (or create a shortcut to) dist\BatteryBar.exe into that folder.
echo.
pause
