"""
BatteryBar - Windows 11 taskbar widget battery monitor.
A borderless always-on-top window sitting on the taskbar.
Shows a battery icon with time remaining drawn inside it.
Right-click to quit.
"""

import ctypes
import ctypes.wintypes
import threading
import time
import psutil
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageTk

# ── Position / size  (edit these to adjust placement) ────────────────────────
WIDGET_WIDTH      = 55    # width of the widget in pixels
WIDGET_HEIGHT     = 25    # None = auto-fit to taskbar height; or set an int (px)
OFFSET_FROM_RIGHT = 130    # px from the right edge of the taskbar (clears the clock)
OFFSET_FROM_TOP   = None  # None = auto-centre vertically; or set an int (px from taskbar top)

# ── Appearance ────────────────────────────────────────────────────────────────
UPDATE_INTERVAL = 10      # seconds between background refreshes
LOW_PCT         = 10      # battery % below which fill turns red
CORNER_RADIUS   = 8      # corner radius for the battery icon in pixels (0 = square)
FILL_PADDING      = 0     # gap in pixels between the outline and the fill colour
FILL_RIGHT_EXTEND = 0     # extra px added to the fill's right edge (corrects visual right gap on full charge)
FONT_SIZE           = 22  # label font size in points
RENDER_SCALE        = 8   # internal supersampling (higher = crisper; 4-8 recommended)
VISIBILITY_POLL_MS  = 500 # ms between taskbar visibility checks (lower = snappier hide/show)

# ── Hover popup ────────────────────────────────────────────────────────────
POPUP_Y_OFFSET      = 20   # px gap between popup bottom and widget top (increase to move up)
POPUP_CORNER_RADIUS = 12   # corner radius of the hover popup in pixels
POPUP_TITLE_SIZE    = 16   # font size (pt) for the popup title "BatteryBar"
POPUP_TEXT_SIZE     = 12   # font size (pt) for info row labels and values
POPUP_ICON_SIZE     = 16   # font size (pt) for MDL2 icons in the popup

# ── Windows API ───────────────────────────────────────────────────────────────
user32 = ctypes.windll.user32

# Enable per-monitor DPI awareness as early as possible so all coordinates and
# rendering use physical pixels instead of being scaled by Windows.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_ssize_t(-4))  # PER_MONITOR_AWARE_V2
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)           # fallback
    except Exception:
        pass


def _dpi_scale():
    """Return physical-to-logical scale factor (e.g. 1.5 at 144 DPI / 150%)."""
    try:
        return user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0

GWL_EXSTYLE      = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW  = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST     = -1
SWP_NOMOVE       = 0x0002
SWP_NOSIZE       = 0x0001


def _get_taskbar_rect():
    """Get taskbar rect in logical (tkinter) coordinates via Shell_TrayWnd."""
    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    if hwnd:
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right > rect.left and rect.bottom > rect.top:
            return rect
    # Fallback: synthesise a bottom taskbar from screen dimensions
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    rect = ctypes.wintypes.RECT()
    rect.left, rect.top, rect.right, rect.bottom = 0, sh - 48, sw, sh
    return rect


# ── Battery helpers ───────────────────────────────────────────────────────────

def get_battery():
    try:
        return psutil.sensors_battery()
    except Exception:
        return None


def format_time(secs):
    """Return 'H:MM' or None if time is unknown, unlimited, or implausibly large (≥99 h)."""
    if secs is None or secs <= 0:
        return None
    if secs in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED, -1, -2):
        return None
    if secs >= 99 * 3600:   # implausible estimate — fall back to percentage
        return None
    return f"{secs // 3600}:{(secs % 3600) // 60:02d}"


def format_time_long(secs):
    """Return 'x Hours xx Minutes' (or just hours/minutes when one part is zero)."""
    if secs is None or secs <= 0:
        return None
    if secs in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED, -1, -2):
        return None
    if secs >= 99 * 3600:
        return None
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    if h > 0 and m > 0:
        return f"{h} Hour{'s' if h != 1 else ''} {m} Minute{'s' if m != 1 else ''}"
    if h > 0:
        return f"{h} Hour{'s' if h != 1 else ''}"
    return f"{m} Minute{'s' if m != 1 else ''}" if m > 0 else None


