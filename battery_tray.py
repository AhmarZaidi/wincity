"""
BatteryBar - A minimal Windows 11 system tray battery monitor.
Shows time remaining on battery / time to full charge.
Green fill (discharging), Blue fill (charging), Red fill (<10%).
Hover tooltip shows live charge/discharge rate.
"""

import threading
import time
import psutil
from PIL import Image, ImageDraw, ImageFont
import pystray
from pystray import MenuItem as item


# ── Config ────────────────────────────────────────────────────────────────────
ICON_W, ICON_H = 64, 64          # tray icon canvas size
UPDATE_NORMAL   = 30              # seconds between background refreshes
UPDATE_HOVER    = 1               # seconds between hover (rate) refreshes
LOW_PCT         = 10              # threshold for red fill

# Colours
COL_OUTLINE     = (220, 220, 220, 255)
COL_BG          = (30,  30,  30,  255)
COL_GREEN       = (60,  200,  80,  255)
COL_RED         = (220,  50,  50,  255)
COL_BLUE        = (50,  140, 240,  255)
COL_TEXT        = (255, 255, 255, 255)
COL_TRANSPARENT = (0,   0,   0,   0)


# ── Battery helpers ───────────────────────────────────────────────────────────

def get_battery():
    """Return psutil battery object or None."""
    try:
        return psutil.sensors_battery()
    except Exception:
        return None


def format_seconds(secs: int) -> str:
    """Convert seconds to '1h 23m' or '45m' string."""
    if secs <= 0:
        return "–"
    h = secs // 3600
    m = (secs % 3600) // 60
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def get_rate_text(bat) -> str:
    """
    Build a live rate string.  psutil doesn't expose watts directly, so we
    use a 1-second delta on percentage to estimate drain/charge rate in %/hr.
    """
    if bat is None:
        return "No battery detected"
    pct1 = bat.percent
    time.sleep(1)
    bat2 = get_battery()
    if bat2 is None:
        return "No battery"
    pct2 = bat2.percent
    delta_pct_per_sec = pct2 - pct1          # positive = charging
    rate_pct_per_hr   = abs(delta_pct_per_sec) * 3600

    if bat2.power_plugged:
        if rate_pct_per_hr < 0.05:
            return f"Fully charged · {pct2:.1f}%"
        return f"Charging at ~{rate_pct_per_hr:.1f}%/hr · {pct2:.1f}%"
    else:
        if rate_pct_per_hr < 0.05:
            return f"Idle · {pct2:.1f}%"
        return f"Draining at ~{rate_pct_per_hr:.1f}%/hr · {pct2:.1f}%"


# ── Icon drawing ──────────────────────────────────────────────────────────────

