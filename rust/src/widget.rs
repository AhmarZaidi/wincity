use std::sync::atomic::Ordering;
use std::sync::Arc;
use windows::core::{w, PCWSTR};
use windows::Win32::Foundation::{HANDLE, HWND, LPARAM, LRESULT, RECT, WPARAM};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::System::Power::RegisterPowerSettingNotification;
use windows::Win32::UI::Input::KeyboardAndMouse::{TrackMouseEvent, TME_LEAVE, TRACKMOUSEEVENT};
use windows::Win32::UI::WindowsAndMessaging::{
    AppendMenuW, CreatePopupMenu, CreateWindowExW, DefWindowProcW, DestroyMenu,
    GetCursorPos, GetMessageW, PostQuitMessage, RegisterClassExW,
    SetTimer, SetWindowPos, ShowWindow,
    TrackPopupMenu, TranslateMessage, DispatchMessageW,
    HWND_TOPMOST, MF_CHECKED, MF_DISABLED, MF_GRAYED, MF_SEPARATOR, MF_STRING, MF_UNCHECKED, MSG,
    SW_HIDE, SW_SHOW, TPM_RIGHTBUTTON, WM_COMMAND,
    WM_DESTROY, WM_LBUTTONUP, WM_MOUSEMOVE, WM_POWERBROADCAST, WM_RBUTTONUP, WM_TIMER,
    WNDCLASSEXW, WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_POPUP,
    REGISTER_NOTIFICATION_FLAGS,
};

const WM_MOUSELEAVE_MSG: u32 = 0x02A3;
pub const WM_APP_SETTINGS_CHANGED: u32 = windows::Win32::UI::WindowsAndMessaging::WM_USER + 100;

use crate::battery::{self, BatteryInfo};
use crate::config::ConfigManager;
use crate::popup::PopupController;
use crate::render::{parse_hex_color, BitmapBuffer};
use crate::system;

pub struct BatteryWidget {
    config_mgr: Arc<ConfigManager>,
    pub hwnd: HWND,
    buffer: Option<BitmapBuffer>,
    popup_controller: Option<PopupController>,
    last_draw_key: Option<(u32, bool, String, bool, String, i32, i32)>,
    last_battery: Option<BatteryInfo>,
    last_label: Option<String>,
    show_percent: bool,
    tracking_mouse: bool,
    is_visible: bool,
}

static WIDGET_PTR: std::sync::atomic::AtomicPtr<BatteryWidget> =
    std::sync::atomic::AtomicPtr::new(std::ptr::null_mut());



impl BatteryWidget {
    pub fn new(config_mgr: Arc<ConfigManager>) -> Box<Self> {
        let show_percent = config_mgr.state.lock().unwrap().show_percent;

        Box::new(Self {
            config_mgr,
            hwnd: HWND(std::ptr::null_mut()),
            buffer: None,
            popup_controller: None,
            last_draw_key: None,
            last_battery: None,
            last_label: None,
            show_percent,
            tracking_mouse: false,
            is_visible: true,
        })
    }