def _query_battery_hw():
    """Query battery hardware via IOCTL in a single device open.
    Returns (rate_mw, designed_mwh, full_mwh) — any value may be None.
    rate_mw: positive=charging, negative=discharging.
    """
    rate_mw = designed_mwh = full_mwh = None
    try:
        class _GUID(ctypes.Structure):
            _fields_ = [('Data1', ctypes.c_ulong),
                        ('Data2', ctypes.c_ushort),
                        ('Data3', ctypes.c_ushort),
                        ('Data4', ctypes.c_ubyte * 8)]

        class _SP_IFACE_DATA(ctypes.Structure):
            _fields_ = [('cbSize',             ctypes.wintypes.DWORD),
                        ('InterfaceClassGuid', _GUID),
                        ('Flags',             ctypes.wintypes.DWORD),
                        ('Reserved',          ctypes.c_size_t)]

        class _SP_IFACE_DETAIL(ctypes.Structure):
            _fields_ = [('cbSize',     ctypes.wintypes.DWORD),
                        ('DevicePath', ctypes.c_wchar * 512)]

        class _BAT_WAIT(ctypes.Structure):
            _fields_ = [('BatteryTag',   ctypes.c_ulong),
                        ('Timeout',      ctypes.c_ulong),
                        ('PowerState',   ctypes.c_ulong),
                        ('LowCapacity',  ctypes.c_ulong),
                        ('HighCapacity', ctypes.c_ulong)]

        class _BAT_STATUS(ctypes.Structure):
            _fields_ = [('PowerState', ctypes.c_ulong),
                        ('Capacity',   ctypes.c_ulong),
                        ('Voltage',    ctypes.c_ulong),
                        ('Rate',       ctypes.c_long)]

        class _BAT_QUERY_INFO(ctypes.Structure):
            _fields_ = [('BatteryTag',       ctypes.c_ulong),
                        ('InformationLevel', ctypes.c_ulong),
                        ('AtRate',           ctypes.c_long)]

        class _BAT_INFO(ctypes.Structure):
            _fields_ = [('Capabilities',       ctypes.c_ulong),
                        ('Technology',         ctypes.c_ubyte),
                        ('Reserved',           ctypes.c_ubyte * 3),
                        ('Chemistry',          ctypes.c_ubyte * 4),
                        ('DesignedCapacity',   ctypes.c_ulong),
                        ('FullChargedCapacity',ctypes.c_ulong),
                        ('DefaultAlert1',      ctypes.c_ulong),
                        ('DefaultAlert2',      ctypes.c_ulong),
                        ('ReservedCapacity',   ctypes.c_ulong),
                        ('CycleCount',         ctypes.c_ulong)]

        sa  = ctypes.windll.setupapi
        k32 = ctypes.windll.kernel32

        sa.SetupDiGetClassDevsW.restype  = ctypes.c_void_p
        k32.CreateFileW.restype          = ctypes.c_void_p

        _ptr_w         = ctypes.sizeof(ctypes.c_void_p) * 8
        INVALID_HANDLE = (1 << _ptr_w) - 1

        guid = _GUID(0x72631E54, 0x78A4, 0x11D0,
                     (ctypes.c_ubyte * 8)(0xBC, 0xF7, 0x00, 0xAA, 0x00, 0xB7, 0xB3, 0x2A))

        DIGCF_PRESENT                   = 0x02
        DIGCF_DEVICEINTERFACE           = 0x10
        GENERIC_READ                    = 0x80000000
        GENERIC_WRITE                   = 0x40000000
        FILE_SHARE_READ                 = 0x01
        FILE_SHARE_WRITE                = 0x02
        OPEN_EXISTING                   = 3
        IOCTL_BATTERY_QUERY_TAG         = 0x294040
        IOCTL_BATTERY_QUERY_STATUS      = 0x29404C
        IOCTL_BATTERY_QUERY_INFORMATION = 0x294044
        BATTERY_UNKNOWN_RATE            = -2147483648

        hdev = sa.SetupDiGetClassDevsW(
            ctypes.byref(guid), None, None,
            DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
        if hdev is None or hdev == INVALID_HANDLE:
            return rate_mw, designed_mwh, full_mwh

        hdev_p = ctypes.c_void_p(hdev)
        try:
            idx = 0
            while True:
                iface = _SP_IFACE_DATA()
                iface.cbSize = ctypes.sizeof(iface)
                if not sa.SetupDiEnumDeviceInterfaces(
                        hdev_p, None, ctypes.byref(guid), idx, ctypes.byref(iface)):
                    break
                idx += 1

                detail = _SP_IFACE_DETAIL()
                detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                req = ctypes.wintypes.DWORD()
                sa.SetupDiGetDeviceInterfaceDetailW(
                    hdev_p, ctypes.byref(iface), ctypes.byref(detail),
                    ctypes.sizeof(detail), ctypes.byref(req), None)

                hbat = k32.CreateFileW(
                    detail.DevicePath,
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None, OPEN_EXISTING, 0, None)
                if hbat is None or hbat == INVALID_HANDLE:
                    continue
                hbat_p = ctypes.c_void_p(hbat)
                try:
                    tag        = ctypes.c_ulong(0)
                    timeout_in = ctypes.c_ulong(0)
                    br         = ctypes.wintypes.DWORD()
                    if not k32.DeviceIoControl(
                            hbat_p, IOCTL_BATTERY_QUERY_TAG,
                            ctypes.byref(timeout_in), ctypes.sizeof(timeout_in),
                            ctypes.byref(tag), ctypes.sizeof(tag),
                            ctypes.byref(br), None):
                        continue
                    if tag.value == 0:
                        continue

                    # Rate
                    wait = _BAT_WAIT(BatteryTag=tag.value, Timeout=0,
                                     PowerState=0, LowCapacity=0,
                                     HighCapacity=0xFFFFFFFF)
                    status = _BAT_STATUS()
                    if k32.DeviceIoControl(
                            hbat_p, IOCTL_BATTERY_QUERY_STATUS,
                            ctypes.byref(wait), ctypes.sizeof(wait),
                            ctypes.byref(status), ctypes.sizeof(status),
                            ctypes.byref(br), None):
                        if status.Rate != BATTERY_UNKNOWN_RATE:
                            rate_mw = status.Rate

                    # Capacity (for health)
                    qinfo = _BAT_QUERY_INFO(BatteryTag=tag.value,
                                            InformationLevel=0,  # BatteryInformation
                                            AtRate=0)
                    binfo = _BAT_INFO()
                    if k32.DeviceIoControl(
                            hbat_p, IOCTL_BATTERY_QUERY_INFORMATION,
                            ctypes.byref(qinfo), ctypes.sizeof(qinfo),
                            ctypes.byref(binfo), ctypes.sizeof(binfo),
                            ctypes.byref(br), None):
                        if binfo.DesignedCapacity > 0:
                            designed_mwh = int(binfo.DesignedCapacity)
                            full_mwh     = int(binfo.FullChargedCapacity)
                    break  # first battery device is sufficient
                finally:
                    k32.CloseHandle(hbat_p)
        finally:
            sa.SetupDiDestroyDeviceInfoList(hdev_p)
    except Exception:
        pass
    return rate_mw, designed_mwh, full_mwh


def _fmt_rate(mw):
    """Format a mW rate value for display: '+3.8 W', '-5.2 W', or '—'."""
    if mw is None:
        return "—"
    w = abs(mw) / 1000.0
    sign = "+" if mw > 0 else "-"
    return f"{sign}{w:.1f} W"


def _fmt_health(designed_mwh, full_mwh):
    """Format battery health as 'xx.x% (xxWh/xxWh)'."""
    if designed_mwh is None or full_mwh is None or designed_mwh <= 0:
        return "—"
    pct    = full_mwh / designed_mwh * 100
    des_wh = designed_mwh / 1000
    ful_wh = full_mwh     / 1000
    return f"{pct:.1f}% ({ful_wh:.0f}Wh/{des_wh:.0f}Wh)"


def _load_font(size):
    """Load best available font at given point size."""
    for name in ("segoeuisb.ttf", "segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _render_battery(W, H, bat, label=None, dark=True):
    """Render the battery icon at W×H using RENDER_SCALE× supersampling.
    Pass label to override the auto-computed text (e.g. estimated charge time).
    """
    S   = RENDER_SCALE
    sw, sh = W * S, H * S
    img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    if bat is None:
        fnt = _load_font(FONT_SIZE * S)
        d.text((sw // 2, sh // 2), "N/A", font=fnt, fill=(136, 136, 136, 255), anchor="mm")
        return img.resize((W, H), Image.LANCZOS).filter(
            ImageFilter.UnsharpMask(radius=0.5, percent=180, threshold=0)
        )
    pct     = bat.percent
    plugged = bat.power_plugged
    if label is None:
        time_s = format_time(bat.secsleft)
        label  = time_s if time_s else f"{pct:.0f}%"

    if plugged:
        fill_col = (50,  150, 240, 255)
    elif pct <= LOW_PCT:
        fill_col = (220,  50,  50, 255)
    elif _get_power_mode() == "Battery Saver":
        fill_col = (240, 190,  40, 255)
    else:
        fill_col = (60,  200,  80, 255)

    nub_w  = 5 * S
    bx0, by0 = 2 * S, 2 * S
    bx1, by1 = sw - 2 * S - nub_w, sh - 2 * S
    body_w = bx1 - bx0
    body_h = by1 - by0
    r      = CORNER_RADIUS * S

    # Theme-dependent colors
    if dark:
        body_bg  = (26,  26,  26,  255)
        nub_col  = (170, 170, 170, 255)
        outline  = (136, 136, 136, 255)
        text_col = (255, 255, 255, 255)
    else:
        body_bg  = (255, 255, 255, 255)
        nub_col  = (30,  30,  30,  255)
        outline  = (30,  30,  30,  255)
        text_col = (26,  26,  26,  255)

    # Nub
    nub_h  = max(4 * S, body_h // 3)
    nub_y0 = by0 + (body_h - nub_h) // 2
    d.rounded_rectangle([bx1, nub_y0, bx1 + nub_w, nub_y0 + nub_h],
                        radius=min(r, nub_w // 2), fill=nub_col)

    # Body background (outline drawn last so it always sits on top of the fill)
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=r, fill=body_bg)

    # Charge fill — FILL_PADDING logical-px gap on every side; 0 = touches the outline
    pad        = FILL_PADDING * S
    rext       = FILL_RIGHT_EXTEND * S
    fill_max_w = max(1, body_w - 2 * pad)
    fill_w     = max(1, int(fill_max_w * pct / 100))
    fill_x1    = min(bx0 + pad + fill_w + rext, bx1 - pad)
    d.rounded_rectangle([bx0 + pad, by0 + pad, fill_x1, by1 - pad],
                        radius=max(1, r - pad) if pad > 0 else r, fill=fill_col)

    # Outline on top — always fully visible regardless of fill level
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=r,
                        outline=outline, width=S)

    # Label centred in body
    fnt  = _load_font(FONT_SIZE * S)
    cx   = bx0 + body_w // 2
    cy   = by0 + body_h // 2
    d.text((cx, cy), label, font=fnt, fill=text_col, anchor="mm")

    return img.resize((W, H), Image.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=0.5, percent=180, threshold=0)
    )


# ── Popup helpers ─────────────────────────────────────────────────────────────

def _is_dark_mode():
    """Return True when Windows apps use dark theme."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        val, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        winreg.CloseKey(k)
        return val == 0
    except Exception:
        return True


def _get_power_mode():
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


class BatteryPopup:
    """Hover info popup — PIL-rendered; transparent-key gives true rounded corners."""

    _TC     = "#020202"   # transparent key color (distinct from widget's #010101)
    _TC_RGB = (2, 2, 2)
    _MIN_W  = 248

    # Layout in logical px (scaled by DPI at render time)
    _PX = 14   # horizontal padding
    _PY = 10   # vertical padding
    _TH = 28   # title row height
    _SH = 13   # separator block height
    _RH = 26   # info row height
    _QH   = 30   # action bar row height
    _TTPH = 18   # tooltip strip height below action bar

    _IC = {
        "status":      "\uE8A1",   # Info
        "thunder":     "\uE945",   # Lightning
        "pct":         "\uE83F",   # BatteryFull
        "time":        "\uE916",   # Timer
        "rate":        "\uE7EF",   # PlugConnected
        "elapsed":     "\uE81C",   # History
        "screen":      "\uE7F4",   # TVMonitor
        "power":       "\uE7E8",   # PowerButton
        "health":      "\uEB52",   # HeartFill
        # Action bar
        "startup_on":  "\uE73E",   # CheckboxFilled (startup enabled)
        "startup_off": "\uE739",   # Checkbox (startup disabled)
        "folder":      "\uE8B7",   # Folder
        "settings":    "\uE713",   # Settings
        "close":       "\uE7E8",   # PowerButton (quit — better than x)
    }

    def __init__(self, root, wx, wy, ww, wh, bat, label, secs,
                 rate_mw, designed_mwh, full_mwh, quit_cb, close_cb):
        self._quit_cb     = quit_cb
        self._close_cb    = close_cb
        self._bat         = bat
        self._label       = label
        self._secs        = secs
        self._rate_mw     = rate_mw
        self._designed_mwh = designed_mwh
        self._full_mwh     = full_mwh
        dark = _is_dark_mode()

        if dark:
            self._bg   = (28,  28,  28)
            self._fg   = (255, 255, 255)
            self._fg2  = (157, 157, 157)
            self._bdr  = (60,  60,  60)
            self._icol = (200, 200, 200)
            self._red  = (224, 64,  64)
            self._hov  = (45,  45,  45)
        else:
            self._bg   = (249, 249, 249)
            self._fg   = (26,  26,  26)
            self._fg2  = (92,  92,  92)
            self._bdr  = (222, 222, 222)
            self._icol = (85,  85,  85)
            self._red  = (196, 43,  28)
            self._hov  = (235, 235, 235)

        s  = _dpi_scale()
        pw = max(int(self._MIN_W * s), self._MIN_W)
        ph = int((self._PY + self._TH + self._SH
                  + 8 * self._RH + self._SH + self._QH + self._TTPH + self._PY) * s)

        self._startup_on        = False  # placeholder toggle state
        self._pw, self._ph, self._s = pw, ph, s
        self._img_cache         = {}     # (hover_key, startup_on) -> PhotoImage

        # Action bar y bounds (all buttons share the same row)
        self._bar_y0 = int((self._PY + self._TH + self._SH + 8 * self._RH + self._SH) * s)
        self._bar_y1 = self._bar_y0 + int(self._QH * s)

        # Button x bounds for hit-testing
        _b   = int(self._QH * s)
        _g   = int(4         * s)
        _pxi = int(self._PX  * s)
        self._btn_xr = {
            "startup":  (_pxi,               _pxi + _b),
            "folder":   (_pxi + _b + _g,     _pxi + 2*_b + _g),
            "settings": (_pxi + 2*(_b+_g),   _pxi + 3*_b + 2*_g),
            "quit":     (pw - _pxi - _b,     pw - _pxi),
        }

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", self._TC)
        self.win.configure(bg=self._TC)
        self.win.resizable(False, False)

        self._cv = tk.Canvas(self.win, width=pw, height=ph,
                              bg=self._TC, highlightthickness=0)
        self._cv.pack()

        _init_img    = ImageTk.PhotoImage(self._render(pw, ph, s, None))
        self._img_cache[(None, self._startup_on)] = _init_img
        self._img_id = self._cv.create_image(0, 0, anchor="nw", image=_init_img)
        self._cv.bind("<Button-1>", self._on_click)
        self._cv.bind("<Motion>",   self._on_motion)
        self._cv.bind("<Leave>",    self._on_leave)
        # Close popup when user clicks anywhere outside it
        self.win.bind("<FocusOut>", lambda _e: self._schedule_close())
        root.bind("<Button-1>",     lambda _e: self._schedule_close(), add="+")

        px = wx + ww // 2 - pw // 2
        py = wy - ph - POPUP_Y_OFFSET
        sw = root.winfo_screenwidth()
        px = max(4, min(px, sw - pw - 4))
        py = max(4, py)

        self.win.geometry(f"{pw}x{ph}+{px}+{py}")
        self.win.update()

        try:
            hwnd  = self.win.winfo_id()
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    # ── Rendering ─────────────────────────────────────────────────────────

    def _render(self, w, h, s, hover_key):
        r = POPUP_CORNER_RADIUS

        def a(rgb): return rgb + (255,)

        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)

        # Rounded rect background + border
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=r,
                             fill=a(self._bg), outline=a(self._bdr), width=1)

        tfnt = _load_font(int(POPUP_TITLE_SIZE * s))
        nfnt = _load_font(int(POPUP_TEXT_SIZE * s))
        ifnt = self._mdl2_font(int(POPUP_ICON_SIZE * s))

        px = int(self._PX * s)
        y  = int(self._PY * s)

        # Title
        d.text((px,     y + int(self._TH * s) // 2), "BatteryBar",
               font=tfnt, fill=a(self._fg), anchor="lm")
        d.text((w - px, y + int(self._TH * s) // 2), "v1.0.0",
               font=nfnt, fill=a(self._fg2), anchor="rm")
        y += int(self._TH * s)

        # Separator
        d.line([(px, y + 4), (w - px, y + 4)], fill=a(self._bdr), width=1)
        y += int(self._SH * s)

        # Info rows — tuples are (left_icon, name, value) or (left_icon, name, value, val_icon)
        for row in self._rows():
            icon, name, value = row[:3]
            val_icon = row[3] if len(row) > 3 else None
            my = y + int(self._RH * s) // 2
            d.text((px + int(11 * s), my), icon,  font=ifnt, fill=a(self._icol), anchor="mm")
            d.text((px + int(26 * s), my), name,  font=nfnt, fill=a(self._fg2),  anchor="lm")
            if val_icon:
                # Measure value text width, place MDL2 icon immediately to its left
                txt_w  = int(d.textlength(value, font=nfnt))
                ico_w  = int(POPUP_ICON_SIZE * s)
                gap    = int(4 * s)
                blk_x  = w - px - txt_w - gap - ico_w
                d.text((blk_x + ico_w // 2, my), val_icon, font=ifnt,
                        fill=a(self._fg), anchor="mm")
                d.text((blk_x + ico_w + gap, my), value,   font=nfnt,
                        fill=a(self._fg), anchor="lm")
            else:
                d.text((w - px, my), value, font=nfnt, fill=a(self._fg), anchor="rm")
            y += int(self._RH * s)

        # Separator
        d.line([(px, y + 4), (w - px, y + 4)], fill=a(self._bdr), width=1)
        y += int(self._SH * s)

        # Action bar — 3 icon buttons on the left, quit on the right
        b      = int(self._QH * s)   # button slot width (square)
        g      = int(4  * s)         # gap between adjacent buttons
        bar_y  = y + b // 2          # vertical centre of the action bar

        _btns = [
            ("startup",  self._IC["startup_on" if self._startup_on else "startup_off"]),
            ("folder",   self._IC["folder"]),
            ("settings", self._IC["settings"]),
            ("quit",     self._IC["close"]),
        ]
        _cx = {
            "startup":  px + b // 2,
            "folder":   px + b + g + b // 2,
            "settings": px + 2*(b + g) + b // 2,
            "quit":     w - px - b // 2,
        }
        _tips = {
            "startup":  f"Run at Startup: {'On' if self._startup_on else 'Off'}",
            "folder":   "Open File Location",
            "settings": "Settings",
            "quit":     "Quit",
        }

        for btn_key, glyph in _btns:
            cx      = _cx[btn_key]
            hov     = (hover_key == btn_key)
            is_quit = (btn_key == "quit")
            if hov:
                bx0 = cx - b // 2
                bx1 = cx + b // 2
                d.rounded_rectangle([bx0, y + int(2 * s), bx1, y + b - int(2 * s)],
                                     radius=int(4 * s), fill=a(self._hov))
            ic_col = self._red if is_quit else (self._fg if hov else self._icol)
            d.text((cx, bar_y), glyph, font=ifnt, fill=a(ic_col), anchor="mm")

        # Tooltip strip — shown below action bar when a button is hovered
        if hover_key in _tips:
            tip_y = y + b + int(self._TTPH * s) // 2
            d.text((w // 2, tip_y), _tips[hover_key],
                   font=nfnt, fill=a(self._fg2), anchor="mm")

        # Composite onto transparent key — corners outside rounded rect become invisible
        result = Image.new("RGB", (w, h), self._TC_RGB)
        result.paste(img.convert("RGB"), mask=img.split()[3])
        return result

    @staticmethod
    def _mdl2_font(size):
        import os
        candidates = [
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segmdl2.ttf"),
            "segmdl2.ttf",
        ]
        for p in candidates:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
        return _load_font(size)

    def _rows(self):
        bat, label = self._bat, self._label
        if bat is None:
            return [(self._IC["status"], "Status", "Unknown")]
        if self._full_mwh:
            remaining_wh = self._full_mwh * bat.percent / 100 / 1000
            pct = f"{bat.percent:.0f}% ({remaining_wh:.1f} Wh)"
        else:
            pct = f"{bat.percent:.0f}%"
        t_lbl = "Time to Full" if bat.power_plugged else "Time Left"
        t_val = format_time_long(self._secs) or ("Full" if bat.percent >= 100 else "—")
        if bat.power_plugged:
            status_row = (self._IC["status"], "Status", "Charging", self._IC["thunder"])
        else:
            status_row = (self._IC["status"], "Status", "Discharging")
        return [
            status_row,
            (self._IC["pct"],     "Percentage",  pct),
            (self._IC["time"],    t_lbl,         t_val),
            (self._IC["rate"],    "Rate",        _fmt_rate(self._rate_mw)),
            (self._IC["elapsed"], "Elapsed",     "—"),
            (self._IC["screen"],  "Screen On",   "—"),
            (self._IC["power"],   "Power Mode",  _get_power_mode()),
            (self._IC["health"],  "Health",      _fmt_health(self._designed_mwh, self._full_mwh)),
        ]

    # ── Interaction ───────────────────────────────────────────────────────

    def _btn_hit(self, x, y):
        """Return the action-bar button key at canvas (x, y), or None."""
        if not (self._bar_y0 <= y < self._bar_y1):
            return None
        for key, (x0, x1) in self._btn_xr.items():
            if x0 <= x < x1:
                return key
        return None

    def _refresh_image(self, hover_key):
        """Display the cached (or freshly rendered) image for the given hover state."""
        ck = (hover_key, self._startup_on)
        if ck not in self._img_cache:
            self._img_cache[ck] = ImageTk.PhotoImage(
                self._render(self._pw, self._ph, self._s, hover_key))
        self._cv.itemconfig(self._img_id, image=self._img_cache[ck])

    def _on_click(self, event):
        btn = self._btn_hit(event.x, event.y)
        if btn == "quit":
            self._quit_cb()
        elif btn == "startup":
            self._startup_on = not self._startup_on
            self._img_cache.clear()   # icon changes — invalidate all cached renders
            self._refresh_image("startup")

    def _on_motion(self, event):
        btn = self._btn_hit(event.x, event.y)
        self._refresh_image(btn)
        self._cv.config(cursor="hand2" if btn else "")

    def _on_leave(self, _e=None):
        self._refresh_image(None)
        self._cv.config(cursor="")

    def _schedule_close(self):
        """Request close via a short delay so click-on-popup itself isn't misread."""
        try:
            self.win.after(50, self._check_close)
        except Exception:
            pass

    def _check_close(self):
        """Close popup if the pointer is not currently over it."""
        try:
            px = self.win.winfo_pointerx()
            py = self.win.winfo_pointery()
            x, y = self.win.winfo_x(), self.win.winfo_y()
            w, h = self.win.winfo_width(), self.win.winfo_height()
            if not (x <= px < x + w and y <= py < y + h):
                self._close_request()
        except Exception:
            pass

    def _close_request(self):
        """Called when popup should close; notifies the widget via stored callback."""
        self._close_cb()

    def destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass


# ── Taskbar widget ────────────────────────────────────────────────────────────

class BatteryWidget:
    BG     = "#1c1c1c"
    GREEN  = "#3cc850"
    BLUE   = "#3296f0"
    RED    = "#dc3232"
    FG     = "#ffffff"
    BORDER = "#3a3a3a"

    @staticmethod
    def _should_show():
        """Return True when the widget should be visible.
        Hidden when: taskbar is auto-hidden off-screen, OR a fullscreen window covers the monitor.
        """
        # Check 1: taskbar auto-hidden (rect shrinks to ~2 px when slid off-screen)
        tb_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
        if not tb_hwnd or not user32.IsWindowVisible(tb_hwnd):
            return False
        tb_rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(tb_hwnd, ctypes.byref(tb_rect))
        if min(tb_rect.bottom - tb_rect.top, tb_rect.right - tb_rect.left) <= 6:
            return False

        # Check 2: foreground window is fullscreen (covers the whole screen)
        fg = user32.GetForegroundWindow()
        if fg:
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(fg, cls, 256)
            # Ignore desktop/taskbar windows
            if cls.value not in ("Shell_TrayWnd", "Progman", "WorkerW", ""):
                fg_rect = ctypes.wintypes.RECT()
                user32.GetWindowRect(fg, ctypes.byref(fg_rect))
                sw = user32.GetSystemMetrics(0)  # physical screen width
                sh = user32.GetSystemMetrics(1)  # physical screen height
                if fg_rect.left <= 0 and fg_rect.top <= 0 and fg_rect.right >= sw and fg_rect.bottom >= sh:
                    return False

        return True

    def __init__(self):
        self._stop         = threading.Event()
        self._widget_shown = True
        self._charge_obs   = None   # (timestamp, percent) last charging observation
        self._charge_rate  = None   # estimated charge rate in %/second
        self._show_percent = False  # toggled by left-click: True = always show %
        self._popup      = None    # BatteryPopup instance when hovered, else None
        self._last_bat   = None    # cached battery data for popup
        self._last_label = None    # cached displayed label for popup
        self._last_secs  = None    # raw seconds used to compute label (for long format)
        self._last_rate_mw     = None  # cached battery rate in mW for popup
        self._last_designed_mwh = None  # battery designed capacity in mWh
        self._last_full_mwh     = None  # battery full-charge capacity in mWh

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg=self.BG)
        self.root.resizable(False, False)

        tb     = _get_taskbar_rect()
        tb_h   = tb.bottom - tb.top
        scale  = _dpi_scale()
        self.H = int((WIDGET_HEIGHT if WIDGET_HEIGHT is not None else max(28, tb_h - 8)) * scale)
        self.W = int(WIDGET_WIDTH * scale)

        # Use a key colour for transparency so only the battery shape is visible
        TRANSPARENT = "#010101"
        self.root.attributes("-transparentcolor", TRANSPARENT)
        self.root.configure(bg=TRANSPARENT)

        self.canvas = tk.Canvas(
            self.root,
            width=self.W, height=self.H,
            bg=TRANSPARENT, highlightthickness=0,
        )
        self.canvas.pack()
        self._place(tb, tb_h)

        # Right-click → quit
        self._menu = tk.Menu(self.root, tearoff=0, bg="#2d2d2d", fg="#ffffff",
                             activebackground="#3a3a3a", activeforeground="#ffffff",
                             font=("Segoe UI", 9))
        self._menu.add_command(label="BatteryBar", state="disabled")
        self._menu.add_separator()
        self._menu.add_command(label="Quit", command=self._quit)
        self.canvas.bind("<Button-3>", self._show_menu)
        self.canvas.bind("<Button-1>", self._toggle_display)
        self.canvas.bind("<Enter>",    self._on_hover_enter)

        self._update_ui()
        self.root.update()

        try:
            self._apply_win_style()
        except Exception:
            pass  # styling is cosmetic — don't crash if it fails

        threading.Thread(target=self._bg_updater, daemon=True).start()
        self.root.after(VISIBILITY_POLL_MS, self._poll_taskbar_visibility)

    # ── Positioning ────────────────────────────────────────────────────────

    def _place(self, tb, tb_h):
        x = tb.right - self.W - OFFSET_FROM_RIGHT
        if OFFSET_FROM_TOP is None:
            y = tb.top + (tb_h - self.H) // 2
        else:
            y = tb.top + OFFSET_FROM_TOP
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

    # ── Win32 styling ──────────────────────────────────────────────────────

    def _apply_win_style(self):
        hwnd  = self.root.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)

    # ── Drawing ────────────────────────────────────────────────────────────

    def _draw(self, bat, label=None):
        W, H   = self.W, self.H
        T      = (1, 1, 1)          # transparent key colour as RGB tuple

        batt   = _render_battery(W, H, bat, label, dark=_is_dark_mode())   # RGBA PIL image

        # Composite RGBA battery over the transparent key colour
        bg = Image.new("RGB", (W, H), T)
        bg.paste(batt, mask=batt.split()[3])

        self._photo = ImageTk.PhotoImage(bg)   # keep reference to prevent GC
        c = self.canvas
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._photo)

    # ── Refresh ────────────────────────────────────────────────────────────

    def _update_ui(self):
        bat   = get_battery()
        label = None

        if self._show_percent:
            # Percentage-only mode — skip time logic entirely
            if bat:
                label = f"{bat.percent:.0f}%"
        elif bat and bat.power_plugged and bat.percent < 100:
            now = time.monotonic()
            if self._charge_obs is not None:
                prev_t, prev_pct = self._charge_obs
                dt   = now - prev_t
                dpct = bat.percent - prev_pct
                if dt > 0 and dpct > 0:
                    self._charge_rate = dpct / dt  # percentage points per second
            self._charge_obs = (now, bat.percent)

            # Prefer the OS-supplied time; fall back to our estimated rate
            if bat.secsleft > 0:
                self._last_secs = bat.secsleft
                label = format_time(bat.secsleft)
            elif self._charge_rate:
                est = int((100 - bat.percent) / self._charge_rate)
                self._last_secs = est
                label = format_time(est)
        else:
            self._charge_obs  = None
            self._charge_rate = None
            self._last_secs   = bat.secsleft if (bat and not bat.power_plugged) else None

        self._last_bat   = bat
        self._last_label = label
        rate_mw, designed_mwh, full_mwh = _query_battery_hw()
        self._last_rate_mw      = rate_mw
        self._last_designed_mwh = designed_mwh
        self._last_full_mwh     = full_mwh
        self._draw(bat, label)

    def _toggle_display(self, _event=None):
        self._show_percent = not self._show_percent
        self._update_ui()

    def _bg_updater(self):
        while not self._stop.wait(UPDATE_INTERVAL):
            self.root.after(0, self._update_ui)

    # ── Taskbar visibility tracking ────────────────────────────────────────

    def _poll_taskbar_visibility(self):
        visible = self._should_show()
        if visible and not self._widget_shown:
            self.root.deiconify()
            self._widget_shown = True
        elif not visible and self._widget_shown:
            self.root.withdraw()
            self._widget_shown = False
        self.root.after(VISIBILITY_POLL_MS, self._poll_taskbar_visibility)

    # ── Hover popup ──────────────────────────────────────────────────

    def _on_hover_enter(self, _e=None):
        if self._popup is None:
            self._open_popup()

    def _open_popup(self):
        self._popup = BatteryPopup(
            self.root,
            self.root.winfo_x(), self.root.winfo_y(), self.W, self.H,
            self._last_bat, self._last_label, self._last_secs,
            self._last_rate_mw, self._last_designed_mwh, self._last_full_mwh,
            quit_cb=self._quit,
            close_cb=self._close_popup,
        )
        self._watch_popup()

    def _watch_popup(self):
        """Periodically close the popup once the mouse leaves both widget and popup."""
        if self._popup is None:
            return
        px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()

        # Still over the taskbar widget?
        wx, wy = self.root.winfo_x(), self.root.winfo_y()
        if wx <= px < wx + self.W and wy <= py < wy + self.H:
            self.root.after(150, self._watch_popup)
            return

        # Still over the popup window?
        try:
            popup_win = self._popup.win
            pox = popup_win.winfo_x()
            poy = popup_win.winfo_y()
            pw_ = popup_win.winfo_width()
            ph_ = popup_win.winfo_height()
            if pox <= px < pox + pw_ and poy <= py < poy + ph_:
                self.root.after(150, self._watch_popup)
                return
        except Exception:
            pass

        self._close_popup()

    def _close_popup(self):
        if self._popup:
            self._popup.destroy()
            self._popup = None

    # ── Menu / quit ────────────────────────────────────────────────────────

    def _show_menu(self, event):
        self._menu.tk_popup(event.x_root, event.y_root)

    def _quit(self):
        self._close_popup()
        self._stop.set()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        BatteryWidget().run()
    except Exception as e:
        import traceback, sys
        traceback.print_exc()
        input("Press Enter to exit...")
        sys.exit(1)

