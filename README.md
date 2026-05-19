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

```
battery_tray/
├── main.py            ← entry point
├── app/
│   ├── config.py      constants, colors/rows globals, load/save config & state
│   ├── system.py      Win32 helpers (DPI, taskbar, dark mode, power mode)
│   ├── battery.py     IOCTL queries, WMI temp fallback, display formatters
│   ├── render.py      battery icon renderer
│   ├── popup.py       hover popup with history graph
│   └── widget.py      main tkinter widget
├── data/
│   ├── config.json    user-editable settings & colors
│   └── state.json     runtime state (history, elapsed time) - gitignored
├── build.ps1          builds dist\WinCity.exe via PyInstaller
├── build.bat          double-click shortcut → runs build.ps1
├── README.md          this file
└── requirements.txt   Python dependencies
```

---

## Quick start

Go to Settings (Win + I) > System > Power & Battery > Turn on Battery Percentage.

```powershell
pip install -r requirements.txt
python main.py
```

**Run detached in the background:**
```powershell
Start-Process python -ArgumentList "main.py" -WindowStyle Hidden
```

**Stop**
```powershell
Stop-Process -Name python
```

---

## Configuration

Edit `data/config.json` to customise the widget. Changes are picked up automatically without restarting.

Key settings:
- `rows`: control which info rows appear in the popup and in what order (`"visible": false` to hide)
- `colors`: per-theme hex colors for dark, light, graph, and widget fill
- `LOW_PCT`: percentage threshold for the red low-battery indicator
- `OFFSET_FROM_RIGHT`: widget position from the right edge of the taskbar

---

## Build a standalone .exe

**Option A - double-click** `build.bat` in Windows Explorer.

**Option B - from PowerShell:**
```powershell
.\build.ps1
```

Produces `dist\WinCity.exe` - no Python required to run.

---

## Auto-start on login

1. Press **Win + R**, type `shell:startup`, press Enter.
2. Copy `dist\WinCity.exe` (or a shortcut) into that folder.

---

## Troubleshooting

If facing issues like incorrect values at start, or getting stuck, then delete the `data/config.json` file.
A new file will automatically be created next time it starts.

If issue is still not solved, please raise an issue [here](https://github.com/AhmarZaidi/wincity/issues)

## Known Issues

- Graph may be buggy in some edge cases. Especially when charging.
- Charging time estimation may not be accurate.
- Settings button is not implemented yet.

## Todos

- [ ] Add settings page to configure colors, rows, thresholds, etc.
- [ ] Add more battery info like cycle count, temperature, etc.

## Uninstall

Quit via right-click → Quit, then delete the folder and remove the startup shortcut.
