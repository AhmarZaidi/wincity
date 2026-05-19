@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  WinCity – build script
REM  Run this once on your Windows 11 machine to produce dist\WinCity.exe
REM ─────────────────────────────────────────────────────────────────────────────

echo [1/4] Installing dependencies...
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo [2/4] Building executable (no console window)...
python -m PyInstaller --onefile --noconsole --name WinCity main.py

echo [3/4] Done!
echo.
echo  Executable is at:  dist\WinCity.exe
echo.
echo  To auto-start on login:
echo    1. Press Win+R, type: shell:startup
echo    2. Copy (or create a shortcut to) dist\WinCity.exe into that folder.
echo.
pause
