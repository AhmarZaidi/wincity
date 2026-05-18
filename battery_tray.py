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
FILL_RIGHT_EXTEND = 6     # extra px added to the fill's right edge (corrects visual right gap)
FONT_SIZE           = 22  # label font size in points
RENDER_SCALE        = 8   # internal supersampling (higher = crisper; 4-8 recommended)
VISIBILITY_POLL_MS  = 500 # ms between taskbar visibility checks (lower = snappier hide/show)

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


def _rrect(c, x0, y0, x1, y1, r, fill="", outline="", width=1):
    pass  # kept for compatibility; drawing now done via PIL


def _load_font(size):
    """Load best available font at given point size."""
    for name in ("segoeuisb.ttf", "segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _render_battery(W, H, bat, label=None):
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
    else:
        fill_col = (60,  200,  80, 255)

    nub_w  = 5 * S
    bx0, by0 = 2 * S, 2 * S
    bx1, by1 = sw - 2 * S - nub_w, sh - 2 * S
    body_w = bx1 - bx0
    body_h = by1 - by0
    r      = CORNER_RADIUS * S

    # Nub
    nub_h  = max(4 * S, body_h // 3)
    nub_y0 = by0 + (body_h - nub_h) // 2
    d.rounded_rectangle([bx1, nub_y0, bx1 + nub_w, nub_y0 + nub_h],
                        radius=min(r, nub_w // 2), fill=(170, 170, 170, 255))

    # Body background (outline drawn last so it always sits on top of the fill)
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=r, fill=(26, 26, 26, 255))

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
                        outline=(136, 136, 136, 255), width=S)

    # Label centred in body
    fnt  = _load_font(FONT_SIZE * S)
    cx   = bx0 + body_w // 2
    cy   = by0 + body_h // 2
    d.text((cx, cy), label, font=fnt, fill=(255, 255, 255, 255), anchor="mm")

    return img.resize((W, H), Image.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=0.5, percent=180, threshold=0)
    )


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

        batt   = _render_battery(W, H, bat, label)   # RGBA PIL image

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
                label = format_time(bat.secsleft)
            elif self._charge_rate:
                label = format_time(int((100 - bat.percent) / self._charge_rate))
        else:
            self._charge_obs  = None
            self._charge_rate = None

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

    # ── Menu / quit ────────────────────────────────────────────────────────

    def _show_menu(self, event):
        self._menu.tk_popup(event.x_root, event.y_root)

    def _quit(self):
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

