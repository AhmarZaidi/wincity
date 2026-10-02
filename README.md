# WinCity

<p align="center">
  <img src="./assets/banner.png" alt="WinCity Banner" width="100%">
</p>

| Dark Mode | Light Mode |
|------------|------------|
| <img width="400" height="700" alt="image" src="https://github.com/user-attachments/assets/3ec8d9f7-f468-4386-b550-a1dac6c667f0" /> | <img width="400" height="700" alt="image" src="https://github.com/user-attachments/assets/53832fc3-fa15-4761-a5e4-2b87683b7b58" /> |


## Features

- **Left-click** the widget to toggle between time and percentage display.
- **Hover** to open a popup: status, health, rate, cycle count, temperature, and a scrolling history graph.
- **Right-click → Quit** to exit.
- Auto-hides when a fullscreen window is active or the taskbar is hidden.

| State | Example |
|---|---|
| Discharging (normal) | <img width="50" height="25" alt="image" src="https://github.com/user-attachments/assets/5bdf3f13-4abb-47ee-a9d1-301c0de33661" /> |
| Discharging (low) | <img width="50" height="25" alt="image" src="https://github.com/user-attachments/assets/a31b90cf-61ac-447b-bb35-39e932108e08" /> |
| Battery saver | <img width="50" height="25" alt="image" src="https://github.com/user-attachments/assets/97cff425-f577-439e-ad83-c6c8ddc1164c" /> |
| Charging | <img width="50" height="25" alt="image" src="https://github.com/user-attachments/assets/5afb565f-c966-4584-9ce0-83cfe4fef9ad" /> |

---

## Project structure

## Project structure

```
wincity/
├── app/
│   ├── __init__.py
│   ├── config.py          constants, colors/rows globals, load/save config & state
│   ├── system.py          Win32 helpers (DPI, taskbar, dark mode, power mode)
│   ├── startup.py         Windows shortcut & auto-start manager (.lnk, shell:startup)
│   ├── battery.py         IOCTL queries, battery wattage & health telemetry
│   ├── render.py          battery icon renderer
│   ├── popup.py           hover popup with history graph, settings & process monitor
│   └── widget.py          main tkinter taskbar widget with render cache
├── assets/
│   ├── appicon.ico        application icon
│   └── banner.png         README banner image
├── data/
│   ├── config.json        user-editable settings & colors
│   └── state.json         runtime state (history, elapsed time) - gitignored
├── dist/
│   └── WinCity.exe        built executable (optional)
├── setup_shortcuts.bat    1-click setup → creates WinCity.lnk & configures Windows auto-start
├── setup_shortcuts.py     Python shortcut and auto-start installer
├── wincity.pyw            silent GUI launcher (runs via pythonw)
├── start.vbs              silent VBScript launcher (0 console window)
├── start.bat              batch launcher
├── build.bat              double-click shortcut → runs build.ps1
├── build.ps1              builds dist\WinCity.exe via PyInstaller
├── main.py                ← entry point
├── README.md              this file
└── requirements.txt       Python dependencies
```

---

## Quick start (No SmartScreen Issues)

Pre-requisite: Go to Settings (Win + I) > System > Power & Battery > Turn on Battery Percentage.

### 1. Install dependencies:
```powershell
pip install -r requirements.txt
```

### 2. Set up Double-Click Icon & Windows Startup:
Double-click **`setup_shortcuts.bat`** (or run `python setup_shortcuts.py`).

This will:
- Create **`WinCity.lnk`** directly in the project folder with the custom WinCity icon.
- Create a **Desktop shortcut** (optional).
- Add **WinCity to Windows Startup** (`shell:startup`) so it automatically starts silently in the background when your PC boots.
- **No SmartScreen warnings** because it runs through Python's standard `pythonw.exe`.

### 3. Launching WinCity:
- **Double-click `WinCity.lnk`** (with the custom icon) or **`wincity.pyw`** or **`start.vbs`**.
- It runs 100% silently in the background without any flashing console window.

---

## Auto-Start on Windows Login

You can manage auto-starting on Windows boot at any time:
- **Option 1 (In-App Menu):** Right-click the taskbar battery widget → check/uncheck **"Start with Windows"**.
- **Option 2 (In-App Settings):** Hover over widget → Settings (gear icon) → toggle **"Start with Windows"**.
- **Option 3 (Setup Script):** Double-click `setup_shortcuts.bat`.

---

## Battery & Power Optimizations

WinCity is engineered for minimal battery consumption:
- **Render Caching:** When battery state is unchanged, Pillow 8x supersampling and canvas redrawing are completely skipped (0% idle CPU).
- **No Periodic PowerShell Spawning:** Removed all background `powershell.exe` / CIM subprocess polling that previously spiked CPU and drained battery.
- **Idle Timer Gating:** Telemetry and live popup refresh loops are suspended whenever the hover popup is closed.
- **Lazy Hardware IOCTLs:** Heavy device interface enumeration and static capacity queries are cached and only queried when required.
- **Single-Instance Enforcement:** Uses a Win32 mutex to prevent duplicate running instances.

---

## Configuration

Edit `data/config.json` (or use the in-app Settings UI) to customise the widget. Changes are picked up automatically without restarting.

Key settings:
- `rows`: control which info rows appear in the popup and in what order (`"visible": false` to hide)
- `colors`: per-theme hex colors for dark, light, graph, and widget fill
- `LOW_PCT`: percentage threshold for the red low-battery indicator
- `OFFSET_FROM_RIGHT`: widget position from the right edge of the taskbar
- `VISIBILITY_POLL_MS`: taskbar / fullscreen window detection frequency (default: 1000ms)

---

## Troubleshooting

If facing issues like incorrect values at start, or getting stuck, delete the `data/config.json` file. A fresh one will be generated automatically.

To report bugs or suggestions, visit [Issues](https://github.com/AhmarZaidi/wincity/issues).

## Uninstall

Right-click the widget → **Quit**, uncheck **"Start with Windows"** (or delete the shortcut in `shell:startup`), then delete the project folder.

