"""
BatteryPopup — PIL-rendered hover info popup.
Pages: dashboard | settings | rows_config | apps | about
Bottom-anchored: popup expands upward, never clips below taskbar.
"""
import hashlib
import math
import os
import threading
import time
import webbrowser
from datetime import datetime, timedelta

import psutil
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk

from . import config
from . import system
from . import battery as bat_mod
from .render import load_font


# ── Row display names ─────────────────────────────────────────────────────────
ROW_LABELS = {
    "status":           "Status",
    "percentage":       "Percentage",
    "battery_estimate": "Est. Runtime",
    "time":             "Time",
    "rate":             "Rate",
    "elapsed":          "Elapsed",
    "screen_on":        "Screen On",
    "power_mode":       "Power Mode",
    "cycle_count":      "Cycle Count",
    "temperature":      "Temperature",
    "health":           "Health",
    "graph":            "Graph",
}

# Defaults for settings reset
_DEFAULTS = {
    "POPUP_REFRESH_INTERVAL": 2,
    "UPDATE_INTERVAL":        10,
    "WIDGET_WIDTH":           55,
    "WIDGET_HEIGHT":          25,
    "FONT_SIZE":              22,
    "GRAPH_HEIGHT":           140,
    "LOW_CRITICAL_PCT":       10,
}


