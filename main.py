"""
WinCity entry point.
Run with: python main.py or pythonw main.py (or double-click WinCity.lnk)
"""
import ctypes
import sys
import traceback

from app import config
from app.widget import BatteryWidget


def _acquire_single_instance_mutex():
    """Ensure only one instance of WinCity runs at a time."""
    kernel32 = ctypes.windll.kernel32
    mutex_name = "WinCity_SingleInstance_Mutex_ahmar"
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    last_error = kernel32.GetLastError()
    ERROR_ALREADY_EXISTS = 183
    if last_error == ERROR_ALREADY_EXISTS:
        return None
    return mutex


def main():
    mutex = _acquire_single_instance_mutex()
    if mutex is None:
        # WinCity is already running in background
        sys.exit(0)

    config.load_config()
    try:
        BatteryWidget().run()
    except Exception:
        traceback.print_exc()
        if sys.stdin and sys.stdin.isatty():
            try:
                input("Press Enter to exit...")
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()

