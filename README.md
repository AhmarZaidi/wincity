# WinCity for Windows 11

A minimal taskbar battery monitor — always visible, no clicking needed.  
Shows time remaining (discharging) or time to full (charging).  
Hover for a detailed popup with a live history graph.

## Features

| State | Widget colour | Label |
|---|---|---|
| Discharging (normal) | 🟢 Green | Time remaining e.g. `5:10` |
| Discharging (low) | 🔴 Red | Time remaining e.g. `0:23` |
| Battery saver | 🟡 Yellow | Time remaining |
| Charging | 🔵 Blue | Time to full e.g. `1:13` |

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

## Uninstall

Quit via right-click → Quit, then delete the folder and remove the startup shortcut.
