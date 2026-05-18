# BatteryBar for Windows 11

A minimal system-tray battery monitor that shows time remaining (discharging)
or time to full (charging) — always visible in the taskbar, no clicking needed.

## Features

| State | Fill colour | Label |
|---|---|---|
| Discharging ≥ 10 % | 🟢 Green | Time remaining e.g. `5h 10m` |
| Discharging < 10 % | 🔴 Red   | Time remaining e.g. `23m`    |
| Charging           | 🔵 Blue  | Time to full e.g. `1h 13m`   |

**Hover** the tray icon → live drain/charge rate updates every second.  
Background polling is every **30 seconds** to minimise CPU/battery impact.

---

## Quick start (run from source)

```
# 1. Install Python 3.9+ from python.org (add to PATH)
# 2. Open a terminal in this folder

pip install -r requirements.txt
python battery_tray.py
```

The icon appears in the system tray (you may need to expand the overflow area).

---

## Build a standalone .exe (recommended)

```
build.bat
```

This produces `dist\BatteryBar.exe` — no Python needed to run it.

---

## Auto-start on login

1. Press **Win + R** and type `shell:startup`, press Enter.  
2. Copy `dist\BatteryBar.exe` (or a shortcut to it) into that folder.  
3. Done — BatteryBar launches automatically on every login.

---

## How it works

- **Icon drawing**: `Pillow` renders a 64×64 RGBA battery icon in memory each
  refresh cycle. No files on disk, no GPU usage.
- **Battery data**: `psutil.sensors_battery()` — a single OS call, negligible CPU.
- **Tray integration**: `pystray` — uses native Win32 `Shell_NotifyIcon` under
  the hood, same as any other system tray app.
- **Hover rate**: A background thread does a 1-second percentage delta to
  estimate drain/charge rate in %/hr and writes it to the tooltip title.
  This runs continuously but only *reads* a single integer twice — CPU cost
  is essentially zero.

---

## Uninstall

Close via **right-click → Quit** in the tray, then delete the folder / remove
the startup shortcut.
