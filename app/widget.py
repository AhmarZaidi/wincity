"""
BatteryWidget — the always-on-top taskbar battery indicator.
"""
import collections
import ctypes
import ctypes.wintypes
import threading
import time

import tkinter as tk
from PIL import Image, ImageTk

from . import config
from . import system
from . import battery as bat_mod
from .render import render_battery
from .popup import BatteryPopup


# Maximum number of historical sessions to keep in memory + state
_MAX_SESSIONS = 20


class BatteryWidget:

    @staticmethod
    def _should_show():
        """Return True when widget should be visible (taskbar visible + no fullscreen window)."""
        u32 = system.user32
        tb_hwnd = u32.FindWindowW("Shell_TrayWnd", None)
        if not tb_hwnd or not u32.IsWindowVisible(tb_hwnd):
            return False
        tb_rect = ctypes.wintypes.RECT()
        u32.GetWindowRect(tb_hwnd, ctypes.byref(tb_rect))
        if min(tb_rect.bottom - tb_rect.top, tb_rect.right - tb_rect.left) <= 6:
            return False

        fg = u32.GetForegroundWindow()
        if fg:
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(fg, cls, 256)
            if cls.value not in ("Shell_TrayWnd", "Progman", "WorkerW", ""):
                fg_rect = ctypes.wintypes.RECT()
                u32.GetWindowRect(fg, ctypes.byref(fg_rect))
                sw = u32.GetSystemMetrics(0)
                sh = u32.GetSystemMetrics(1)
                if (fg_rect.left <= 0 and fg_rect.top <= 0
                        and fg_rect.right >= sw and fg_rect.bottom >= sh):
                    return False
        return True

    def __init__(self):
        self._stop          = threading.Event()
        self._widget_shown  = True
        self._charge_obs    = None
        self._charge_rate   = None
        self._show_percent  = False
        self._popup         = None
        self._last_bat      = None
        self._last_label    = None
        self._last_secs     = None
        self._last_rate_mw      = None
        self._last_designed_mwh = None
        self._last_full_mwh     = None
        self._last_cycle_count  = None
        self._last_temp_c       = None
        self._history           = collections.deque(maxlen=720)
        self._sessions: list    = []       # completed charge/discharge sessions
        self._discharge_start   = None
        self._charge_start      = None
        self._prev_plugged      = None
        self._last_elapsed_secs = None
        self._save_counter      = 0

        # Drag state
        self._dragging      = False
        self._drag_offset_x = 0
        self._drag_offset_y = 0

        # ── Restore persisted state ────────────────────────────────────────
        state     = config.load_state()
        now_mono  = time.monotonic()
        now_epoch = time.time()

        self._show_percent = bool(state.get("show_percent", False))

        cutoff = now_epoch - 7200
        for entry in state.get("history", []):
            if len(entry) == 3:
                t_ep, pct, pl = entry
                if t_ep >= cutoff:
                    self._history.append(
                        (now_mono - (now_epoch - t_ep), float(pct), bool(pl)))

        # Restore completed sessions (up to _MAX_SESSIONS)
        for sess in state.get("sessions", [])[-_MAX_SESSIONS:]:
            self._sessions.append(sess)

        dse = state.get("discharge_start_epoch")
        if dse is not None:
            elapsed_wall = now_epoch - dse
            if 0 < elapsed_wall < 86400:
                self._discharge_start = now_mono - elapsed_wall
                self._prev_plugged    = False

        cse = state.get("charge_start_epoch")
        if cse is not None:
            elapsed_wall = now_epoch - cse
            if 0 < elapsed_wall < 86400:
                self._charge_start = now_mono - elapsed_wall
                self._prev_plugged = True

        # ── Window setup ──────────────────────────────────────────────────
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.resizable(False, False)

        tb     = system.get_taskbar_rect()
        tb_h   = tb.bottom - tb.top
        scale  = system.dpi_scale()
        self.H = int((config.WIDGET_HEIGHT if config.WIDGET_HEIGHT is not None
                      else max(28, tb_h - 8)) * scale)
        self.W = int(config.WIDGET_WIDTH * scale)

        TRANSPARENT = "#010101"
        self.root.attributes("-transparentcolor", TRANSPARENT)
        self.root.configure(bg=TRANSPARENT)

        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H,
                                bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()
        self._place(tb, tb_h)

        self._menu = tk.Menu(self.root, tearoff=0, bg="#2d2d2d", fg="#ffffff",
                             activebackground="#3a3a3a", activeforeground="#ffffff",
                             font=("Segoe UI", 9))
        self._menu.add_command(label="WinCity", state="disabled")
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
            pass

        threading.Thread(target=self._bg_updater, daemon=True).start()
        self.root.after(config.VISIBILITY_POLL_MS, self._poll_taskbar_visibility)
        self.root.after(int(config.POPUP_REFRESH_INTERVAL * 1000), self._popup_refresh_tick)

    # ── Positioning ────────────────────────────────────────────────────────────

    def _place(self, tb, tb_h):
        # Use saved absolute position if available (set by drag-to-move)
        if config.WIDGET_X is not None and config.WIDGET_Y is not None:
            self.root.geometry(f"{self.W}x{self.H}+{config.WIDGET_X}+{config.WIDGET_Y}")
            return
        x = tb.right - self.W - config.OFFSET_FROM_RIGHT
        if config.OFFSET_FROM_TOP is None:
            y = tb.top + (tb_h - self.H) // 2
        else:
            y = tb.top + config.OFFSET_FROM_TOP
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

    # ── Win32 styling ──────────────────────────────────────────────────────────

    def _apply_win_style(self):
        u32  = system.user32
        hwnd = self.root.winfo_id()
        style = u32.GetWindowLongW(hwnd, system.GWL_EXSTYLE)
        style = (style | system.WS_EX_TOOLWINDOW | system.WS_EX_NOACTIVATE) & ~system.WS_EX_APPWINDOW
        u32.SetWindowLongW(hwnd, system.GWL_EXSTYLE, style)
        u32.SetWindowPos(hwnd, system.HWND_TOPMOST, 0, 0, 0, 0,
                         system.SWP_NOMOVE | system.SWP_NOSIZE)

    # ── Drawing ────────────────────────────────────────────────────────────────

    def _draw(self, bat, label=None):
        W, H  = self.W, self.H
        T     = (1, 1, 1)
        batt  = render_battery(W, H, bat, label, dark=system.is_dark_mode())
        bg    = Image.new("RGB", (W, H), T)
        bg.paste(batt, mask=batt.split()[3])
        self._photo = ImageTk.PhotoImage(bg)
        c = self.canvas
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._photo)

    # ── Refresh ────────────────────────────────────────────────────────────────

    def _update_ui(self):
        bat   = bat_mod.get_battery()
        label = None

        if self._show_percent:
            if bat:
                label = f"{bat.percent:.0f}%"
        elif bat and bat.power_plugged and bat.percent < 100:
            now = time.monotonic()
            if self._charge_obs is not None:
                prev_t, prev_pct = self._charge_obs
                dt   = now - prev_t
                dpct = bat.percent - prev_pct
                if dt > 0 and dpct > 0:
                    self._charge_rate = dpct / dt
            self._charge_obs = (now, bat.percent)

            if bat.secsleft > 0:
                self._last_secs = bat.secsleft
                label = bat_mod.format_time(bat.secsleft)
            elif self._charge_rate:
                est = int((100 - bat.percent) / self._charge_rate)
                self._last_secs = est
                label = bat_mod.format_time(est)
        else:
            self._charge_obs  = None
            self._charge_rate = None
            self._last_secs   = bat.secsleft if (bat and not bat.power_plugged) else None

        self._last_bat   = bat
        self._last_label = label
        if bat is not None:
            self._history.append((time.monotonic(), bat.percent, bat.power_plugged))

        if bat is not None:
            plugged = bat.power_plugged
            if self._prev_plugged is None:
                if plugged:
                    self._charge_start = time.monotonic()
                else:
                    self._discharge_start = time.monotonic()
            elif self._prev_plugged and not plugged:
                # Charger disconnected — save current charging session, start discharge
                self._save_session("charging")
                self._history.clear()
                self._discharge_start = time.monotonic()
                self._charge_start    = None
                self._persist_state()
            elif not self._prev_plugged and plugged:
                # Charger connected — save current discharge session, start charging
                self._save_session("discharging")
                self._history.clear()
                self._charge_start    = time.monotonic()
                self._discharge_start = None
                self._persist_state()
            self._prev_plugged = plugged

        _now = time.monotonic()
        if bat is not None and bat.power_plugged and self._charge_start is not None:
            self._last_elapsed_secs = int(_now - self._charge_start)
        elif bat is not None and not bat.power_plugged and self._discharge_start is not None:
            self._last_elapsed_secs = int(_now - self._discharge_start)
        else:
            self._last_elapsed_secs = None

        rate_mw, designed_mwh, full_mwh, cycle_count, temp_c = bat_mod.query_battery_hw()
        self._last_rate_mw      = rate_mw
        self._last_designed_mwh = designed_mwh
        self._last_full_mwh     = full_mwh
        self._last_cycle_count  = cycle_count
        self._last_temp_c       = temp_c
        self._draw(bat, label)

        self._save_counter += 1
        if self._save_counter >= 30:
            self._save_counter = 0
            self._persist_state()

    def _save_session(self, session_type: str):
        """Snapshot the current history as a completed session and append to self._sessions."""
        if not self._history:
            return
        now_mono  = time.monotonic()
        now_epoch = time.time()
        pts = []
        for t, pct, pl in self._history:
            epoch_t = now_epoch - (now_mono - t)
            pts.append([round(epoch_t, 1), round(pct, 1), int(pl)])
        if pts:
            self._sessions.append({
                "type":    session_type,
                "start":   pts[0][0],
                "end":     pts[-1][0],
                "points":  pts,
            })
            # Trim to max sessions
            if len(self._sessions) > _MAX_SESSIONS:
                self._sessions = self._sessions[-_MAX_SESSIONS:]

    def _persist_state(self):
        now_mono  = time.monotonic()
        now_epoch = time.time()
        dse = None
        if self._discharge_start is not None:
            dse = round(now_epoch - (now_mono - self._discharge_start), 2)
        cse = None
        if self._charge_start is not None:
            cse = round(now_epoch - (now_mono - self._charge_start), 2)
        history_out = [
            [round(now_epoch - (now_mono - t), 1), round(p, 1), int(pl)]
            for t, p, pl in self._history
        ]
        config.save_state({
            "schema":                1,
            "discharge_start_epoch": dse,
            "charge_start_epoch":    cse,
            "show_percent":          self._show_percent,
            "history":               history_out,
            "sessions":              self._sessions,
        })

    def _toggle_display(self, _event=None):
        self._show_percent = not self._show_percent
        self._persist_state()
        self._update_ui()

    def _bg_updater(self):
        _cfg_mtime = config._CONFIG_FILE.stat().st_mtime if config._CONFIG_FILE.exists() else 0
        while not self._stop.wait(config.UPDATE_INTERVAL):
            try:
                mtime = config._CONFIG_FILE.stat().st_mtime
                if mtime != _cfg_mtime:
                    config.load_config()
                    _cfg_mtime = mtime
            except Exception:
                pass
            self.root.after(0, self._update_ui)

    # ── Live popup refresh ─────────────────────────────────────────────────────

    def _popup_refresh_tick(self):
        """Called every POPUP_REFRESH_INTERVAL; pushes fresh telemetry into open popup."""
        if self._popup is not None:
            try:
                self._popup.push_update(
                    self._last_bat, self._last_label, self._last_secs,
                    self._last_rate_mw, self._last_designed_mwh, self._last_full_mwh,
                    self._last_cycle_count, self._last_temp_c,
                    self._last_elapsed_secs,
                    list(self._history),
                    self._sessions,
                )
            except Exception:
                pass
        interval_ms = max(500, int(config.POPUP_REFRESH_INTERVAL * 1000))
        self.root.after(interval_ms, self._popup_refresh_tick)

    # ── Taskbar visibility tracking ────────────────────────────────────────────

    def _poll_taskbar_visibility(self):
        visible = self._should_show()
        if visible and not self._widget_shown:
            self.root.deiconify()
            self._widget_shown = True
        elif not visible and self._widget_shown:
            self.root.withdraw()
            self._widget_shown = False
        self.root.after(config.VISIBILITY_POLL_MS, self._poll_taskbar_visibility)

    # ── Hover popup ────────────────────────────────────────────────────────────

    def _on_hover_enter(self, _e=None):
        if self._popup is None:
            self._open_popup()

    def _open_popup(self):
        self._popup = BatteryPopup(
            self.root,
            self.root.winfo_x(), self.root.winfo_y(), self.W, self.H,
            self._last_bat, self._last_label, self._last_secs,
            self._last_rate_mw, self._last_designed_mwh, self._last_full_mwh,
            self._last_cycle_count, self._last_temp_c,
            self._last_elapsed_secs,
            list(self._history),
            self._sessions,
            quit_cb=self._quit,
            close_cb=self._close_popup,
            move_cb=self._start_drag_mode,
            settings_saved_cb=self._on_settings_saved,
        )
        self._watch_popup()

    def _watch_popup(self):
        if self._popup is None:
            return

        # If the popup is on a page other than dashboard, never auto-close
        try:
            if self._popup.page != "dashboard":
                self.root.after(200, self._watch_popup)
                return
        except Exception:
            pass

        px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()

        wx  = self.root.winfo_x()
        wy  = self.root.winfo_y()

        # Compute the bounding box of popup window
        try:
            popup_win = self._popup.win
            pox = popup_win.winfo_x()
            poy = popup_win.winfo_y()
            pw_ = popup_win.winfo_width()
            ph_ = popup_win.winfo_height()
        except Exception:
            self._close_popup()
            return

        # Active zone: union of widget rect, popup rect, and the gap between them
        zone_x0 = min(wx, pox)
        zone_x1 = max(wx + self.W, pox + pw_)
        zone_y0 = min(wy, poy)
        zone_y1 = max(wy + self.H, poy + ph_)

        if zone_x0 <= px < zone_x1 and zone_y0 <= py < zone_y1:
            self.root.after(150, self._watch_popup)
            return

        self._close_popup()

    def _close_popup(self):
        if self._popup:
            self._popup.destroy()
            self._popup = None

    # ── Drag-to-move ──────────────────────────────────────────────────────────

    def _start_drag_mode(self):
        """Called by popup settings 'Move' button. Enters drag mode."""
        self._close_popup()
        self.canvas.config(cursor="fleur")
        self.canvas.bind("<ButtonPress-1>",   self._drag_start)
        self.canvas.bind("<B1-Motion>",        self._drag_motion)
        self.canvas.bind("<ButtonRelease-1>",  self._drag_stop)

    def _drag_start(self, event):
        self._dragging      = True
        self._drag_offset_x = event.x_root - self.root.winfo_x()
        self._drag_offset_y = event.y_root - self.root.winfo_y()

    def _drag_motion(self, event):
        if not self._dragging:
            return
        new_x = event.x_root - self._drag_offset_x
        new_y = event.y_root - self._drag_offset_y
        self.root.geometry(f"{self.W}x{self.H}+{new_x}+{new_y}")

    def _drag_stop(self, event):
        self._dragging = False
        # Persist absolute position
        config.WIDGET_X = self.root.winfo_x()
        config.WIDGET_Y = self.root.winfo_y()
        config.save_config()
        # Restore normal bindings
        self.canvas.config(cursor="")
        self.canvas.bind("<ButtonPress-1>",   "")
        self.canvas.bind("<B1-Motion>",        "")
        self.canvas.bind("<ButtonRelease-1>",  "")
        self.canvas.bind("<Button-1>",  self._toggle_display)

    # ── Settings saved callback ─────────────────────────────────────────────

    def _on_settings_saved(self):
        """Called when the settings page saves changes; redraws the widget."""
        # Rebuild widget size from updated config
        scale = system.dpi_scale()
        tb    = system.get_taskbar_rect()
        tb_h  = tb.bottom - tb.top
        self.H = int((config.WIDGET_HEIGHT if config.WIDGET_HEIGHT is not None
                      else max(28, tb_h - 8)) * scale)
        self.W = int(config.WIDGET_WIDTH * scale)
        self.canvas.config(width=self.W, height=self.H)
        self._place(tb, tb_h)
        self._update_ui()

    # ── Menu / quit ────────────────────────────────────────────────────────────

    def _show_menu(self, event):
        self._menu.tk_popup(event.x_root, event.y_root)

    def _quit(self):
        self._persist_state()
        self._close_popup()
        self._stop.set()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