class BatteryPopup:
    """Hover info popup — multi-page, bottom-anchored, PIL-rendered."""

    _TC     = "#020202"   # transparent key colour
    _TC_RGB = (2, 2, 2)
    _MIN_W  = 284

    # Layout in logical px
    _PX = 14; _PY = 10; _TH = 28; _SH = 13; _RH = 26; _QH = 30

    # Graph internals
    _G_MARGIN = 7; _G_LBL_H = 18; _G_CORNER = 6
    _G_FONT = 10; _G_LW = 1.5

    _IC = {
        "status":      "\uE8A1",
        "thunder":     "\uE945",
        "pct":         "\uE83F",
        "time":        "\uE916",
        "estimate":    "\uE916",
        "rate":        "\uE7EF",
        "elapsed":     "\uE81C",
        "screen":      "\uE7F4",
        "power":       "\uE7E8",
        "health":      "\uEB52",
        "cycle":       "\uE117",
        "temp":        "\uE9CA",
        "settings":    "\uE713",
        "close":       "\uE8BB",
        "apps":        "\uE179",
        "info":        "\uE946",
        "back":        "\uE72B",
        "reset":       "\uE72C",
        "chevL":       "\uE76B",
        "chevR":       "\uE76C",
        "move":        "\uE7C2",
        "check_on":    "\uE73E",
        "check_off":   "\uE739",
        "arrow_up":    "\uE74A",
        "arrow_dn":    "\uE74B",
        "minus":       "\uE738",
        "plus":        "\uE710",
        "skull":       "\uEA3A",
    }

    def __init__(self, root, wx, wy, ww, wh, bat, label, secs,
                 rate_mw, designed_mwh, full_mwh, cycle_count, temp_c,
                 elapsed_secs, history, sessions, quit_cb, close_cb,
                 move_cb, settings_saved_cb):
        self._quit_cb           = quit_cb
        self._close_cb          = close_cb
        self._move_cb           = move_cb
        self._settings_saved_cb = settings_saved_cb

        self._bat           = bat
        self._label         = label
        self._secs          = secs
        self._rate_mw       = rate_mw
        self._designed_mwh  = designed_mwh
        self._full_mwh      = full_mwh
        self._cycle_count   = cycle_count
        self._temp_c        = temp_c
        self._elapsed_secs  = elapsed_secs
        self._history       = history
        self._sessions      = sessions

        # Page state
        self.page         = "dashboard"
        self._graph_index = -1

        # Apps page — lazy-init ProcessTracker for faster popup open
        self._process_tracker    = None
        self._app_list: list     = []
        self._actual_total_watts = 0.0
        self._app_scroll         = 0
        self._app_lock           = threading.Lock()

        # About page hit regions
        self._about_hit_regions: dict = {}

        self._hover_key = None

        dark = system.is_dark_mode()
        _c = config.COLORS_DARK if dark else config.COLORS_LIGHT
        self._bg   = _c["bg"];    self._fg   = _c["fg"];   self._fg2  = _c["fg2"]
        self._bdr  = _c["border"]; self._icol = _c["icon"]; self._red  = _c["danger"]
        self._hov  = _c["hover"]
        self._acc  = (0, 120, 212) if dark else (0, 99, 177)

        s = system.dpi_scale()
        self._s  = s
        pw       = max(int(self._MIN_W * s), self._MIN_W)
        self._pw = pw
        self._wx, self._wy, self._ww, self._wh = wx, wy, ww, wh

        # Bottom anchor — popup bottom is always wy − POPUP_Y_OFFSET
        self._popup_bottom_y = wy - config.POPUP_Y_OFFSET
        self._ph             = self._compute_height(pw, s)

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", self._TC)
        self.win.configure(bg=self._TC)
        self.win.resizable(False, False)

        self._cv = tk.Canvas(self.win, width=pw, height=self._ph,
                             bg=self._TC, highlightthickness=0)
        self._cv.pack()

        # Safe defaults before first render
        self._photo  = None
        self._img_id = None
        self._bar_y0 = 0;  self._bar_y1 = 0
        self._btn_regions           = {}
        self._graph_nav             = {}
        self._settings_hit_regions  = {}
        self._rows_hit_regions      = {}
        self._apps_hit_regions      = {}

        # Show a bare rounded-rect placeholder immediately so window appears fast
        self._draw_placeholder(pw, self._ph, s)
        px_pos, py_pos = self._calc_position()
        self.win.geometry(f"{pw}x{self._ph}+{px_pos}+{py_pos}")
        self.win.update()           # ← display the window NOW

        # Full render (may take 50–100 ms) — updates the canvas in-place
        self._redraw()

        self._cv.bind("<Button-1>",   self._on_click)
        self._cv.bind("<Motion>",     self._on_motion)
        self._cv.bind("<Leave>",      self._on_leave)
        self._cv.bind("<MouseWheel>", self._on_scroll)

        try:
            hwnd  = self.win.winfo_id()
            style = system.user32.GetWindowLongW(hwnd, system.GWL_EXSTYLE)
            system.user32.SetWindowLongW(hwnd, system.GWL_EXSTYLE,
                                         style | system.WS_EX_TOOLWINDOW)
        except Exception:
            pass

    # ── Placeholder ────────────────────────────────────────────────────────────

    def _draw_placeholder(self, pw, ph, s):
        r   = config.POPUP_CORNER_RADIUS
        img = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, pw - 1, ph - 1], radius=r,
                             fill=self._bg + (255,), outline=self._bdr + (255,), width=1)
        # Tiny loading dots
        sfnt = load_font(max(9, int(11 * s)))
        d.text((pw // 2, ph // 2), "Loading…",
               font=sfnt, fill=self._fg2 + (180,), anchor="mm")
        result = Image.new("RGB", (pw, ph), self._TC_RGB)
        result.paste(img.convert("RGB"), mask=img.split()[3])
        photo = ImageTk.PhotoImage(result)
        self._photo  = photo
        self._img_id = self._cv.create_image(0, 0, anchor="nw", image=self._photo)

    # ── Height calculation ─────────────────────────────────────────────────────

    def _compute_height(self, pw, s):
        if self.page == "dashboard":
            _vis       = [r for r in config.ROWS_CONFIG if r.get("visible", True)]
            _n_rows    = sum(1 for r in _vis if r.get("id") != "graph")
            _has_graph = any(r.get("id") == "graph" for r in _vis)
            ph = int((self._PY + self._TH + self._SH
                      + _n_rows * self._RH
                      + (_has_graph * config.GRAPH_HEIGHT)
                      + self._SH + self._QH + self._PY) * s)
        elif self.page == "settings":
            # 7 stepper rows (RH+4 each) + customize_rows + move_icon (RH each)
            ph = int((self._PY + self._TH + self._SH
                      + 7 * (self._RH + 4)
                      + 2 * self._RH
                      + self._SH + self._QH + self._PY) * s)
        elif self.page == "rows_config":
            n = len(config.ROWS_CONFIG)
            ph = int((self._PY + self._TH + self._SH
                      + n * self._RH
                      + self._SH + self._QH + self._PY) * s)
        elif self.page == "apps":
            # header + 8 app rows + total row + some padding
            ph = int((self._PY + self._TH + self._SH
                      + 11 * self._RH
                      + self._SH + self._QH + self._PY) * s)
        elif self.page == "about":
            ph = int((self._PY + self._TH + self._SH
                      + 9 * self._RH
                      + self._SH + self._QH + self._PY) * s)
        else:
            ph = int(400 * s)
        return ph

    # ── Bottom-anchored positioning ────────────────────────────────────────────

    def _calc_position(self):
        """Return (px, py) keeping popup bottom at _popup_bottom_y."""
        pw, ph = self._pw, self._ph
        py_pos = self._popup_bottom_y - ph
        px_pos = self._wx + self._ww // 2 - pw // 2
        sw     = self.win.winfo_screenwidth()
        sh     = self.win.winfo_screenheight()
        px_pos = max(4, min(px_pos, sw - pw - 4))
        py_pos = max(4, min(py_pos, sh - ph - 4))
        return px_pos, py_pos

    # ── Fonts ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _mdl2_font(size):
        candidates = [
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segmdl2.ttf"),
            "segmdl2.ttf",
        ]
        for p in candidates:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
        return load_font(size)

    # ── Master redraw ──────────────────────────────────────────────────────────

    def _redraw(self):
        s  = self._s
        pw = self._pw
        ph = self._compute_height(pw, s)

        if ph != self._ph:
            self._ph = ph
            self._cv.config(height=ph)
            px_pos, py_pos = self._calc_position()
            self.win.geometry(f"{pw}x{ph}+{px_pos}+{py_pos}")

        img   = self._render(pw, ph, s)
        photo = ImageTk.PhotoImage(img)
        self._photo = photo
        if self._img_id is not None:
            self._cv.itemconfig(self._img_id, image=self._photo)
        else:
            self._img_id = self._cv.create_image(0, 0, anchor="nw", image=self._photo)

    # ── Top-level render dispatcher ────────────────────────────────────────────

    def _render(self, w, h, s):
        r = config.POPUP_CORNER_RADIUS

        def a(rgb):
            return rgb[:3] + (255,)

        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=r,
                             fill=a(self._bg), outline=a(self._bdr), width=1)

        tfnt = load_font(int(config.POPUP_TITLE_SIZE * s))
        nfnt = load_font(int(config.POPUP_TEXT_SIZE  * s))
        ifnt = self._mdl2_font(int(config.POPUP_ICON_SIZE * s))
        sfnt = load_font(int(max(9, 11 * s)))

        px = int(self._PX * s)
        y  = int(self._PY * s)
        ty = y + int(self._TH * s) // 2

        # ── Title bar ─────────────────────────────────────────────────────
        page_titles = {
            "dashboard":  ("WinCity",            "v1.0.0"),
            "settings":   ("Settings",            None),
            "rows_config":("Customize Rows",      None),
            "apps":       ("App Battery Usage",   None),
            "about":      ("About WinCity",       None),
        }
        title, subtitle = page_titles.get(self.page, (self.page, None))
        d.text((px, ty), title, font=tfnt, fill=a(self._fg), anchor="lm")
        if subtitle:
            d.text((w - px, ty), subtitle, font=nfnt, fill=a(self._fg2), anchor="rm")
        y += int(self._TH * s)

        # ── Separator ─────────────────────────────────────────────────────
        d.line([(px, y + 4), (w - px, y + 4)], fill=a(self._bdr), width=1)
        y += int(self._SH * s)

        # ── Page body ─────────────────────────────────────────────────────
        if self.page == "dashboard":
            y = self._render_dashboard(d, img, px, y, w, s, a, ifnt, nfnt)
        elif self.page == "settings":
            y = self._render_settings(d, px, y, w, s, a, ifnt, nfnt, sfnt)
        elif self.page == "rows_config":
            y = self._render_rows_config(d, px, y, w, s, a, ifnt, nfnt)
        elif self.page == "apps":
            y = self._render_apps(d, px, y, w, s, a, ifnt, nfnt)
        elif self.page == "about":
            y = self._render_about(d, px, y, w, s, a, ifnt, nfnt, tfnt, sfnt)

        # ── Bottom separator ───────────────────────────────────────────────
        d.line([(px, y + 4), (w - px, y + 4)], fill=a(self._bdr), width=1)
        y += int(self._SH * s)

        self._render_bottom_bar(d, px, y, w, s, a, ifnt)

        result = Image.new("RGB", (w, h), self._TC_RGB)
        result.paste(img.convert("RGB"), mask=img.split()[3])
        return result

    # ── Dashboard page ─────────────────────────────────────────────────────────

    def _render_dashboard(self, d, img, px, y, w, s, a, ifnt, nfnt):
        for row in self._rows():
            if row[0] == "graph":
                self._draw_graph(d, img, px, y, w, s, a)
                y += int(config.GRAPH_HEIGHT * s)
                continue
            icon, name, value = row[1], row[2], row[3]
            val_icon = row[4] if len(row) > 4 else None
            my = y + int(self._RH * s) // 2
            d.text((px + int(11 * s), my), icon, font=ifnt, fill=a(self._icol), anchor="mm")
            d.text((px + int(26 * s), my), name, font=nfnt, fill=a(self._fg2), anchor="lm")
            if val_icon:
                txt_w = int(d.textlength(value, font=nfnt))
                ico_w = int(config.POPUP_ICON_SIZE * s)
                gap   = int(4 * s)
                blk_x = w - px - txt_w - gap - ico_w
                d.text((blk_x + ico_w // 2, my), val_icon,
                       font=ifnt, fill=a(self._fg), anchor="mm")
                d.text((blk_x + ico_w + gap, my), value,
                       font=nfnt, fill=a(self._fg), anchor="lm")
            else:
                d.text((w - px, my), value, font=nfnt, fill=a(self._fg), anchor="rm")
            y += int(self._RH * s)
        return y

    def _rows(self):
        bat = self._bat
        if bat is None:
            yield ("status", self._IC["status"], "Status", "Loading…")
            return

        if self._full_mwh:
            remaining_wh = self._full_mwh * bat.percent / 100 / 1000
            pct = f"{bat.percent:.0f}% ({remaining_wh:.1f} Wh)"
        else:
            pct = f"{bat.percent:.0f}%"

        t_lbl = "Time to Full" if bat.power_plugged else "Time Left"
        t_val = bat_mod.format_time_long(self._secs) or ("Full" if bat.percent >= 100 else "\u2014")
        status_extra = (self._IC["thunder"],) if bat.power_plugged else ()

        # Screen-on time via system uptime
        sot = bat_mod.get_screen_on_seconds()
        if sot is not None:
            h_, rem = divmod(sot, 3600)
            m_ = rem // 60
            screen_str = f"{h_}h {m_:02d}m" if h_ > 0 else f"{m_}m"
        else:
            screen_str = "\u2014"

        _data = {
            "status":           (self._IC["status"],   "Status",
                                 "Charging" if bat.power_plugged else "Discharging") + status_extra,
            "percentage":       (self._IC["pct"],      "Percentage",     pct),
            "time":             (self._IC["time"],     t_lbl,            t_val),
            "rate":             (self._IC["rate"],     "Rate",           bat_mod.fmt_rate(self._rate_mw)),
            "elapsed":          (self._IC["elapsed"],  "Elapsed",        bat_mod.format_time_long(self._elapsed_secs) or "\u2014"),
            "screen_on":        (self._IC["screen"],   "Screen On",      screen_str),
            "power_mode":       (self._IC["power"],    "Power Mode",     system.get_power_mode()),
            "cycle_count":      (self._IC["cycle"],    "Cycle Count",    str(self._cycle_count) if self._cycle_count is not None else "\u2014"),
            "temperature":      (self._IC["temp"],     "Temperature",    f"{self._temp_c} \u00b0C" if self._temp_c is not None else "\u2014"),
            "health":           (self._IC["health"],   "Health",         bat_mod.fmt_health(self._designed_mwh, self._full_mwh)),
            "battery_estimate": (self._IC["estimate"], "Est. Runtime",   self._battery_estimate_str()),
        }

        for entry in config.ROWS_CONFIG:
            rid = entry.get("id")
            if not entry.get("visible", True):
                continue
            if rid == "graph":
                yield ("graph", None, None, None)
            elif rid in _data:
                yield (rid,) + _data[rid]

    def _battery_estimate_str(self):
        """Estimate runtime to 0% (discharge) or 100% (charge) from rate."""
        bat = self._bat
        if bat is None or self._rate_mw is None:
            return "\u2014"
        rate_abs = abs(self._rate_mw)
        if rate_abs < 50:
            return "\u2014"
        if not self._full_mwh:
            return "\u2014"
        if bat.power_plugged:
            remaining_mwh = self._full_mwh * (100 - bat.percent) / 100
        else:
            remaining_mwh = self._full_mwh * bat.percent / 100
        hours = remaining_mwh / rate_abs
        secs  = int(hours * 3600)
        return bat_mod.format_time_long(secs) or "\u2014"

    # ── Graph ──────────────────────────────────────────────────────────────────

    def _draw_graph(self, d, img, px, y, w, s, a):
        gh    = int(config.GRAPH_HEIGHT * s)
        mg    = int(self._G_MARGIN * s)
        h_lbl = int(self._G_LBL_H * s)
        cr    = int(self._G_CORNER * s)

        cx0, cy0 = px, y + int(4 * s)
        cx1, cy1 = w - px, cy0 + gh - int(8 * s)

        dark    = (self._bg[0] < 128)
        cont_bg = (44, 44, 50) if dark else (205, 207, 215)

        # ── Nav arrows (top-right of graph box) ──────────────────────────
        arrow_r  = max(14, int(config.POPUP_ICON_SIZE * s))
        ifnt_sm  = self._mdl2_font(max(12, int(13 * s)))
        nav_y    = cy0 + mg
        nav_rx1  = cx1 - int(4 * s)
        nav_rx0  = nav_rx1 - arrow_r
        nav_lx1  = nav_rx0 - int(4 * s)
        nav_lx0  = nav_lx1 - arrow_r

        self._graph_nav = {
            "left":  (nav_lx0, nav_y, nav_lx1, nav_y + arrow_r),
            "right": (nav_rx0, nav_y, nav_rx1, nav_y + arrow_r),
        }

        # ── Determine session data ────────────────────────────────────────
        if self._graph_index == -1:
            hist        = self._history
            bat         = self._bat
            elapsed     = self._elapsed_secs or 0
            secs_r      = self._secs
            is_charging = bat.power_plugged if bat else False
            sess_start_ep = time.time() - elapsed
            sess_end_ep   = None
        else:
            idx      = self._graph_index
            sessions = self._sessions
            if not sessions or idx < 0 or idx >= len(sessions):
                hist, bat, elapsed, secs_r, is_charging = [], None, 0, None, False
                sess_start_ep = sess_end_ep = None
            else:
                sess = sessions[idx]
                pts  = sess.get("points", [])
                now_mono  = time.monotonic()
                now_epoch = time.time()
                hist = [(now_mono - (now_epoch - t), p, bool(pl)) for t, p, pl in pts]
                bat         = None
                elapsed     = int(sess.get("end", 0) - sess.get("start", 0))
                secs_r      = None
                is_charging = (sess.get("type") == "charging")
                sess_start_ep = sess.get("start")
                sess_end_ep   = sess.get("end")

        current_pct = hist[-1][1] if hist else (bat.percent if bat else 50)

        # ── Colors: match widget fill colors ─────────────────────────────
        cw = config.COLORS_WIDGET
        if is_charging:
            base = cw.get("fill_charging", (50, 150, 240))
        elif current_pct <= getattr(config, "LOW_CRITICAL_PCT", 10):
            base = cw.get("fill_low", (220, 50, 50))
        elif current_pct <= config.LOW_PCT:
            base = cw.get("fill_saver", (240, 190, 40))
        else:
            base = cw.get("fill_normal", (60, 200, 80))
        base     = base[:3]
        fill_col = base + (90,)
        line_col = base + (230,)

        # ── Plot geometry ─────────────────────────────────────────────────
        if (secs_r is None or secs_r <= 0
                or secs_r in (psutil.POWER_TIME_UNKNOWN,
                               psutil.POWER_TIME_UNLIMITED, -1, -2)):
            secs_right = 0
        else:
            secs_right = int(secs_r)

        total_s = max(1, elapsed + secs_right)
        ppx0 = cx0 + mg;  ppx1 = cx1 - mg
        ppy0 = cy0 + mg;  ppy1 = cy1 - mg - h_lbl
        pw_  = max(1, ppx1 - ppx0)
        ph_  = max(1, ppy1 - ppy0)

        def pct_y(pct_):
            return ppy1 - int(max(0.0, min(100.0, pct_)) / 100.0 * ph_)

        now_px  = ppx0 + int(elapsed / total_s * pw_)
        cur_y   = pct_y(current_pct)

        if bat is None and not hist:
            sfnt2 = load_font(int(11 * s))
            mid_x = (cx0 + cx1) // 2
            mid_y = cy0 + mg + (cy1 - cy0) // 2
            d.text((mid_x, mid_y), "No data",
                   font=sfnt2, fill=a(self._fg2), anchor="mm")
            d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=cr,
                                 outline=a(self._bdr), width=1)
        else:
            if hist and len(hist) >= 2:
                now_mono_ = time.monotonic()
                def mono_x(mono_t):
                    off = elapsed - (now_mono_ - mono_t)
                    return ppx0 + int(max(0.0, min(1.0, off / total_s)) * pw_)

                pts_hist = [(mono_x(t), pct_y(p)) for t, p, _ in hist]

                overlay = Image.new("RGBA", img.size, cont_bg + (255,))
                od      = ImageDraw.Draw(overlay)

                left_wall = [(ppx0, ppy1)]
                if pts_hist[0][0] > ppx0:
                    left_wall.append((ppx0, pts_hist[0][1]))
                poly = left_wall + pts_hist + [(now_px, ppy1)]
                od.polygon(poly, fill=fill_col)

                lw       = max(1, int(self._G_LW * s))
                line_pts = ([(ppx0, pts_hist[0][1])] if pts_hist[0][0] > ppx0 else []) \
                           + pts_hist + [(now_px, cur_y)]
                od.line(line_pts, fill=line_col, width=lw)

                clip_mask = Image.new("L", img.size, 0)
                ImageDraw.Draw(clip_mask).rounded_rectangle(
                    [cx0 + 1, cy0 + 1, cx1 - 1, cy1 - 1],
                    radius=max(1, cr - 1), fill=255)
                img.paste(overlay, mask=clip_mask)
            else:
                sfnt2 = load_font(int(11 * s))
                mid_x = (cx0 + cx1) // 2
                mid_y = cy0 + mg + ph_ // 2
                d.text((mid_x, mid_y), "Collecting data…",
                       font=sfnt2, fill=a(self._fg2), anchor="mm")

            if secs_right > 0 and bat is not None:
                end_y = pct_y(100.0 if is_charging else 0.0)
                self._dotted_line(d, now_px, cur_y, ppx1, end_y, line_col, s)

            d.line([(ppx0, ppy0), (ppx0, ppy1)], fill=a(self._fg2), width=1)
            d.line([(ppx0, ppy1), (ppx1, ppy1)], fill=a(self._fg2), width=1)
            d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=cr,
                                 outline=a(self._bdr), width=1)

            lfnt = load_font(max(self._G_FONT, int(self._G_FONT * s)))

            # "100%" — top-LEFT of plot area
            d.text((ppx0 + int(3 * s), ppy0 + int(2 * s)), "100%",
                   font=lfnt, fill=a(self._fg), anchor="lt")

            # Start pct label (left side, inside)
            _sp  = hist[0][1] if (hist and len(hist) >= 1) else current_pct
            _spy = pct_y(_sp + 8)
            if _spy > ppy0 + int(15 * s):
                d.text((ppx0 + int(4 * s), _spy), f"{_sp:.0f}%",
                       font=lfnt, fill=a(self._fg2), anchor="lm")

            # ── Timeline labels below x-axis ─────────────────────────────
            now_dt = datetime.now()
            lbl_y  = ppy1 + int(3 * s)

            if self._graph_index == -1:
                # Live session: start time left, estimated end right, duration center
                if elapsed > 0 and sess_start_ep:
                    st_dt = datetime.fromtimestamp(sess_start_ep)
                    d.text((ppx0, lbl_y), bat_mod.fmt_hm(st_dt),
                           font=lfnt, fill=a(self._fg2), anchor="lt")
                if secs_right > 0:
                    end_dt = now_dt + timedelta(seconds=secs_right)
                    d.text((ppx1, lbl_y), bat_mod.fmt_hm(end_dt),
                           font=lfnt, fill=a(self._fg2), anchor="rt")
                # duration so far
                if elapsed > 60:
                    h_, m_ = divmod(int(elapsed), 3600)
                    dur_str = f"{h_}h {m_//60:02d}m" if h_ else f"{m_//60}m"
                    d.text(((ppx0 + ppx1) // 2, lbl_y), dur_str,
                           font=lfnt, fill=a(self._fg2), anchor="mt")
            else:
                # Historical session: start, end, duration
                if sess_start_ep:
                    st_dt = datetime.fromtimestamp(sess_start_ep)
                    d.text((ppx0, lbl_y), bat_mod.fmt_hm(st_dt),
                           font=lfnt, fill=a(self._fg2), anchor="lt")
                if sess_end_ep:
                    en_dt = datetime.fromtimestamp(sess_end_ep)
                    d.text((ppx1, lbl_y), bat_mod.fmt_hm(en_dt),
                           font=lfnt, fill=a(self._fg2), anchor="rt")
                dur_s = elapsed
                if dur_s > 60:
                    h_, m_ = divmod(int(dur_s), 3600)
                    dur_str = f"{h_}h {m_//60:02d}m" if h_ else f"{m_//60}m"
                    d.text(((ppx0 + ppx1) // 2, lbl_y), dur_str,
                           font=lfnt, fill=a(self._fg2), anchor="mt")

        # ── Session / Live label — TOP-RIGHT of plot area ─────────────────
        lfnt2 = load_font(max(self._G_FONT, int(self._G_FONT * s)))
        if self._graph_index == -1:
            lbl_txt = "Live"
        elif self._sessions and 0 <= self._graph_index < len(self._sessions):
            s_type  = self._sessions[self._graph_index].get("type", "")
            lbl_txt = "Charging" if s_type == "charging" else "Discharging"
        else:
            lbl_txt = ""
        if lbl_txt:
            d.text((ppx1 - int(2 * s), ppy0 + int(2 * s)),
                   lbl_txt, font=lfnt2, fill=a(self._acc), anchor="rt")

        # ── Nav arrows ────────────────────────────────────────────────────
        can_left  = (self._graph_index == -1 and bool(self._sessions)) \
                    or (0 < self._graph_index)
        can_right = self._graph_index != -1
        l_col = a(self._fg)   if can_left  else a(self._fg2)
        r_col = a(self._acc)  if can_right else a(self._fg2)
        nav_my = nav_y + arrow_r // 2
        d.text(((nav_lx0 + nav_lx1) // 2, nav_my), self._IC["chevL"],
               font=ifnt_sm, fill=l_col, anchor="mm")
        d.text(((nav_rx0 + nav_rx1) // 2, nav_my), self._IC["chevR"],
               font=ifnt_sm, fill=r_col, anchor="mm")

    # ── Settings page ──────────────────────────────────────────────────────────

    def _render_settings(self, d, px, y, w, s, a, ifnt, nfnt, sfnt):
        rh = int((self._RH + 4) * s)
        ix = int(11 * s)

        settings_rows = [
            ("POPUP_REFRESH_INTERVAL", "Popup Refresh",  "s",  0.5, 30,  0.5),
            ("UPDATE_INTERVAL",        "Icon Refresh",   "s",  1,   60,  1),
            ("WIDGET_WIDTH",           "Icon Width",     "px", 20,  200, 1),
            ("WIDGET_HEIGHT",          "Icon Height",    "px", 12,  100, 1),
            ("FONT_SIZE",              "Font Size",      "pt", 8,   72,  1),
            ("GRAPH_HEIGHT",           "Graph Height",   "px", 80,  300, 10),
            ("LOW_CRITICAL_PCT",       "Critical Low %", "%",  5,   50,  1),
        ]
        self._settings_hit_regions = {}

        for key, label, unit, mn, mx, step in settings_rows:
            val = getattr(config, key, _DEFAULTS.get(key, 0))
            my  = y + rh // 2
            d.text((px + ix, my), label, font=nfnt, fill=a(self._fg2), anchor="lm")

            val_str = f"{val:.0f}{unit}" if step >= 1 else f"{val:.1f}{unit}"
            btn_w   = int(22 * s)
            gap     = int(4 * s)
            val_tw  = int(d.textlength(val_str, font=sfnt)) + int(8 * s)
            x0      = w - px - (btn_w + gap + val_tw + gap + btn_w + gap + int(20 * s))

            # [-]
            m_x0, m_x1 = x0, x0 + btn_w
            hov_m = self._hover_key == (key, "minus")
            if hov_m:
                d.rounded_rectangle([m_x0, y + int(3 * s), m_x1, y + rh - int(3 * s)],
                                    radius=int(4 * s), fill=a(self._hov))
            d.text(((m_x0 + m_x1) // 2, my), self._IC["minus"],
                   font=ifnt, fill=a(self._fg if hov_m else self._icol), anchor="mm")

            # value text
            v_cx = m_x1 + gap + val_tw // 2
            d.text((v_cx, my), val_str, font=sfnt, fill=a(self._fg), anchor="mm")

            # [+]
            p_x0 = m_x1 + gap + val_tw + gap
            p_x1 = p_x0 + btn_w
            hov_p = self._hover_key == (key, "plus")
            if hov_p:
                d.rounded_rectangle([p_x0, y + int(3 * s), p_x1, y + rh - int(3 * s)],
                                    radius=int(4 * s), fill=a(self._hov))
            d.text(((p_x0 + p_x1) // 2, my), self._IC["plus"],
                   font=ifnt, fill=a(self._fg if hov_p else self._icol), anchor="mm")

            # [reset]
            rst_x0 = p_x1 + gap
            rst_x1 = rst_x0 + int(20 * s)
            hov_r  = self._hover_key == (key, "reset")
            d.text(((rst_x0 + rst_x1) // 2, my), self._IC["reset"],
                   font=ifnt, fill=a(self._acc if hov_r else self._fg2), anchor="mm")

            self._settings_hit_regions[key] = {
                "minus": (m_x0, y, m_x1, y + rh),
                "plus":  (p_x0, y, p_x1, y + rh),
                "reset": (rst_x0, y, rst_x1, y + rh),
            }
            y += rh

        # "Customize Rows" button
        rh2 = int(self._RH * s)
        my  = y + rh2 // 2
        hov_cr = self._hover_key == "customize_rows"
        if hov_cr:
            d.rounded_rectangle([px, y + int(2 * s), w - px, y + rh2 - int(2 * s)],
                                 radius=int(6 * s), fill=a(self._hov))
        d.text((px + ix, my), "Customize Rows",
               font=nfnt, fill=a(self._fg), anchor="lm")
        d.text((w - px, my), ">", font=nfnt, fill=a(self._fg2), anchor="rm")
        self._settings_hit_regions["customize_rows"] = (px, y, w - px, y + rh2)
        y += rh2

        # "Move Icon" button
        hov_mv = self._hover_key == "move_icon"
        my2    = y + rh2 // 2
        if hov_mv:
            d.rounded_rectangle([px, y + int(2 * s), w - px, y + rh2 - int(2 * s)],
                                 radius=int(6 * s), fill=a(self._hov))
        d.text((px + ix, my2), self._IC["move"],
               font=ifnt, fill=a(self._fg if hov_mv else self._icol), anchor="mm")
        d.text((px + ix * 2 + int(4 * s), my2), "Move Icon",
               font=nfnt, fill=a(self._fg), anchor="lm")
        self._settings_hit_regions["move_icon"] = (px, y, w - px, y + rh2)
        y += rh2

        return y

    # ── Rows config page ───────────────────────────────────────────────────────

    def _render_rows_config(self, d, px, y, w, s, a, ifnt, nfnt):
        rh = int(self._RH * s)
        ix = int(11 * s)
        self._rows_hit_regions = {}

        for i, row in enumerate(config.ROWS_CONFIG):
            rid     = row.get("id", "")
            visible = row.get("visible", True)
            lbl     = ROW_LABELS.get(rid, rid)
            my      = y + rh // 2

            chk_ic  = self._IC["check_on"] if visible else self._IC["check_off"]
            chk_col = a(self._acc) if visible else a(self._fg2)
            d.text((px + ix, my), chk_ic, font=ifnt, fill=chk_col, anchor="mm")
            d.text((px + ix + int(18 * s), my), lbl,
                   font=nfnt, fill=a(self._fg if visible else self._fg2), anchor="lm")

            arrow_w = int(20 * s)
            gap     = int(4 * s)
            dn_x0   = w - px - arrow_w
            dn_x1   = dn_x0 + arrow_w
            up_x0   = dn_x0 - gap - arrow_w
            up_x1   = up_x0 + arrow_w

            hov_up = self._hover_key == (i, "up")
            hov_dn = self._hover_key == (i, "down")
            up_col = a(self._fg if hov_up else self._icol) if i > 0 else a(self._fg2)
            dn_col = a(self._fg if hov_dn else self._icol) \
                     if i < len(config.ROWS_CONFIG) - 1 else a(self._fg2)

            d.text(((up_x0 + up_x1) // 2, my), self._IC["arrow_up"],
                   font=ifnt, fill=up_col, anchor="mm")
            d.text(((dn_x0 + dn_x1) // 2, my), self._IC["arrow_dn"],
                   font=ifnt, fill=dn_col, anchor="mm")

            self._rows_hit_regions[i] = {
                "toggle": (px, y, w - px - arrow_w * 2 - gap, y + rh),
                "up":     (up_x0, y, up_x1, y + rh),
                "down":   (dn_x0, y, dn_x1, y + rh),
            }
            y += rh

        return y

    # ── Apps page ─────────────────────────────────────────────────────────────

    def _render_apps(self, d, px, y, w, s, a, ifnt, nfnt):
        rh      = int(self._RH * s)
        icon_r  = max(8, int(9 * s))
        self._apps_hit_regions = {}

        # Header
        hdr_y = y + rh // 2
        d.text((px + int(28 * s), hdr_y), "Process",
               font=nfnt, fill=a(self._fg2), anchor="lm")
        d.text((w - px - int(24 * s), hdr_y), "Watts",
               font=nfnt, fill=a(self._fg2), anchor="rm")
        y += rh

        visible_rows = 8
        with self._app_lock:
            items        = list(self._app_list)
            actual_total = self._actual_total_watts

        start = self._app_scroll
        end   = start + visible_rows

        for idx, proc in enumerate(items[start:end]):
            my    = y + rh // 2
            name  = proc.get("name", "?")
            watts = proc.get("watts", 0.0)
            pid   = proc.get("pid", 0)
            w_str = f"{watts:.2f}W"

            row_key  = ("app_row", start + idx)
            hov_row  = self._hover_key == row_key
            if hov_row:
                d.rounded_rectangle([px, y + int(1 * s), w - px, y + rh - int(1 * s)],
                                    radius=int(4 * s), fill=a(self._hov))

            # Colored-initial icon circle
            col = self._proc_color(name)
            ix0 = px + int(4 * s)
            d.ellipse([ix0 - icon_r, my - icon_r, ix0 + icon_r, my + icon_r],
                      fill=col + (210,))
            letter  = name[0].upper() if name else "?"
            lfnt_sm = load_font(max(7, int(8 * s)))
            d.text((ix0, my), letter, font=lfnt_sm, fill=(255, 255, 255, 255), anchor="mm")

            # Kill button (right edge)
            kill_w  = int(22 * s)
            kill_x0 = w - px - kill_w
            kill_x1 = w - px
            hov_kll = self._hover_key == ("kill", start + idx)
            d.text(((kill_x0 + kill_x1) // 2, my), self._IC["skull"],
                   font=ifnt,
                   fill=a(self._red if hov_kll else (self._icol if hov_row else self._fg2)),
                   anchor="mm")

            disp_name = (name[:20] + "…") if len(name) > 21 else name
            d.text((px + int(18 * s), my), disp_name,
                   font=nfnt, fill=a(self._fg), anchor="lm")
            d.text((kill_x0 - int(4 * s), my), w_str,
                   font=nfnt, fill=a(self._fg), anchor="rm")

            self._apps_hit_regions[start + idx] = {
                "row":  (px, y, kill_x0, y + rh),
                "kill": (kill_x0, y, kill_x1, y + rh),
                "pid":  pid,
            }
            y += rh

        # Scroll indicators
        if self._app_scroll > 0:
            d.text((w // 2, y - rh * visible_rows - int(4 * s)),
                   self._IC["arrow_up"], font=ifnt, fill=a(self._fg2), anchor="mm")
        if end < len(items):
            d.text((w // 2, y + int(4 * s)),
                   self._IC["arrow_dn"], font=ifnt, fill=a(self._fg2), anchor="mm")
            y += int(14 * s)

        # Pad unused rows
        remaining = visible_rows - min(visible_rows, len(items[start:end]))
        y += remaining * rh

        # ── Total wattage footer ──────────────────────────────────────────
        if items:
            sep_y = y + int(2 * s)
            d.line([(px, sep_y), (w - px, sep_y)], fill=a(self._bdr), width=1)
            y += int(6 * s)
            tot_y = y + rh // 2

            computed = sum(p.get("watts", 0.0) for p in items)
            diff_pct = (abs(computed - actual_total) / max(actual_total, 0.1)) * 100
            warn     = diff_pct > 20

            tot_str = f"Total: {computed:.2f} W"
            msr_str = f"({actual_total:.2f} W meas.)"
            d.text((px + int(8 * s), tot_y), tot_str,
                   font=nfnt, fill=a(self._fg), anchor="lm")
            warn_col = self._red if warn else self._fg2
            d.text((w - px, tot_y), msr_str,
                   font=nfnt, fill=a(warn_col), anchor="rm")
            if warn:
                d.text((w - px - int(d.textlength(msr_str, font=nfnt)) - int(6 * s),
                        tot_y - int(4 * s)), "⚠",
                       font=nfnt, fill=a(self._red), anchor="rm")
            y += rh

        return y

    # ── About page ─────────────────────────────────────────────────────────────

    def _render_about(self, d, px, y, w, s, a, ifnt, nfnt, tfnt, sfnt):
        self._about_hit_regions = {}
        rh = int(self._RH * s)

        # App name + tagline
        cx = w // 2
        d.text((cx, y + rh // 2), "WinCity Battery Monitor",
               font=nfnt, fill=a(self._fg), anchor="mm")
        y += rh
        d.text((cx, y + int(9 * s)), "v1.0.0",
               font=sfnt, fill=a(self._fg2), anchor="mm")
        y += rh // 2 + int(4 * s)

        # Feature bullets
        bullets = [
            "Floating battery icon for Windows 11",
            "Live stats \u2022 Session graphs \u2022 Per-app wattage",
            "Fully configurable \u2022 Dark & Light mode",
        ]
        bfnt = load_font(max(9, int(10 * s)))
        for line in bullets:
            d.text((cx, y + int(10 * s)), line,
                   font=bfnt, fill=a(self._fg2), anchor="mm")
            y += int(18 * s)
        y += int(8 * s)

        # GitHub + Donate buttons
        btn_w = (w - 2 * px - int(8 * s)) // 2

        gh_x0, gh_x1 = px, px + btn_w
        gh_my = y + rh // 2
        hov_gh = self._hover_key == "about_github"
        gh_fill = a(self._hov) if hov_gh else None
        if gh_fill:
            d.rounded_rectangle([gh_x0, y, gh_x1, y + rh],
                                 radius=int(6 * s), fill=gh_fill)
        d.rounded_rectangle([gh_x0, y, gh_x1, y + rh],
                             radius=int(6 * s), outline=a(self._bdr), width=1)
        d.text((gh_x0 + int(10 * s), gh_my), self._IC["apps"],
               font=ifnt, fill=a(self._icol), anchor="lm")
        d.text(((gh_x0 + gh_x1) // 2 + int(6 * s), gh_my), "GitHub",
               font=nfnt, fill=a(self._fg), anchor="mm")
        self._about_hit_regions["github"] = (gh_x0, y, gh_x1, y + rh)

        don_x0 = px + btn_w + int(8 * s)
        don_x1 = w - px
        don_my  = y + rh // 2
        hov_don = self._hover_key == "about_donate"
        don_fill = a(self._hov) if hov_don else None
        if don_fill:
            d.rounded_rectangle([don_x0, y, don_x1, y + rh],
                                 radius=int(6 * s), fill=don_fill)
        d.rounded_rectangle([don_x0, y, don_x1, y + rh],
                             radius=int(6 * s), outline=a(self._acc), width=1)
        d.text(((don_x0 + don_x1) // 2, don_my), "\u2615 Donate",
               font=nfnt, fill=a(self._acc), anchor="mm")
        self._about_hit_regions["donate"] = (don_x0, y, don_x1, y + rh)

        y += rh + int(4 * s)

        # GitHub URL label
        url_fnt = load_font(max(8, int(9 * s)))
        d.text((cx, y + int(8 * s)),
               "github.com/AhmarZaidi/wincity",
               font=url_fnt, fill=a(self._fg2), anchor="mm")
        y += rh // 2

        return y

    # ── Bottom button bar ─────────────────────────────────────────────────────

    def _render_bottom_bar(self, d, px, y, w, s, a, ifnt):
        b     = int(self._QH * s)
        bar_y = y + b // 2
        gap   = int(6 * s)

        if self.page == "dashboard":
            # Left: settings, apps — Right: about, quit
            self._btn_regions = {
                "settings": (px,                 px + b),
                "apps":     (px + b + gap,        px + 2 * b + gap),
                "about":    (w - px - 2 * b - gap, w - px - b - gap),
                "quit":     (w - px - b,           w - px),
            }
            btns = [
                ("settings", self._IC["settings"], False),
                ("apps",     self._IC["apps"],     False),
                ("about",    self._IC["info"],     False),
                ("quit",     self._IC["close"],    True),
            ]
        else:
            self._btn_regions = {
                "back": (px,         px + b),
                "quit": (w - px - b, w - px),
            }
            btns = [
                ("back", self._IC["back"],  False),
                ("quit", self._IC["close"], True),
            ]

        for btn_key, glyph, is_quit in btns:
            bx0, bx1 = self._btn_regions[btn_key]
            cx_      = (bx0 + bx1) // 2
            hov      = (self._hover_key == btn_key)
            if hov:
                d.rounded_rectangle([bx0, y + int(2 * s), bx1, y + b - int(2 * s)],
                                    radius=int(4 * s), fill=a(self._hov))
            ic_col = self._red if is_quit else (self._fg if hov else self._icol)
            d.text((cx_, bar_y), glyph, font=ifnt, fill=a(ic_col), anchor="mm")

        self._bar_y0 = y
        self._bar_y1 = y + b

    # ── Interaction ────────────────────────────────────────────────────────────

    def _hit_bottom_bar(self, x, y):
        if not (self._bar_y0 <= y < self._bar_y1):
            return None
        for key, (x0, x1) in self._btn_regions.items():
            if x0 <= x < x1:
                return key
        return None

    def _hit_graph_nav(self, x, y):
        for key, (x0, y0, x1, y1) in self._graph_nav.items():
            if x0 <= x < x1 and y0 <= y < y1:
                return key
        return None

    def _on_click(self, event):
        ex, ey = event.x, event.y

        btn = self._hit_bottom_bar(ex, ey)
        if btn == "quit":
            self._quit_cb(); return
        if btn == "settings" and self.page == "dashboard":
            self.page = "settings"; self._hover_key = None; self._redraw(); return
        if btn == "apps" and self.page == "dashboard":
            self.page = "apps"; self._hover_key = None
            self._start_apps_updater(); self._redraw(); return
        if btn == "about" and self.page == "dashboard":
            self.page = "about"; self._hover_key = None; self._redraw(); return
        if btn == "back":
            self.page = "dashboard"; self._hover_key = None; self._redraw(); return

        # Graph nav on dashboard
        if self.page == "dashboard":
            nav = self._hit_graph_nav(ex, ey)
            if nav == "left":
                if self._graph_index == -1 and self._sessions:
                    self._graph_index = len(self._sessions) - 1
                elif self._graph_index > 0:
                    self._graph_index -= 1
                self._hover_key = None; self._redraw(); return
            if nav == "right":
                if self._graph_index != -1:
                    if self._graph_index < len(self._sessions) - 1:
                        self._graph_index += 1
                    else:
                        self._graph_index = -1
                    self._hover_key = None; self._redraw(); return

        if self.page == "settings":
            self._handle_settings_click(ex, ey); return
        if self.page == "rows_config":
            self._handle_rows_config_click(ex, ey); return
        if self.page == "apps":
            self._handle_apps_click(ex, ey); return
        if self.page == "about":
            self._handle_about_click(ex, ey); return

    def _handle_settings_click(self, x, y):
        settings_meta = {
            "POPUP_REFRESH_INTERVAL": (0.5, 30,  0.5),
            "UPDATE_INTERVAL":        (1,   60,  1),
            "WIDGET_WIDTH":           (20,  200, 1),
            "WIDGET_HEIGHT":          (12,  100, 1),
            "FONT_SIZE":              (8,   72,  1),
            "GRAPH_HEIGHT":           (80,  300, 10),
            "LOW_CRITICAL_PCT":       (5,   50,  1),
        }
        for key, regions in self._settings_hit_regions.items():
            if key == "customize_rows":
                x0, y0, x1, y1 = regions
                if x0 <= x < x1 and y0 <= y < y1:
                    self.page = "rows_config"; self._hover_key = None; self._redraw(); return
            elif key == "move_icon":
                x0, y0, x1, y1 = regions
                if x0 <= x < x1 and y0 <= y < y1:
                    self._move_cb(); return
            else:
                if key not in settings_meta:
                    continue
                mn, mx, step = settings_meta[key]
                cur = getattr(config, key, _DEFAULTS.get(key, 0))
                for action in ("minus", "plus", "reset"):
                    rx0, ry0, rx1, ry1 = regions[action]
                    if rx0 <= x < rx1 and ry0 <= y < ry1:
                        if action == "minus":
                            new_val = max(mn, cur - step)
                        elif action == "plus":
                            new_val = min(mx, cur + step)
                        else:
                            new_val = _DEFAULTS.get(key, cur)
                        if step >= 1:
                            new_val = int(round(new_val))
                        setattr(config, key, new_val)
                        config.save_config()
                        if self._settings_saved_cb:
                            self._settings_saved_cb()
                        self._redraw(); return

    def _handle_rows_config_click(self, x, y):
        for i, regions in self._rows_hit_regions.items():
            for action in ("toggle", "up", "down"):
                rx0, ry0, rx1, ry1 = regions[action]
                if rx0 <= x < rx1 and ry0 <= y < ry1:
                    if action == "toggle":
                        config.ROWS_CONFIG[i]["visible"] = not config.ROWS_CONFIG[i].get("visible", True)
                    elif action == "up" and i > 0:
                        config.ROWS_CONFIG[i], config.ROWS_CONFIG[i - 1] = \
                            config.ROWS_CONFIG[i - 1], config.ROWS_CONFIG[i]
                    elif action == "down" and i < len(config.ROWS_CONFIG) - 1:
                        config.ROWS_CONFIG[i], config.ROWS_CONFIG[i + 1] = \
                            config.ROWS_CONFIG[i + 1], config.ROWS_CONFIG[i]
                    config.save_config()
                    if self._settings_saved_cb:
                        self._settings_saved_cb()
                    self._hover_key = None; self._redraw(); return

    def _handle_apps_click(self, x, y):
        for idx, regions in self._apps_hit_regions.items():
            kx0, ky0, kx1, ky1 = regions["kill"]
            if kx0 <= x < kx1 and ky0 <= y < ky1:
                pid = regions.get("pid", 0)
                if pid > 0:
                    bat_mod.kill_process(pid)
                return

    def _handle_about_click(self, x, y):
        for key, (rx0, ry0, rx1, ry1) in self._about_hit_regions.items():
            if rx0 <= x < rx1 and ry0 <= y < ry1:
                if key == "github":
                    webbrowser.open("https://github.com/AhmarZaidi/wincity")
                elif key == "donate":
                    webbrowser.open("https://ko-fi.com/ahmar")
                return

    def _on_motion(self, event):
        ex, ey  = event.x, event.y
        new_key = None

        btn = self._hit_bottom_bar(ex, ey)
        if btn:
            new_key = btn

        if self.page == "dashboard" and new_key is None:
            nav = self._hit_graph_nav(ex, ey)
            if nav:
                new_key = f"nav_{nav}"

        if self.page == "settings":
            for key, regions in self._settings_hit_regions.items():
                if key in ("customize_rows", "move_icon"):
                    x0, y0, x1, y1 = regions
                    if x0 <= ex < x1 and y0 <= ey < y1:
                        new_key = key; break
                else:
                    for action in ("minus", "plus", "reset"):
                        rx0, ry0, rx1, ry1 = regions[action]
                        if rx0 <= ex < rx1 and ry0 <= ey < ry1:
                            new_key = (key, action); break
                    if new_key:
                        break

        if self.page == "rows_config":
            for i, regions in self._rows_hit_regions.items():
                for action in ("toggle", "up", "down"):
                    rx0, ry0, rx1, ry1 = regions[action]
                    if rx0 <= ex < rx1 and ry0 <= ey < ry1:
                        new_key = (i, action); break
                if new_key:
                    break

        if self.page == "apps":
            for idx, regions in self._apps_hit_regions.items():
                kx0, ky0, kx1, ky1 = regions["kill"]
                if kx0 <= ex < kx1 and ky0 <= ey < ky1:
                    new_key = ("kill", idx); break
                rx0, ry0, rx1, ry1 = regions["row"]
                if rx0 <= ex < rx1 and ry0 <= ey < ry1:
                    new_key = ("app_row", idx); break

        if self.page == "about":
            for key, (rx0, ry0, rx1, ry1) in self._about_hit_regions.items():
                if rx0 <= ex < rx1 and ry0 <= ey < ry1:
                    new_key = f"about_{key}"; break

        if new_key != self._hover_key:
            self._hover_key = new_key
            self._redraw()

        self._cv.config(cursor="hand2" if new_key else "")

    def _on_leave(self, _e=None):
        if self._hover_key is not None:
            self._hover_key = None
            self._redraw()
        self._cv.config(cursor="")

    def _on_scroll(self, event):
        if self.page == "apps":
            with self._app_lock:
                n = len(self._app_list)
            delta = -1 if event.delta > 0 else 1
            self._app_scroll = max(0, min(max(0, n - 8), self._app_scroll + delta))
            self._redraw()

    # ── Live data push ─────────────────────────────────────────────────────────

    def push_update(self, bat, label, secs, rate_mw, designed_mwh, full_mwh,
                    cycle_count, temp_c, elapsed_secs, history, sessions):
        """Called by widget's popup_refresh_tick — pushes fresh telemetry."""
        self._bat           = bat
        self._label         = label
        self._secs          = secs
        self._rate_mw       = rate_mw
        self._designed_mwh  = designed_mwh
        self._full_mwh      = full_mwh
        self._cycle_count   = cycle_count
        self._temp_c        = temp_c
        self._elapsed_secs  = elapsed_secs
        self._history       = history
        self._sessions      = sessions

        if self.page in ("dashboard", "apps"):
            try:
                self._redraw()
            except Exception:
                pass

    # ── Apps background updater ────────────────────────────────────────────────

    def _start_apps_updater(self):
        threading.Thread(target=self._apps_update_loop, daemon=True).start()

    def _apps_update_loop(self):
        """Refresh process list every 2 s while on apps page."""
        while True:
            if self.page != "apps":
                return
            try:
                # Lazy-init ProcessTracker so it doesn't slow popup open
                if self._process_tracker is None:
                    self._process_tracker = bat_mod.ProcessTracker()

                total_watts = bat_mod.get_total_watts(self._rate_mw)
                procs       = self._process_tracker.update(total_watts)
                with self._app_lock:
                    self._app_list        = procs
                    self._actual_total_watts = total_watts
                try:
                    self.win.after(0, self._redraw)
                except Exception:
                    return
            except Exception:
                pass
            time.sleep(2)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _proc_color(name: str) -> tuple:
        """Deterministic vivid color for a process name."""
        h  = int(hashlib.md5(name.lower().encode()).hexdigest()[:6], 16)
        r  = (h >> 16) & 0xFF
        g  = (h >> 8)  & 0xFF
        b  =  h        & 0xFF
        mx = max(r, g, b)
        if mx < 110:
            f = 110 / max(mx, 1)
            r, g, b = (min(220, int(c * f)) for c in (r, g, b))
        return (r, g, b)

    @staticmethod
    def _dotted_line(draw, x1, y1, x2, y2, fill, s):
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1:
            return
        dash = max(3, int(4 * s));  gap = max(2, int(3 * s))
        ux, uy = dx / length, dy / length
        lw     = max(1, int(1.5 * s))
        pos    = 0
        while pos < length:
            ep = min(pos + dash, length)
            draw.line([(int(x1 + ux * pos), int(y1 + uy * pos)),
                       (int(x1 + ux * ep),  int(y1 + uy * ep))],
                      fill=fill, width=lw)
            pos += dash + gap

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def destroy(self):
        self.page = "closed"
        try:
            self.win.destroy()
        except Exception:
            pass
