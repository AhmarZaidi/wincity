"""
Windows system helpers: DPI, Win32 API, taskbar geometry, dark mode, power mode.
DPI awareness is applied at import time.
"""
import ctypes
import ctypes.wintypes

user32 = ctypes.windll.user32

# Apply per-monitor DPI awareness as early as possible.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_ssize_t(-4))   # PER_MONITOR_AWARE_V2
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

# ── Win32 constants ───────────────────────────────────────────────────────────
GWL_EXSTYLE      = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW  = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST     = -1
SWP_NOMOVE       = 0x0002
SWP_NOSIZE       = 0x0001


def dpi_scale():
    """Return the physical-to-logical pixel scale (e.g. 1.5 at 150% / 144 DPI)."""
    try:
        return user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0


def get_taskbar_rect():
    """Return the taskbar RECT (physical pixels) via Shell_TrayWnd."""
    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    if hwnd:
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right > rect.left and rect.bottom > rect.top:
            return rect
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    rect = ctypes.wintypes.RECT()
    rect.left, rect.top, rect.right, rect.bottom = 0, sh - 48, sw, sh
    return rect


def is_dark_mode():
    """Return True when Windows apps are using dark theme."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        val, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        winreg.CloseKey(k)
        return val == 0
    except Exception:
        return True


def get_power_mode():
    """Return a human-readable string for the active Windows power overlay."""
    try:
        import uuid as _uuid
        scheme = (ctypes.c_byte * 16)()
        if ctypes.windll.powrprof.PowerGetEffectiveOverlayScheme(ctypes.byref(scheme)) == 0:
            g = _uuid.UUID(bytes_le=bytes(scheme))
            if g == _uuid.UUID("{961cc777-2547-4f9d-8174-7d86181b8a7a}"):
                return "Battery Saver"
            if g == _uuid.UUID("{ded574b5-45a0-4f42-8734-20b1de8d37b3}"):
                return "Best Performance"
    except Exception:
        pass
    return "Balanced"
