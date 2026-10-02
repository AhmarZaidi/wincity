"""
WinCity GUI entry point (.pyw runs natively with pythonw without opening a console window).
"""
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from main import main

if __name__ == "__main__":
    main()
