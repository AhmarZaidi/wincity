@echo off
setlocal EnableDelayedExpansion

:: -------------------------------------------------------------
:: Detect Python executable
:: -------------------------------------------------------------
set "PYTHON_EXE="
set "PYTHONW_EXE="

if exist "%USERPROFILE%\.pyenv\pyenv-win\versions\3.14.5\python.exe" (
    set "PYTHON_EXE=%USERPROFILE%\.pyenv\pyenv-win\versions\3.14.5\python.exe"
    set "PYTHONW_EXE=%USERPROFILE%\.pyenv\pyenv-win\versions\3.14.5\pythonw.exe"
) else if exist "%USERPROFILE%\.pyenv\pyenv-win\versions\3.10.11\python.exe" (
    set "PYTHON_EXE=%USERPROFILE%\.pyenv\pyenv-win\versions\3.10.11\python.exe"
    set "PYTHONW_EXE=%USERPROFILE%\.pyenv\pyenv-win\versions\3.10.11\pythonw.exe"
) else (
    set "PYTHON_EXE=python"
    set "PYTHONW_EXE=pythonw"
)

if "%1"=="python" goto run_python
if "%1"=="py"     goto run_python
if "%1"=="rust"   goto run_rust
if "%1"=="rs"     goto run_rust
if "%1"=="bench"  goto run_bench
if "%1"=="setup"  goto run_setup

:menu
cls
echo =======================================================
echo                     WinCity Hub
echo =======================================================
echo.
echo   [1] Run WinCity (Rust - Native High Performance)
echo   [2] Run WinCity (Python - Tkinter Version)
echo   [3] Build ^& Run Benchmarks (Python vs Rust)
echo   [4] Configure Windows Auto-Start
echo   [5] Exit
echo.
echo =======================================================
set /p choice="Enter choice [1-5]: "

if "%choice%"=="1" goto run_rust
if "%choice%"=="2" goto run_python
if "%choice%"=="3" goto run_bench
if "%choice%"=="4" goto run_setup
if "%choice%"=="5" exit /b 0
goto menu

:run_rust
echo [*] Starting WinCity (Rust Native)...
if not exist "%~dp0rust\target\release\wincity.exe" (
    echo [*] Building Rust release binary first...
    cd /d "%~dp0rust"
    cargo build --release
    cd /d "%~dp0"
)
start "" /d "%~dp0" "%~dp0rust\target\release\wincity.exe"
exit /b 0

:run_python
echo [*] Starting WinCity (Python)...
cd /d "%~dp0python"
start "" "!PYTHONW_EXE!" "main.py"
cd /d "%~dp0"
exit /b 0

:run_bench
echo [*] Running resource benchmark comparison...
"%PYTHON_EXE%" "%~dp0scripts\benchmark.py" %*
pause
goto menu

:run_setup
"%PYTHON_EXE%" "%~dp0scripts\setup_autostart.py"
pause
goto menu

