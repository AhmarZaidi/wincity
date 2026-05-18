"""
BatteryBar - Windows 11 taskbar widget battery monitor.
A borderless always-on-top window sitting on the taskbar.
Shows a battery icon with time remaining drawn inside it.
Right-click to quit.
"""

import ctypes
import ctypes.wintypes
import threading
import psutil
import tkinter as tk

# ── Position / size  (edit these to adjust placement) ────────────────────────
WIDGET_WIDTH      = 55    # width of the widget in pixels
WIDGET_HEIGHT     = 25  # None = auto-fit to taskbar height; or set an int (px)
OFFSET_FROM_RIGHT = 85    # px from the right edge of the taskbar (clears the clock)
OFFSET_FROM_TOP   = None  # None = auto-centre vertically; or set an int (px from taskbar top)

# ── Appearance ────────────────────────────────────────────────────────────────
UPDATE_INTERVAL = 30      # seconds between background refreshes
LOW_PCT         = 10      # battery % below which fill turns red

# ── Windows API ───────────────────────────────────────────────────────────────
user32 = ctypes.windll.user32

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
    """Return 'H:MM' or None if time is unknown/unlimited."""
    if secs is None or secs <= 0:
        return None
    if secs in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED, -1, -2):
        return None
    return f"{secs // 3600}:{(secs % 3600) // 60:02d}"


# ── Taskbar widget ────────────────────────────────────────────────────────────

class BatteryWidget:
    BG     = "#1c1c1c"
    GREEN  = "#3cc850"
    BLUE   = "#3296f0"
    RED    = "#dc3232"
    FG     = "#ffffff"
    BORDER = "#3a3a3a"

    def __init__(self):
        self._stop = threading.Event()

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg=self.BG)
        self.root.resizable(False, False)

        tb     = _get_taskbar_rect()
        tb_h   = tb.bottom - tb.top
        self.H = WIDGET_HEIGHT if WIDGET_HEIGHT is not None else max(28, tb_h - 8)
        self.W = WIDGET_WIDTH

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

        self._update_ui()
        self.root.update()

        try:
            self._apply_win_style()
        except Exception:
            pass  # styling is cosmetic — don't crash if it fails

        threading.Thread(target=self._bg_updater, daemon=True).start()

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

    def _draw(self, bat):
        c = self.canvas
        c.delete("all")
        W, H = self.W, self.H
        TRANSPARENT = "#010101"

        # Fill whole canvas with transparent colour first
        c.create_rectangle(0, 0, W, H, fill=TRANSPARENT, outline="")

        if bat is None:
            c.create_text(W // 2, H // 2, text="N/A",
                          fill="#888888", font=("Segoe UI", 8))
            return

        pct     = bat.percent
        plugged = bat.power_plugged
        time_s  = format_time(bat.secsleft)
        label   = time_s if time_s else f"{pct:.0f}%"
        color   = self.BLUE if plugged else (self.RED if pct <= LOW_PCT else self.GREEN)

        # Battery outline
        nub_w = 4
        bx0, by0 = 2, 3
        bx1, by1 = W - 2 - nub_w, H - 3
        body_w = bx1 - bx0
        body_h = by1 - by0

        # Nub
        nub_h  = max(4, body_h // 3)
        nub_y0 = by0 + (body_h - nub_h) // 2
        c.create_rectangle(bx1, nub_y0, bx1 + nub_w, nub_y0 + nub_h,
                           fill="#888888", outline="")

        # Body background
        c.create_rectangle(bx0, by0, bx1, by1,
                           outline="#888888", width=1, fill="#1a1a1a")

        # Charge fill
        fill_w = max(1, int((body_w - 2) * pct / 100))
        c.create_rectangle(bx0 + 1, by0 + 1, bx0 + 1 + fill_w, by1 - 1,
                           fill=color, outline="")

        # Text centred inside battery body — pick largest fitting size
        cx = bx0 + body_w // 2
        cy = by0 + body_h // 2
        for size in range(13, 6, -1):
            f = ("Segoe UI Semibold", size)
            tmp = c.create_text(-999, -999, text=label, font=f)
            x0, y0, x1, y1 = c.bbox(tmp)
            c.delete(tmp)
            if (x1 - x0) <= body_w - 4:
                break
        c.create_text(cx, cy, text=label, fill=self.FG, font=f)

    # ── Refresh ────────────────────────────────────────────────────────────

    def _update_ui(self):
        self._draw(get_battery())

    def _bg_updater(self):
        while not self._stop.wait(UPDATE_INTERVAL):
            self.root.after(0, self._update_ui)

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

