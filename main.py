"""
BatteryBar entry point.
Run with: python main.py
"""
import sys
import traceback

from app import config
from app.widget import BatteryWidget


def main():
    config.load_config()
    try:
        BatteryWidget().run()
    except Exception:
        traceback.print_exc()
        input("Press Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    main()