    pub fn run(mut self: Box<Self>) {
        unsafe {
            let hinstance = GetModuleHandleW(PCWSTR::null()).unwrap_or_default();
            let class_name = w!("WinCityWidgetClass");

            let wnd_class = WNDCLASSEXW {
                cbSize: std::mem::size_of::<WNDCLASSEXW>() as u32,
                style: windows::Win32::UI::WindowsAndMessaging::WNDCLASS_STYLES(0),
                lpfnWndProc: Some(widget_wnd_proc),
                hInstance: hinstance.into(),
                hCursor: windows::Win32::UI::WindowsAndMessaging::LoadCursorW(None, PCWSTR(32512 as _)).unwrap_or_default(),
                lpszClassName: class_name,
                ..Default::default()
            };

            let _ = RegisterClassExW(&wnd_class);

            let ex_style = WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED;
            let hwnd = CreateWindowExW(
                ex_style,
                class_name,
                w!("WinCity"),
                WS_POPUP,
                0,
                0,
                100,
                50,
                None,
                None,
                hinstance,
                None,
            );

            if let Ok(hwnd) = hwnd {
                self.hwnd = hwnd;
                let raw_ptr = Box::into_raw(self);
                WIDGET_PTR.store(raw_ptr, Ordering::SeqCst);

                let widget = &mut *raw_ptr;
                widget.popup_controller = Some(PopupController::new(hwnd, Arc::clone(&widget.config_mgr)));

                // Position and size window
                widget.reposition();

                // Register for Windows Battery & Power Setting Notifications
                let guid_bat = windows::core::GUID::from_u128(0xA7AD8041_B45A_4CAE_87A3_EECBB468A9E1);
                let _ = RegisterPowerSettingNotification(HANDLE(hwnd.0), &guid_bat, REGISTER_NOTIFICATION_FLAGS(0));
                let guid_ac = windows::core::GUID::from_u128(0x5D3E4A25_E05A_4649_8D22_771FE4D1409C);
                let _ = RegisterPowerSettingNotification(HANDLE(hwnd.0), &guid_ac, REGISTER_NOTIFICATION_FLAGS(0));

                // Set timer for periodic checks
                let poll_ms = widget.config_mgr.config.lock().unwrap().VISIBILITY_POLL_MS;
                let _ = SetTimer(hwnd, 1, poll_ms, None);
                let update_interval = widget.config_mgr.config.lock().unwrap().UPDATE_INTERVAL * 1000;
                let _ = SetTimer(hwnd, 2, update_interval as u32, None);

                widget.update_ui();
                let _ = ShowWindow(hwnd, SW_SHOW);
                let _ = SetWindowPos(
                    hwnd,
                    HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    windows::Win32::UI::WindowsAndMessaging::SWP_NOMOVE
                        | windows::Win32::UI::WindowsAndMessaging::SWP_NOSIZE
                        | windows::Win32::UI::WindowsAndMessaging::SWP_SHOWWINDOW,
                );

                // Main Message Loop
                let mut msg = MSG::default();
                while GetMessageW(&mut msg, None, 0, 0).as_bool() {
                    let _ = TranslateMessage(&msg);
                    DispatchMessageW(&msg);
                }

                let _ = Box::from_raw(raw_ptr);
            }
        }
    }

    pub fn reposition(&mut self) {
        let (w, h, x, y) = {
            let cfg = self.config_mgr.config.lock().unwrap();
            let scale = system::get_dpi_scale();
            let tb = system::get_taskbar_rect();
            let tb_h = tb.bottom - tb.top;

            let h = (cfg.WIDGET_HEIGHT.unwrap_or(28.max(tb_h - 8)) as f64 * scale) as i32;
            let w = (cfg.WIDGET_WIDTH as f64 * scale) as i32;

            let (wx, wy) = if let (Some(cx), Some(cy)) = (cfg.WIDGET_X, cfg.WIDGET_Y) {
                (cx, cy)
            } else {
                let gx = tb.right - w - cfg.OFFSET_FROM_RIGHT;
                let gy = if let Some(ot) = cfg.OFFSET_FROM_TOP {
                    tb.top + ot
                } else {
                    tb.top + (tb_h - h) / 2
                };
                (gx, gy)
            };
            (w, h, wx, wy)
        };

        unsafe {
            let _ = SetWindowPos(
                self.hwnd,
                HWND_TOPMOST,
                x,
                y,
                w,
                h,
                windows::Win32::UI::WindowsAndMessaging::SET_WINDOW_POS_FLAGS(0),
            );
        }

        self.buffer = BitmapBuffer::new(w, h);
    }

    pub fn update_ui(&mut self) {
        if self.config_mgr.reload_if_modified() {
            self.last_draw_key = None;
            self.reposition();
            if let Some(ref mut popup) = self.popup_controller {
                popup.reposition();
                popup.redraw();
            }
        }

        let bat = battery::get_battery_basic();
        if let Some(ref b) = bat {
            let mut st = self.config_mgr.state.lock().unwrap();
            st.record_history_point(b.percent, b.power_plugged);
        }

        let label = if self.show_percent {
            bat.as_ref().map(|b| format!("{:.0}%", b.percent))
        } else if let Some(ref b) = bat {
            if b.power_plugged && b.percent < 100.0 {
                b.secsleft.and_then(battery::format_time).or_else(|| Some(format!("{:.0}%", b.percent)))
            } else if !b.power_plugged {
                b.secsleft.and_then(battery::format_time).or_else(|| Some(format!("{:.0}%", b.percent)))
            } else {
                Some(format!("{:.0}%", b.percent))
            }
        } else {
            None
        };

        self.last_battery = bat.clone();
        self.last_label = label.clone();

        self.render_and_present(bat, label);
    }

