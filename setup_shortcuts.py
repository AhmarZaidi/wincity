"""
Setup helper for WinCity.
Creates double-clickable shortcuts with the WinCity icon:
1. In the project folder (WinCity.lnk)
2. On your Desktop (optional)
3. In the Windows Startup folder (auto-start on login)
"""
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from app import startup


def main():
    print("=" * 50)
    print("       WinCity Setup & Shortcut Installer")
    print("=" * 50)
    print()

    pythonw = startup.get_pythonw_path()
    print(f"[+] Detected pythonw path: {pythonw}")

    # 1. Project directory shortcut
    root_lnk = startup.create_project_shortcut()
    if root_lnk and root_lnk.exists():
        print(f"[OK] Created project shortcut: {root_lnk}")
    else:
        print("[!] Warning: Could not create project root shortcut.")

    # 2. Desktop shortcut
    desk_lnk = startup.create_desktop_shortcut()
    if desk_lnk and desk_lnk.exists():
        print(f"[OK] Created Desktop shortcut: {desk_lnk}")
    else:
        print("[INFO] Desktop shortcut skipped or not available.")

    # 3. Windows Startup shortcut
    ok = startup.set_autostart(True)
    if ok:
        print(f"[OK] Configured auto-start on Windows startup: {startup.get_startup_shortcut_path()}")
    else:
        print("[!] Warning: Could not configure Windows startup auto-start.")

    print()
    print("=" * 50)
    print("Setup Complete! You can now:")
    print(" - Double-click 'WinCity.lnk' in this folder or on Desktop")
    print(" - WinCity will also automatically launch on Windows startup")
    print(" - No .exe or SmartScreen warnings required!")
    print("=" * 50)



if __name__ == "__main__":
    main()
