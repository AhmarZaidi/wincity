@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  WinCity – build script
REM  Run this once on your Windows 11 machine to produce dist\WinCity.exe
REM  Double-click this file, or run:  cmd /c build.bat
REM ─────────────────────────────────────────────────────────────────────────────

echo [1/3] Installing dependencies...
python -m pip install -r requirements.txt < nul
python -m pip install pyinstaller < nul

echo [2/3] Building executable (no console window)...
python -m PyInstaller --onefile --noconsole --name WinCity main.py < nul

echo [3/3] Done!
echo.
echo  Executable is at:  dist\WinCity.exe
echo.
echo  To auto-start on login:
echo    1. Press Win+R, type: shell:startup
echo    2. Copy (or create a shortcut to) dist\WinCity.exe into that folder.
echo.
pause