    pub fn render_and_present(&mut self, bat: Option<BatteryInfo>, label: Option<String>) {
        if self.buffer.is_none() {
            return;
        }

        let is_dark = system::is_dark_mode();
        let power_mode = system::get_power_mode();
        let pct = bat.as_ref().map(|b| b.percent.round() as u32).unwrap_or(0);
        let plugged = bat.as_ref().map(|b| b.power_plugged).unwrap_or(false);
        let lbl_str = label.clone().unwrap_or_default();

        let (w, h) = {
            let b = self.buffer.as_ref().unwrap();
            (b.width, b.height)
        };

        let draw_key = (pct, plugged, power_mode.clone(), is_dark, lbl_str.clone(), w, h);
        if Some(&draw_key) == self.last_draw_key.as_ref() {
            return; // 0.00% CPU: Skip drawing if unchanged!
        }
        self.last_draw_key = Some(draw_key);

        let cfg = self.config_mgr.config.lock().unwrap();
        let theme = if is_dark { &cfg.colors.dark } else { &cfg.colors.light };

        let buf = self.buffer.as_mut().unwrap();
        buf.clear(0); // Transparent 32-bit ARGB background

        let scale = system::get_dpi_scale();
        let nub_w = (4.0 * scale) as i32;
        let bx0 = (2.0 * scale) as i32;
        let by0 = (2.0 * scale) as i32;
        let bx1 = w - (2.0 * scale) as i32 - nub_w;
        let by1 = h - (2.0 * scale) as i32;
        let body_w = bx1 - bx0;
        let body_h = by1 - by0;
        let r = ((cfg.CORNER_RADIUS as f64).min(4.5) * scale).round() as i32;

        let body_bg = parse_hex_color(&theme.widget_body);
        let nub_col = parse_hex_color(&theme.widget_nub);
        let outline = parse_hex_color(&theme.widget_outline);
        let text_col = parse_hex_color(&theme.widget_text);

        let fill_col = if plugged {
            parse_hex_color(&cfg.colors.widget.fill_charging)
        } else if pct <= cfg.LOW_CRITICAL_PCT {
            parse_hex_color(&cfg.colors.widget.fill_low)
        } else if pct <= cfg.LOW_PCT || power_mode == "Battery Saver" {
            parse_hex_color(&cfg.colors.widget.fill_saver)
        } else {
            parse_hex_color(&cfg.colors.widget.fill_normal)
        };

        // 1. Draw Nub first (overlapping slightly into the body so there is no gap)
        let nub_h = ((body_h as f64 * 0.42).round() as i32).max((5.0 * scale) as i32);
        let nub_y0 = by0 + (body_h - nub_h) / 2;
        let nub_r = ((2.0 * scale).round() as i32).max(1);
        let overlap = (2.0 * scale).round() as i32;
        buf.fill_rounded_rect(bx1 - overlap, nub_y0, bx1 + nub_w, nub_y0 + nub_h, nub_r, nub_col);

        // 2. Draw Battery Body
        buf.fill_rounded_rect(bx0, by0, bx1, by1, r, body_bg);

        // 3. Draw Battery Fill
        let pad = (cfg.FILL_PADDING as f64 * scale) as i32;
        let fill_max_w = (body_w - 2 * pad).max(1);
        let fill_w = ((fill_max_w as f64 * (pct as f64 / 100.0)).round() as i32).max(1);
        let fill_x1 = (bx0 + pad + fill_w).min(bx1 - pad);
        if fill_x1 > bx0 + pad {
            buf.fill_rounded_rect(bx0 + pad, by0 + pad, fill_x1, by1 - pad, (r - pad).max(1), fill_col);
        }

        // 4. Draw Outline
        let out_w = ((cfg.OUTLINE_WIDTH as f64) * scale).round() as i32;
        buf.outline_rounded_rect(bx0, by0, bx1, by1, r, out_w, outline);

        // 5. Draw Text
        let font_size = ((cfg.FONT_SIZE as f64 * 0.62) * scale) as i32;
        let display_text = label.unwrap_or_else(|| format!("{}%", pct));
        let cx = bx0 + body_w / 2;
        let cy = by0 + body_h / 2;
        buf.draw_text(&display_text, cx, cy, font_size, text_col & 0x00FFFFFF, true);

        // Blit to screen via UpdateLayeredWindow
        let mut rect = RECT::default();
        unsafe {
            let _ = windows::Win32::UI::WindowsAndMessaging::GetWindowRect(self.hwnd, &mut rect);
        }
        buf.present_to_window(self.hwnd, rect.left, rect.top);
    }