def draw_icon(pct: float, plugged: bool, time_str: str) -> Image.Image:
    """
    Draw the tray icon:
      - Battery outline with terminal nub
      - Coloured fill proportional to pct
      - Small time text centred in the body
    """
    img = Image.new("RGBA", (ICON_W, ICON_H), COL_TRANSPARENT)
    d   = ImageDraw.Draw(img)

    # Battery body rect (leave room for nub on right)
    nub_w  = 5
    nub_h  = 14
    bdr    = 2                        # border radius
    bx0, by0 = 3,  14
    bx1, by1 = ICON_W - 3 - nub_w, ICON_H - 14

    body_w = bx1 - bx0
    body_h = by1 - by0

    # Nub (positive terminal)
    nub_x0 = bx1
    nub_y0 = by0 + (body_h - nub_h) // 2
    nub_x1 = bx1 + nub_w
    nub_y1 = nub_y0 + nub_h
    d.rounded_rectangle([nub_x0, nub_y0, nub_x1, nub_y1], radius=2, fill=COL_OUTLINE)

    # Background fill
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=bdr, fill=COL_BG, outline=COL_OUTLINE, width=2)

    # Charge fill
    pad   = 3
    fill_max_w = body_w - pad * 2
    fill_w     = max(1, int(fill_max_w * pct / 100))

    if plugged:
        fill_col = COL_BLUE
    elif pct <= LOW_PCT:
        fill_col = COL_RED
    else:
        fill_col = COL_GREEN

    fx0 = bx0 + pad
    fy0 = by0 + pad
    fx1 = fx0 + fill_w
    fy1 = by1 - pad

    if fill_w > 2:
        d.rounded_rectangle([fx0, fy0, fx1, fy1], radius=1, fill=fill_col)

    # Time text — pick biggest font that fits
    text = time_str
    font = None
    for size in [13, 11, 10, 9, 8]:
        try:
            font = ImageFont.truetype("arial.ttf", size)
        except Exception:
            font = ImageFont.load_default()
        bbox = d.textbbox((0, 0), text, font=font)
        tw   = bbox[2] - bbox[0]
        th   = bbox[3] - bbox[1]
        if tw <= body_w - 4:
            break

    cx = bx0 + body_w // 2
    cy = by0 + body_h // 2
    d.text((cx - tw // 2, cy - th // 2), text, font=font, fill=COL_TEXT)

    return img


# ── Tray application ──────────────────────────────────────────────────────────

class BatteryTray:
    def __init__(self):
        self.icon       = None
        self._stop_evt  = threading.Event()
        self._hover_active = False

        # Initial state
        bat = get_battery()
        self._last_bat  = bat
        img, title      = self._render(bat)

        self.icon = pystray.Icon(
            "BatteryBar",
            img,
            title,
            menu=pystray.Menu(
                item("BatteryBar", lambda: None, enabled=False),
                pystray.Menu.SEPARATOR,
                item("Quit", self._quit),
            )
        )

    # ── Rendering ──────────────────────────────────────────────────────────

    @staticmethod
    def _render(bat):
        if bat is None:
            img   = draw_icon(0, False, "N/A")
            title = "No battery"
            return img, title

        pct     = bat.percent
        plugged = bat.power_plugged
        secs    = bat.secsleft   # may be psutil.POWER_TIME_UNKNOWN or POWER_TIME_UNLIMITED

        if secs in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED, -1, -2):
            time_str = f"{pct:.0f}%"
        else:
            time_str = format_seconds(secs)

        img = draw_icon(pct, plugged, time_str)

        if plugged:
            state = "Charging"
            eta   = f"Full in {time_str}" if secs > 0 and secs not in (
                psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED) else "Fully charged"
            title = f"{state} · {pct:.0f}% · {eta}"
        else:
            title = f"Battery · {pct:.0f}% · {time_str} remaining"

        return img, title

    # ── Background updater ─────────────────────────────────────────────────

    def _updater(self):
        """Runs in background thread; refreshes icon every UPDATE_NORMAL sec."""
        while not self._stop_evt.wait(UPDATE_NORMAL):
            bat = get_battery()
            self._last_bat = bat
            img, title = self._render(bat)
            if self.icon:
                self.icon.icon  = img
                self.icon.title = title

    # ── Hover rate updater ─────────────────────────────────────────────────

    def _hover_updater(self):
        """
        pystray doesn't expose hover events on Windows, so we approximate
        by using a secondary fast-poll thread that updates the tooltip (title)
        every second.  The thread starts on launch and runs cheaply most of
        the time (just reading battery %).  The expensive 1-sec delta for
        rate is only computed inside get_rate_text(), which sleeps 1 s.
        Because the tooltip is only *read* when the user hovers, this is
        effectively hover-only from the user's perspective.
        """
        while not self._stop_evt.wait(0):
            bat = get_battery()
            rate_text = get_rate_text(bat)   # this sleeps 1 sec internally
            if self.icon and bat is not None:
                _, base_title = self._render(bat)
                self.icon.title = f"{base_title}\n{rate_text}"
            if self._stop_evt.is_set():
                break

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def _quit(self):
        self._stop_evt.set()
        self.icon.stop()

    def run(self):
        # Background update thread (low frequency)
        t_update = threading.Thread(target=self._updater, daemon=True)
        t_update.start()

        # Hover rate thread — runs at 1 s but only costs CPU during hover
        t_hover = threading.Thread(target=self._hover_updater, daemon=True)
        t_hover.start()

        self.icon.run()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = BatteryTray()
    app.run()
