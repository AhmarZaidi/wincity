# WinCity

A minimal taskbar battery monitor.  

| Dark Mode | Light Mode |
|------------|------------|
| <img width="400" height="700" alt="Dark Mode" src="https://github.com/user-attachments/assets/09ff82e6-3054-4428-b8a3-fc3a6cfcb01e" /> | <img width="400" height="700" alt="Light Mode" src="https://github.com/user-attachments/assets/1142ada7-1f02-42c8-bbbd-580430a0686b" /> |


## Features

| State | Widget colour | Example |
|---|---|---|
| Discharging (normal) | 🟢 Green | <img width="50" height="25" alt="image" src="https://github.com/user-attachments/assets/5bdf3f13-4abb-47ee-a9d1-301c0de33661" /> |
| Discharging (low) | 🔴 Red | <img width="50" height="25" alt="image" src="https://github.com/user-attachments/assets/a31b90cf-61ac-447b-bb35-39e932108e08" /> |
| Battery saver | 🟡 Yellow | <img width="50" height="25" alt="image" src="https://github.com/user-attachments/assets/97cff425-f577-439e-ad83-c6c8ddc1164c" /> |
| Charging | 🔵 Blue | <img width="50" height="25" alt="image" src="https://github.com/user-attachments/assets/5afb565f-c966-4584-9ce0-83cfe4fef9ad" /> |

- **Left-click** the widget to toggle between time and percentage display.
- **Hover** to open a popup: status, health, rate, cycle count, temperature, and a scrolling history graph.
- **Right-click → Quit** to exit.
- Auto-hides when a fullscreen window is active or the taskbar is hidden.

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
│   └── state.json     runtime state (history, elapsed time) — gitignored
├── build.bat          builds dist\WinCity.exe via PyInstaller
└── requirements.txt
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

**Stop it:**
```powershell
Stop-Process -Name python
```

---

## Configuration

Edit `data/config.json` to customise the widget. Changes are picked up automatically without restarting.

Key settings:
- `rows` — control which info rows appear in the popup and in what order (`"visible": false` to hide)
- `colors` — per-theme hex colors for dark, light, graph, and widget fill
- `LOW_PCT` — percentage threshold for the red low-battery indicator
- `OFFSET_FROM_RIGHT` — widget position from the right edge of the taskbar

---

## Build a standalone .exe

```
build.bat
```

Produces `dist\WinCity.exe` — no Python required to run.

---

## Auto-start on login

1. Press **Win + R**, type `shell:startup`, press Enter.
2. Copy `dist\WinCity.exe` (or a shortcut) into that folder.

---

## Troubleshooting

If facing issues like incorrect values at start, or getting stuck, then delete the `data/config.json` file.
A new file will automatically be created next time it starts.

If issue is still not solved, please raise an issue [here](https://github.com/AhmarZaidi/wincity/issues)

## Uninstall

Quit via right-click → Quit, then delete the folder and remove the startup shortcut.