    pub fn toggle_display(&mut self) {
        self.show_percent = !self.show_percent;
        {
            let mut st = self.config_mgr.state.lock().unwrap();
            st.show_percent = self.show_percent;
        }
        self.config_mgr.save_state();
        self.update_ui();
    }

    pub fn show_context_menu(&self) {
        unsafe {
            let hmenu = CreatePopupMenu();
            if let Ok(hmenu) = hmenu {
                let _ = AppendMenuW(hmenu, MF_STRING | MF_DISABLED | MF_GRAYED, 1, w!("WinCity Native (Rust)"));
                let _ = AppendMenuW(hmenu, MF_SEPARATOR, 0, PCWSTR::null());

                let autostart_flag = if system::is_autostart_enabled() {
                    MF_CHECKED
                } else {
                    MF_UNCHECKED
                };
                let _ = AppendMenuW(hmenu, MF_STRING | autostart_flag, 2, w!("Start with Windows"));
                let _ = AppendMenuW(hmenu, MF_STRING, 3, w!("Settings"));
                let _ = AppendMenuW(hmenu, MF_SEPARATOR, 0, PCWSTR::null());
                let _ = AppendMenuW(hmenu, MF_STRING, 4, w!("Quit"));

                let mut pt = windows::Win32::Foundation::POINT::default();
                let _ = GetCursorPos(&mut pt);

                let _ = TrackPopupMenu(hmenu, TPM_RIGHTBUTTON, pt.x, pt.y, 0, self.hwnd, None);
                let _ = DestroyMenu(hmenu);
            }
        }
    }
}

unsafe extern "system" fn widget_wnd_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    let raw = WIDGET_PTR.load(Ordering::SeqCst);
    if raw.is_null() {
        return DefWindowProcW(hwnd, msg, wparam, lparam);
    }
    let widget = &mut *raw;

    match msg {
        WM_LBUTTONUP => {
            widget.toggle_display();
            LRESULT(0)
        }
        WM_RBUTTONUP => {
            widget.show_context_menu();
            LRESULT(0)
        }
        WM_MOUSEMOVE => {
            if !widget.tracking_mouse {
                widget.tracking_mouse = true;
                let mut tme = TRACKMOUSEEVENT {
                    cbSize: std::mem::size_of::<TRACKMOUSEEVENT>() as u32,
                    dwFlags: TME_LEAVE,
                    hwndTrack: hwnd,
                    dwHoverTime: 0,
                };
                let _ = TrackMouseEvent(&mut tme);

                if let Some(ref mut popup) = widget.popup_controller {
                    popup.show(widget.last_battery.clone(), widget.last_label.clone());
                }
            }
            LRESULT(0)
        }
        WM_MOUSELEAVE_MSG => {
            widget.tracking_mouse = false;
            if let Some(ref mut popup) = widget.popup_controller {
                popup.on_mouse_leave();
            }
            LRESULT(0)
        }
        WM_POWERBROADCAST => {
            widget.update_ui();
            LRESULT(1)
        }
        WM_APP_SETTINGS_CHANGED => {
            let _ = widget.config_mgr.reload_if_modified();
            widget.last_draw_key = None;
            widget.reposition();
            widget.update_ui();
            LRESULT(0)
        }
        WM_TIMER => {
            if wparam.0 == 1 {
                let should_show = system::should_show_widget();
                if should_show && !widget.is_visible {
                    let _ = ShowWindow(hwnd, SW_SHOW);
                    widget.is_visible = true;
                    widget.last_draw_key = None;
                    widget.update_ui();
                } else if !should_show && widget.is_visible {
                    let _ = ShowWindow(hwnd, SW_HIDE);
                    widget.is_visible = false;
                }
            } else if wparam.0 == 2 {
                widget.update_ui();
            }
            LRESULT(0)
        }
        WM_COMMAND => {
            let cmd_id = wparam.0 as u16;
            match cmd_id {
                2 => {
                    let cur = system::is_autostart_enabled();
                    system::set_autostart(!cur, widget.config_mgr.base_dir());
                }
                3 => {
                    if let Some(ref mut popup) = widget.popup_controller {
                        popup.open_settings(widget.last_battery.clone(), widget.last_label.clone());
                    }
                }
                4 => {
                    PostQuitMessage(0);
                }
                _ => {}
            }
            LRESULT(0)
        }
        WM_DESTROY => {
            PostQuitMessage(0);
            LRESULT(0)
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}
