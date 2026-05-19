Write-Host "[1/3] Installing dependencies..."
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed"; exit 1 }

python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { Write-Error "pip install pyinstaller failed"; exit 1 }

Write-Host "[2/3] Building executable (no console window)..."
python -m PyInstaller --onefile --noconsole --icon assets\appicon.ico --name WinCity main.py
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed"; exit 1 }

Write-Host ""
Write-Host "[3/3] Done!"
Write-Host "  Executable at: dist\WinCity.exe"
Write-Host ""
Write-Host "  To auto-start on login:"
Write-Host "    1. Press Win+R, type: shell:startup"
Write-Host "    2. Copy (or create a shortcut to) dist\WinCity.exe into that folder."
