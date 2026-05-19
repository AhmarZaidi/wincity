"""
BatteryPopup — PIL-rendered hover info popup with rounded corners and graph.
"""
import math
import os
import time
from datetime import datetime, timedelta

import psutil
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk

from . import config
from . import system
from . import battery as bat_mod
from .render import load_font


class BatteryPopup:
    """Hover info popup — PIL-rendered; transparent-key gives true rounded corners."""

    _TC     = "#020202"   # transparent key color (distinct from widget's #010101)
    _TC_RGB = (2, 2, 2)
    _MIN_W  = 248

    # Layout in logical px (scaled by DPI at render time)
    _PX = 14; _PY = 10; _TH = 28; _SH = 13; _RH = 26; _QH = 30
    _GH = 120   # graph block total height

    # Graph internals
    _G_MARGIN = 7; _G_LBL_H = 15; _G_CORNER = 6
    _G_FONT = 10; _G_LW = 1.5; _G_MIN_GAP = 34

    _IC = {
        "status":      "\uE8A1",
        "thunder":     "\uE945",
        "pct":         "\uE83F",
        "time":        "\uE916",
        "rate":        "\uE7EF",
        "elapsed":     "\uE81C",
        "screen":      "\uE7F4",
        "power":       "\uE7E8",
        "health":      "\uEB52",
        "cycle":       "\uE117",
        "temp":        "\uE9CA",
        "startup_on":  "\uE73E",
        "startup_off": "\uE739",
        "folder":      "\uE8B7",
        "settings":    "\uE713",
        "close":       "\uE7E8",
        "github":      "\uE71B",
    }

    def __init__(self, root, wx, wy, ww, wh, bat, label, secs,
                 rate_mw, designed_mwh, full_mwh, cycle_count, temp_c,
                 elapsed_secs, history, quit_cb, close_cb):
        self._quit_cb       = quit_cb
        self._close_cb      = close_cb
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

        dark = system.is_dark_mode()
        _c = config.COLORS_DARK if dark else config.COLORS_LIGHT
        self._bg   = _c["bg"];    self._fg   = _c["fg"];   self._fg2  = _c["fg2"]
        self._bdr  = _c["border"]; self._icol = _c["icon"]; self._red  = _c["danger"]
        self._hov  = _c["hover"]

        s          = system.dpi_scale()
        pw         = max(int(self._MIN_W * s), self._MIN_W)
        _vis       = [r for r in config.ROWS_CONFIG if r.get("visible", True)]
        _n_rows    = sum(1 for r in _vis if r.get("id") != "graph")
        _has_graph = any(r.get("id") == "graph" for r in _vis)
        ph = int((self._PY + self._TH + self._SH
                  + _n_rows * self._RH
                  + (_has_graph * self._GH)
                  + self._SH + self._QH + self._PY) * s)

        self._pw, self._ph, self._s = pw, ph, s
        self._img_cache = {}

        self._bar_y0 = int((self._PY + self._TH + self._SH
                            + _n_rows * self._RH
                            + (_has_graph * self._GH)
                            + self._SH) * s)
        self._bar_y1 = self._bar_y0 + int(self._QH * s)

        _b   = int(self._QH * s)
        _pxi = int(self._PX  * s)
        _gap = int(6 * s)
        self._btn_xr = {
            "settings": (_pxi,                              _pxi + _b),
            "github":   (pw - _pxi - _b - _gap - _b,        pw - _pxi - _gap - _b),
            "quit":     (pw - _pxi - _b,                    pw - _pxi),
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

        _init_img = ImageTk.PhotoImage(self._render(pw, ph, s, None))
        self._img_cache[None] = _init_img
        self._img_id = self._cv.create_image(0, 0, anchor="nw", image=_init_img)
        self._cv.bind("<Button-1>", self._on_click)
        self._cv.bind("<Motion>",   self._on_motion)
        self._cv.bind("<Leave>",    self._on_leave)
        self.win.bind("<FocusOut>", lambda _e: self._schedule_close())
        root.bind("<Button-1>",     lambda _e: self._schedule_close(), add="+")

        px_pos = wx + ww // 2 - pw // 2
        py_pos = wy - ph - config.POPUP_Y_OFFSET
        sw     = root.winfo_screenwidth()
        px_pos = max(4, min(px_pos, sw - pw - 4))
        py_pos = max(4, py_pos)

        self.win.geometry(f"{pw}x{ph}+{px_pos}+{py_pos}")
        self.win.update()

        try:
            hwnd  = self.win.winfo_id()
            style = system.user32.GetWindowLongW(hwnd, system.GWL_EXSTYLE)
            system.user32.SetWindowLongW(hwnd, system.GWL_EXSTYLE,
                                         style | system.WS_EX_TOOLWINDOW)
        except Exception:
            pass

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self, w, h, s, hover_key):
        r = config.POPUP_CORNER_RADIUS

        def a(rgb): return rgb + (255,)

        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)

        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=r,
                             fill=a(self._bg), outline=a(self._bdr), width=1)

        tfnt = load_font(int(config.POPUP_TITLE_SIZE * s))
        nfnt = load_font(int(config.POPUP_TEXT_SIZE  * s))
        ifnt = self._mdl2_font(int(config.POPUP_ICON_SIZE * s))

        px = int(self._PX * s)
        y  = int(self._PY * s)

        d.text((px,     y + int(self._TH * s) // 2), "WinCity",
               font=tfnt, fill=a(self._fg), anchor="lm")
        d.text((w - px, y + int(self._TH * s) // 2), "v1.0.0",
               font=nfnt, fill=a(self._fg2), anchor="rm")
        y += int(self._TH * s)

        d.line([(px, y + 4), (w - px, y + 4)], fill=a(self._bdr), width=1)
        y += int(self._SH * s)

        for row in self._rows():
            if row[0] == "graph":
                self._draw_graph(d, img, px, y, w, s, a)
                y += int(self._GH * s)
                continue
            icon, name, value = row[1], row[2], row[3]
            val_icon = row[4] if len(row) > 4 else None
            my = y + int(self._RH * s) // 2
            d.text((px + int(11 * s), my), icon,  font=ifnt, fill=a(self._icol), anchor="mm")
            d.text((px + int(26 * s), my), name,  font=nfnt, fill=a(self._fg2),  anchor="lm")
            if val_icon:
                txt_w = int(d.textlength(value, font=nfnt))
                ico_w = int(config.POPUP_ICON_SIZE * s)
                gap   = int(4 * s)
                blk_x = w - px - txt_w - gap - ico_w
                d.text((blk_x + ico_w // 2, my), val_icon, font=ifnt,
                       fill=a(self._fg), anchor="mm")
                d.text((blk_x + ico_w + gap, my), value, font=nfnt,
                       fill=a(self._fg), anchor="lm")
            else:
                d.text((w - px, my), value, font=nfnt, fill=a(self._fg), anchor="rm")
            y += int(self._RH * s)

        d.line([(px, y + 4), (w - px, y + 4)], fill=a(self._bdr), width=1)
        y += int(self._SH * s)

        b     = int(self._QH * s)
        bar_y = y + b // 2
        for btn_key, glyph in [
            ("settings", self._IC["settings"]),
            ("github",   self._IC["github"]),
            ("quit",     self._IC["close"]),
        ]:
            bx0, bx1 = self._btn_xr[btn_key]
            cx      = (bx0 + bx1) // 2
            hov     = (hover_key == btn_key)
            is_quit = (btn_key == "quit")
            if hov:
                d.rounded_rectangle([bx0, y + int(2 * s), bx1, y + b - int(2 * s)],
                                    radius=int(4 * s), fill=a(self._hov))
            ic_col = self._red if is_quit else (self._fg if hov else self._icol)
            d.text((cx, bar_y), glyph, font=ifnt, fill=a(ic_col), anchor="mm")

        result = Image.new("RGB", (w, h), self._TC_RGB)
        result.paste(img.convert("RGB"), mask=img.split()[3])
        return result

    def _draw_graph(self, d, img, px, y, w, s, a):
        """Draw the battery-history area chart with dotted forecast."""
        gh    = int(self._GH       * s)
        mg    = int(self._G_MARGIN  * s)
        h_lbl = int(self._G_LBL_H   * s)
        cr    = int(self._G_CORNER  * s)

        cx0, cy0 = px, y + int(4 * s)
        cx1, cy1 = w - px, cy0 + gh - int(8 * s)

        dark     = (self._bg[0] < 128)
        cont_bg  = (44, 44, 50) if dark else (205, 207, 215)

        bat = self._bat
        if bat is None:
            return

        if bat.power_plugged:
            fill_col = (  0, 120, 212,  95)
            line_col = (  0, 140, 230, 235)
        elif bat.percent <= config.LOW_PCT or system.get_power_mode() == "Battery Saver":
            fill_col = (240, 190,  40, 100)
            line_col = (215, 160,  15, 240)
        else:
            fill_col = ( 76, 187, 100, 100)
            line_col = ( 40, 170,  70, 240)

        elapsed_s = self._elapsed_secs or 0
        secs_raw  = self._secs
        if (secs_raw is None or secs_raw <= 0
                or secs_raw in (psutil.POWER_TIME_UNKNOWN,
                                psutil.POWER_TIME_UNLIMITED, -1, -2)):
            secs_right = 0
        else:
            secs_right = int(secs_raw)

        total_s = max(1, elapsed_s + secs_right)

        ppx0 = cx0 + mg;  ppx1 = cx1 - mg
        ppy0 = cy0 + mg;  ppy1 = cy1 - mg - h_lbl
        pw_  = max(1, ppx1 - ppx0)
        ph_  = max(1, ppy1 - ppy0)

        def pct_y(pct):
            return ppy1 - int(max(0.0, min(100.0, pct)) / 100.0 * ph_)

        def offset_x(sec_from_left):
            return ppx0 + int(sec_from_left / total_s * pw_)

        now_px = offset_x(elapsed_s)
        cur_y  = pct_y(bat.percent)

        hist = self._history
        if hist and len(hist) >= 2:
            now_mono = time.monotonic()

            def mono_x(mono_t):
                off = elapsed_s - (now_mono - mono_t)
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
                [cx0 + 1, cy0 + 1, cx1 - 1, cy1 - 1], radius=max(1, cr - 1), fill=255)
            img.paste(overlay, mask=clip_mask)
        else:
            sfnt  = load_font(int(11 * s))
            mid_x = (cx0 + cx1) // 2
            mid_y = cy0 + mg + ph_ // 2
            d.text((mid_x, mid_y), "Collecting data\u2026",
                   font=sfnt, fill=a(self._fg2), anchor="mm")

        if secs_right > 0:
            end_y = pct_y(100.0 if bat.power_plugged else 0.0)
            self._dotted_line(d, now_px, cur_y, ppx1, end_y, line_col, s)

        axis_col = a(self._fg2)
        d.line([(ppx0, ppy0), (ppx0, ppy1)], fill=axis_col, width=1)
        d.line([(ppx0, ppy1), (ppx1, ppy1)], fill=axis_col, width=1)

        d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=cr, outline=a(self._bdr), width=1)

        lfnt    = load_font(max(self._G_FONT, int(self._G_FONT * s)))
        lbl_y   = ppy1 + int(3 * s)
        min_gap = int(self._G_MIN_GAP * s)
        now_dt  = datetime.now()

        d.text((ppx0 + int(3 * s), ppy0 + int(2 * s)), "100%",
               font=lfnt, fill=a(self._fg), anchor="lt")

        _h   = self._history
        _sp  = _h[0][1] if (_h and len(_h) >= 1) else bat.percent
        _spy = pct_y(_sp + 8)
        if _spy > ppy0 + int(12 * s):
            d.text((ppx0 + int(4 * s), _spy), f"{_sp:.0f}%",
                   font=lfnt, fill=a(self._fg2), anchor="lm")

        if elapsed_s > 0:
            d.text((ppx0, lbl_y),
                   bat_mod.fmt_hm(now_dt - timedelta(seconds=elapsed_s)),
                   font=lfnt, fill=a(self._fg2), anchor="lt")

        if secs_right > 0 and (ppx1 - now_px) >= min_gap // 2:
            d.text((ppx1, lbl_y),
                   bat_mod.fmt_hm(now_dt + timedelta(seconds=secs_right)),
                   font=lfnt, fill=a(self._fg2), anchor="rt")

    @staticmethod
    def _dotted_line(draw, x1, y1, x2, y2, fill, s):
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1:
            return
        dash = max(3, int(4 * s));  gap = max(2, int(3 * s))
        ux, uy = dx / length, dy / length
        lw = max(1, int(1.5 * s))
        pos = 0
        while pos < length:
            end_pos = min(pos + dash, length)
            draw.line([(int(x1 + ux * pos),     int(y1 + uy * pos)),
                       (int(x1 + ux * end_pos), int(y1 + uy * end_pos))],
                      fill=fill, width=lw)
            pos += dash + gap

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

    def _rows(self):
        bat = self._bat
        if bat is None:
            yield ("status", self._IC["status"], "Status", "Unknown")
            return

        if self._full_mwh:
            remaining_wh = self._full_mwh * bat.percent / 100 / 1000
            pct = f"{bat.percent:.0f}% ({remaining_wh:.1f} Wh)"
        else:
            pct = f"{bat.percent:.0f}%"
        t_lbl = "Time to Full" if bat.power_plugged else "Time Left"
        t_val = bat_mod.format_time_long(self._secs) or ("Full" if bat.percent >= 100 else "\u2014")
        status_extra = (self._IC["thunder"],) if bat.power_plugged else ()

        _data = {
            "status":      (self._IC["status"],  "Status",      "Charging" if bat.power_plugged else "Discharging") + status_extra,
            "percentage":  (self._IC["pct"],     "Percentage",  pct),
            "time":        (self._IC["time"],     t_lbl,         t_val),
            "rate":        (self._IC["rate"],     "Rate",        bat_mod.fmt_rate(self._rate_mw)),
            "elapsed":     (self._IC["elapsed"],  "Elapsed",     bat_mod.format_time_long(self._elapsed_secs) or "\u2014"),
            "screen_on":   (self._IC["screen"],   "Screen On",   "\u2014"),  # TODO: implement screen-on time tracking
            "power_mode":  (self._IC["power"],    "Power Mode",  system.get_power_mode()),
            "cycle_count": (self._IC["cycle"],    "Cycle Count", str(self._cycle_count) if self._cycle_count is not None else "\u2014"),
            "temperature": (self._IC["temp"],     "Temperature", f"{self._temp_c} \u00b0C" if self._temp_c is not None else "\u2014"),
            "health":      (self._IC["health"],   "Health",      bat_mod.fmt_health(self._designed_mwh, self._full_mwh)),
        }

        for entry in config.ROWS_CONFIG:
            rid = entry.get("id")
            if not entry.get("visible", True):
                continue
            if rid == "graph":
                yield ("graph", None, None, None)
            elif rid in _data:
                yield (rid,) + _data[rid]

    # ── Interaction ────────────────────────────────────────────────────────────

    def _btn_hit(self, x, y):
        if not (self._bar_y0 <= y < self._bar_y1):
            return None
        for key, (x0, x1) in self._btn_xr.items():
            if x0 <= x < x1:
                return key
        return None

    def _refresh_image(self, hover_key):
        if hover_key not in self._img_cache:
            self._img_cache[hover_key] = ImageTk.PhotoImage(
                self._render(self._pw, self._ph, self._s, hover_key))
        self._cv.itemconfig(self._img_id, image=self._img_cache[hover_key])

    def _on_click(self, event):
        btn = self._btn_hit(event.x, event.y)
        if btn == "quit":
            self._quit_cb()
        elif btn == "github":
            import webbrowser
            webbrowser.open("https://github.com/AhmarZaidi/wincity")
        elif btn == "settings":
            pass  # TODO: open settings panel

    def _on_motion(self, event):
        btn = self._btn_hit(event.x, event.y)
        self._refresh_image(btn)
        self._cv.config(cursor="hand2" if btn else "")

    def _on_leave(self, _e=None):
        self._refresh_image(None)
        self._cv.config(cursor="")

    def _schedule_close(self):
        try:
            self.win.after(50, self._check_close)
        except Exception:
            pass

    def _check_close(self):
        try:
            px = self.win.winfo_pointerx();  py = self.win.winfo_pointery()
            x,  y  = self.win.winfo_x(),     self.win.winfo_y()
            w,  h  = self.win.winfo_width(),  self.win.winfo_height()
            if not (x <= px < x + w and y <= py < y + h):
                self._close_request()
        except Exception:
            pass

    def _close_request(self):
        self._close_cb()

    def destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass
