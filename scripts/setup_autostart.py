"""
Setup helper for WinCity.
Creates double-clickable shortcuts with the WinCity icon:
1. In the project folder (WinCity.lnk)
2. On your Desktop (optional)
3. In the Windows Startup folder (auto-start on login)
"""
import argparse
import sys
from pathlib import Path

# Add python directory to sys.path
_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT / "python"))

from app import startup


def main():
    parser = argparse.ArgumentParser(description="WinCity Setup & Shortcut Installer")
    parser.add_argument("--variant", choices=["rust", "python", "auto"], default="auto",
                        help="Target implementation: rust (native), python (script), or auto (prefers rust)")
    parser.add_argument("--disable-autostart", action="store_true", help="Remove Windows startup shortcut")
    args = parser.parse_args()

    print("=" * 55)
    print("       WinCity Setup & Shortcut Installer")
    print("=" * 55)
    print()

    if args.disable_autostart:
        startup.set_autostart(False)
        print("[OK] Removed WinCity from Windows startup.")
        return

    target_exe, target_args = startup.get_target_command(args.variant)
    print(f"[+] Selected Target: {target_exe} {target_args}".strip())

    # 1. Project directory shortcut
    root_lnk = startup.create_project_shortcut(args.variant)
    if root_lnk and root_lnk.exists():
        print(f"[OK] Created project shortcut: {root_lnk}")
    else:
        print("[!] Warning: Could not create project root shortcut.")

    # 2. Desktop shortcut
    desk_lnk = startup.create_desktop_shortcut(args.variant)
    if desk_lnk and desk_lnk.exists():
        print(f"[OK] Created Desktop shortcut: {desk_lnk}")
    else:
        print("[INFO] Desktop shortcut skipped or not available.")

    # 3. Windows Startup shortcut
    ok = startup.set_autostart(True, args.variant)
    if ok:
        print(f"[OK] Configured auto-start on Windows startup: {startup.get_startup_shortcut_path()}")
    else:
        print("[!] Warning: Could not configure Windows startup auto-start.")

    print()
    print("=" * 55)
    print("Setup Complete! You can now:")
    print(" - Double-click 'WinCity.lnk' in this folder or on Desktop")
    print(" - WinCity will automatically launch on Windows login")
    print("=" * 55)


if __name__ == "__main__":
    main()
