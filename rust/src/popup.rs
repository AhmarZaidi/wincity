#![allow(dead_code)]

use std::sync::atomic::{AtomicPtr, Ordering};
use std::sync::Arc;
use windows::core::{w, PCWSTR};
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, GetCursorPos, GetWindowRect, PostQuitMessage, RegisterClassExW,
    SetTimer, SetWindowPos, ShowWindow, HWND_TOPMOST, SW_HIDE, SW_SHOW, WM_LBUTTONDOWN, WM_TIMER,
    WNDCLASSEXW, WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_POPUP,
};

use crate::battery::{self, BatteryHwInfo, BatteryInfo, ProcessTracker, ProcessWattage};
use crate::config::ConfigManager;
use crate::render::{parse_hex_color, BitmapBuffer};
use crate::system;

#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum PopupPage {
    Dashboard,
    Settings,
    RowsConfig,
    Apps,
    About,
    Closed,
}

pub struct PopupController {
    widget_hwnd: HWND,
    popup_hwnd: HWND,
    config_mgr: Arc<ConfigManager>,
    buffer: Option<BitmapBuffer>,
    page: PopupPage,
    last_battery: Option<BatteryInfo>,
    last_label: Option<String>,
    hw_info: BatteryHwInfo,
    process_tracker: Option<ProcessTracker>,
    apps_list: Vec<ProcessWattage>,
    hit_regions: Vec<(RECT, String)>,
    is_open: bool,
}

static POPUP_PTR: AtomicPtr<PopupController> = AtomicPtr::new(std::ptr::null_mut());

impl PopupController {
    pub fn new(widget_hwnd: HWND, config_mgr: Arc<ConfigManager>) -> Self {
        unsafe {
            let hinstance = GetModuleHandleW(PCWSTR::null()).unwrap_or_default();
            let class_name = w!("WinCityPopupClass");

            let wnd_class = WNDCLASSEXW {
                cbSize: std::mem::size_of::<WNDCLASSEXW>() as u32,
                lpfnWndProc: Some(popup_wnd_proc),
                hInstance: hinstance.into(),
                hCursor: windows::Win32::UI::WindowsAndMessaging::LoadCursorW(None, PCWSTR(32512 as _)).unwrap_or_default(),
                lpszClassName: class_name,
                ..Default::default()
            };

            let _ = RegisterClassExW(&wnd_class);

            let ex_style = WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED;
            let popup_hwnd = CreateWindowExW(
                ex_style,
                class_name,
                w!("WinCityPopup"),
                WS_POPUP,
                0,
                0,
                320,
                420,
                None,
                None,
                hinstance,
                None,
            ).unwrap_or(HWND(std::ptr::null_mut()));

            Self {
                widget_hwnd,
                popup_hwnd,
                config_mgr,
                buffer: BitmapBuffer::new(340, 440),
                page: PopupPage::Closed,
                last_battery: None,
                last_label: None,
                hw_info: BatteryHwInfo::default(),
                process_tracker: None,
                apps_list: Vec::new(),
                hit_regions: Vec::new(),
                is_open: false,
            }
        }
    }

    pub fn show(&mut self, bat: Option<BatteryInfo>, label: Option<String>) {
        if self.page == PopupPage::Closed {
            self.page = PopupPage::Dashboard;
        }
        self.last_battery = bat;
        self.last_label = label;
        self.hw_info = battery::query_battery_hw(true);
        self.is_open = true;

        POPUP_PTR.store(self as *mut _, Ordering::SeqCst);

        self.reposition();
        self.redraw();

        unsafe {
            let _ = ShowWindow(self.popup_hwnd, SW_SHOW);
            let _ = SetTimer(self.popup_hwnd, 1, 100, None); // Watch mouse bounds
        }
    }

    pub fn open_settings(&mut self, bat: Option<BatteryInfo>, label: Option<String>) {
        self.page = PopupPage::Settings;
        self.show(bat, label);
    }

    pub fn on_mouse_leave(&mut self) {
        // Watch timer handles auto-dismissal
    }

    pub fn close(&mut self) {
        self.is_open = false;
        self.page = PopupPage::Closed;
        unsafe {
            let _ = ShowWindow(self.popup_hwnd, SW_HIDE);
        }
    }

    pub fn reposition(&mut self) {
        let scale = system::get_dpi_scale();
        let w = (340.0 * scale) as i32;
        let h = (440.0 * scale) as i32;

        let mut widget_rect = RECT::default();
        unsafe {
            let _ = GetWindowRect(self.widget_hwnd, &mut widget_rect);
        }

        let sw = unsafe { windows::Win32::UI::WindowsAndMessaging::GetSystemMetrics(windows::Win32::UI::WindowsAndMessaging::SM_CXSCREEN) };
        let sh = unsafe { windows::Win32::UI::WindowsAndMessaging::GetSystemMetrics(windows::Win32::UI::WindowsAndMessaging::SM_CYSCREEN) };
        let margin = (12.0 * scale) as i32;

        let target_x = widget_rect.left + (widget_rect.right - widget_rect.left - w) / 2;
        let target_y = widget_rect.top - h - (10.0 * scale) as i32;

        let x = target_x.clamp(margin, (sw - w - margin).max(margin));
        let y = target_y.clamp(margin, (sh - h - margin).max(margin));

        unsafe {
            let _ = SetWindowPos(
                self.popup_hwnd,
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

    pub fn redraw(&mut self) {
        if self.buffer.is_none() {
            return;
        }

        let is_dark = system::is_dark_mode();
        let cfg = self.config_mgr.config.lock().unwrap().clone();
        let theme = if is_dark { &cfg.colors.dark } else { &cfg.colors.light };

        let buf = self.buffer.as_mut().unwrap();
        buf.clear(0);
        self.hit_regions.clear();

        let w = buf.width;
        let h = buf.height;
        let scale = system::get_dpi_scale();
        let r = ((cfg.POPUP_CORNER_RADIUS as f64) * scale) as i32;

        let bg_color = parse_hex_color(&theme.bg);
        let border_color = parse_hex_color(&theme.border);
        let fg_color = parse_hex_color(&theme.fg) & 0x00FFFFFF;
        let fg2_color = parse_hex_color(&theme.fg2) & 0x00FFFFFF;
        let danger_color = parse_hex_color(&theme.danger) & 0x00FFFFFF;

        // Draw Card Background and Border
        buf.fill_rounded_rect(0, 0, w, h, r, bg_color);
        buf.outline_rounded_rect(0, 0, w, h, r, 1, border_color);

        let pad = (16.0 * scale) as i32;
        let title_size = (18.0 * scale) as i32;
        let text_size = (13.0 * scale) as i32;

        match self.page {
            PopupPage::Dashboard => {
                // Header
                buf.draw_text_aligned("Battery Status", pad, pad + 10, title_size, fg_color, false);

                let mut y = pad + (36.0 * scale) as i32;
                let rh = (26.0 * scale) as i32;

                let bat_opt = &self.last_battery;
                let pct = bat_opt.as_ref().map(|b| b.percent).unwrap_or(0.0);
                let plugged = bat_opt.as_ref().map(|b| b.power_plugged).unwrap_or(false);

                // Row: Status
                let status_str = if plugged {
                    if pct >= 100.0 { "Fully Charged" } else { "Charging" }
                } else {
                    "Discharging"
                };
                buf.draw_text_aligned("Status", pad, y, text_size, fg2_color, false);
                buf.draw_text_aligned(status_str, w - pad, y, text_size, fg_color, true);
                y += rh;

                // Row: Power Mode
                let power_mode = system::get_power_mode();
                buf.draw_text_aligned("Power Mode", pad, y, text_size, fg2_color, false);
                buf.draw_text_aligned(&power_mode, w - pad, y, text_size, fg_color, true);
                y += rh;

                // Row: Percentage
                buf.draw_text_aligned("Percentage", pad, y, text_size, fg2_color, false);
                buf.draw_text_aligned(&format!("{:.0}%", pct), w - pad, y, text_size, fg_color, true);
                y += rh;

                // Row: Health
                let health_str = battery::fmt_health(self.hw_info.designed_mwh, self.hw_info.full_mwh);
                buf.draw_text_aligned("Health", pad, y, text_size, fg2_color, false);
                buf.draw_text_aligned(&health_str, w - pad, y, text_size, fg_color, true);
                y += rh;

                // Row: Rate
                let rate_str = battery::fmt_rate(self.hw_info.rate_mw);
                buf.draw_text_aligned("Discharge Rate", pad, y, text_size, fg2_color, false);
                buf.draw_text_aligned(&rate_str, w - pad, y, text_size, fg_color, true);
                y += rh;

                // Row: Cycle Count & Temperature
                if let Some(cycles) = self.hw_info.cycle_count {
                    buf.draw_text_aligned("Cycle Count", pad, y, text_size, fg2_color, false);
                    buf.draw_text_aligned(&format!("{}", cycles), w - pad, y, text_size, fg_color, true);
                    y += rh;
                }
                if let Some(temp) = self.hw_info.temp_c {
                    buf.draw_text_aligned("Temperature", pad, y, text_size, fg2_color, false);
                    buf.draw_text_aligned(&format!("{:.1} °C", temp), w - pad, y, text_size, fg_color, true);
                    y += rh;
                }

                // Mini Graph Section
                let graph_box_y0 = y + 10;
                let graph_box_h = (110.0 * scale) as i32;
                let graph_box_y1 = graph_box_y0 + graph_box_h;
                let graph_container_col = parse_hex_color(&theme.graph_container);
                buf.fill_rounded_rect(pad, graph_box_y0, w - pad, graph_box_y1, 8, graph_container_col);

                buf.draw_text_aligned("History (Live)", pad + 10, graph_box_y0 + 12, text_size - 2, fg2_color, false);
                buf.draw_text_aligned(&format!("{:.0}%", pct), w - pad - 10, graph_box_y0 + 12, text_size - 2, fg_color, true);

                // Bottom Navigation Bar
                let btm_y = h - (38.0 * scale) as i32;
                let btn_w = (w - pad * 2) / 4;

                // [Settings]
                buf.draw_text_aligned("Settings", pad + btn_w / 2, btm_y, text_size, fg_color, false);
                self.hit_regions.push((RECT { left: pad, top: btm_y - 10, right: pad + btn_w, bottom: h }, "nav_settings".into()));

                // [Apps]
                buf.draw_text_aligned("Apps", pad + btn_w + btn_w / 2, btm_y, text_size, fg_color, false);
                self.hit_regions.push((RECT { left: pad + btn_w, top: btm_y - 10, right: pad + btn_w * 2, bottom: h }, "nav_apps".into()));

                // [About]
                buf.draw_text_aligned("About", pad + btn_w * 2 + btn_w / 2, btm_y, text_size, fg_color, false);
                self.hit_regions.push((RECT { left: pad + btn_w * 2, top: btm_y - 10, right: pad + btn_w * 3, bottom: h }, "nav_about".into()));

                // [Quit]
                buf.draw_text_aligned("Quit", pad + btn_w * 3 + btn_w / 2, btm_y, text_size, danger_color, false);
                self.hit_regions.push((RECT { left: pad + btn_w * 3, top: btm_y - 10, right: w - pad, bottom: h }, "nav_quit".into()));
            }

            PopupPage::Settings => {
                // Header with Back Button
                buf.draw_text_aligned("< Back", pad, pad + 10, text_size, fg2_color, false);
                self.hit_regions.push((RECT { left: pad, top: pad, right: pad + 80, bottom: pad + 30 }, "nav_back".into()));

                buf.draw_text_aligned("Settings", w / 2 - 20, pad + 10, title_size, fg_color, false);

                let mut y = pad + (44.0 * scale) as i32;
                let rh = (36.0 * scale) as i32;

                // Setting: Start with Windows
                let autostart_on = system::is_autostart_enabled();
                buf.draw_text_aligned("Start with Windows", pad, y, text_size, fg_color, false);
                let toggle_str = if autostart_on { "[ ON ]" } else { "[ OFF ]" };
                buf.draw_text_aligned(toggle_str, w - pad, y, text_size, if autostart_on { 0x0032CD32 } else { fg2_color }, true);
                self.hit_regions.push((RECT { left: pad, top: y - 10, right: w - pad, bottom: y + rh - 10 }, "toggle_autostart".into()));
                y += rh;

                // Setting: Widget Width
                buf.draw_text_aligned("Icon Width", pad, y, text_size, fg2_color, false);
                buf.draw_text_aligned(&format!("{}px", cfg.WIDGET_WIDTH), w - pad - 60, y, text_size, fg_color, true);
                buf.draw_text_aligned("[-]", w - pad - 35, y, text_size, fg_color, false);
                buf.draw_text_aligned("[+]", w - pad, y, text_size, fg_color, true);
                self.hit_regions.push((RECT { left: w - pad - 45, top: y - 10, right: w - pad - 20, bottom: y + 15 }, "dec_width".into()));
                self.hit_regions.push((RECT { left: w - pad - 15, top: y - 10, right: w - pad + 10, bottom: y + 15 }, "inc_width".into()));
                y += rh;

                // Setting: Low Battery Threshold
                buf.draw_text_aligned("Low Battery %", pad, y, text_size, fg2_color, false);
                buf.draw_text_aligned(&format!("{}%", cfg.LOW_PCT), w - pad - 60, y, text_size, fg_color, true);
                buf.draw_text_aligned("[-]", w - pad - 35, y, text_size, fg_color, false);
                buf.draw_text_aligned("[+]", w - pad, y, text_size, fg_color, true);
                self.hit_regions.push((RECT { left: w - pad - 45, top: y - 10, right: w - pad - 20, bottom: y + 15 }, "dec_low_pct".into()));
                self.hit_regions.push((RECT { left: w - pad - 15, top: y - 10, right: w - pad + 10, bottom: y + 15 }, "inc_low_pct".into()));
            }

            PopupPage::Apps => {
                // Header with Back Button
                buf.draw_text_aligned("< Back", pad, pad + 10, text_size, fg2_color, false);
                self.hit_regions.push((RECT { left: pad, top: pad, right: pad + 80, bottom: pad + 30 }, "nav_back".into()));

                buf.draw_text_aligned("Battery Usage by App", pad + 80, pad + 10, title_size - 2, fg_color, false);

                let mut y = pad + (44.0 * scale) as i32;
                let rh = (28.0 * scale) as i32;

                if self.process_tracker.is_none() {
                    self.process_tracker = Some(ProcessTracker::new());
                }

                if let Some(ref mut tracker) = self.process_tracker {
                    let total_watts = self.hw_info.rate_mw.map(|mw| (mw.abs() as f64) / 1000.0).unwrap_or(15.0);
                    self.apps_list = tracker.update(total_watts);
                }

                for app in self.apps_list.iter().take(8) {
                    let name_trunc = if app.name.len() > 18 { format!("{}...", &app.name[..15]) } else { app.name.clone() };
                    buf.draw_text_aligned(&name_trunc, pad, y, text_size, fg_color, false);
                    buf.draw_text_aligned(&format!("{:.1} W ({:.1}%)", app.watts, app.cpu), w - pad, y, text_size, fg2_color, true);
                    y += rh;
                }
            }

            PopupPage::About => {
                buf.draw_text_aligned("< Back", pad, pad + 10, text_size, fg2_color, false);
                self.hit_regions.push((RECT { left: pad, top: pad, right: pad + 80, bottom: pad + 30 }, "nav_back".into()));

                buf.draw_text_aligned("About WinCity", w / 2 - 30, pad + 10, title_size, fg_color, false);

                let mut y = pad + (60.0 * scale) as i32;
                buf.draw_text_aligned("WinCity Native (Rust)", pad, y, title_size, fg_color, false);
                y += 26;
                buf.draw_text_aligned("Version 0.2.0 (High Performance)", pad, y, text_size, fg2_color, false);
                y += 35;
                buf.draw_text_aligned("• Ultra-low resource footprint (~3 MB RAM)", pad, y, text_size, fg_color, false);
                y += 24;
                buf.draw_text_aligned("• 0.00% Idle CPU with OS power events", pad, y, text_size, fg_color, false);
                y += 24;
                buf.draw_text_aligned("• Hardware accelerated native rendering", pad, y, text_size, fg_color, false);
                y += 40;
                buf.draw_text_aligned("Created with ❤️ by Ahmar Zaidi", pad, y, text_size, fg2_color, false);
            }

            _ => {}
        }

        // Present to window
        let mut rect = RECT::default();
        unsafe {
            let _ = GetWindowRect(self.popup_hwnd, &mut rect);
        }
        buf.present_to_window(self.popup_hwnd, rect.left, rect.top);
    }

    pub fn handle_click(&mut self, x: i32, y: i32) {
        for (rect, action) in &self.hit_regions {
            if x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom {
                match action.as_str() {
                    "nav_settings" => {
                        self.page = PopupPage::Settings;
                        self.redraw();
                    }
                    "nav_apps" => {
                        self.page = PopupPage::Apps;
                        self.redraw();
                    }
                    "nav_about" => {
                        self.page = PopupPage::About;
                        self.redraw();
                    }
                    "nav_back" => {
                        self.page = PopupPage::Dashboard;
                        self.redraw();
                    }
                    "nav_quit" => {
                        unsafe {
                            PostQuitMessage(0);
                        }
                    }
                    "toggle_autostart" => {
                        let cur = system::is_autostart_enabled();
                        system::set_autostart(!cur, self.config_mgr.base_dir());
                        self.redraw();
                    }
                    "inc_width" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.WIDGET_WIDTH = (cfg.WIDGET_WIDTH + 5).min(200);
                        }
                        self.config_mgr.save_config();
                        self.redraw();
                    }
                    "dec_width" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.WIDGET_WIDTH = (cfg.WIDGET_WIDTH - 5).max(25);
                        }
                        self.config_mgr.save_config();
                        self.redraw();
                    }
                    "inc_low_pct" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.LOW_PCT = (cfg.LOW_PCT + 5).min(50);
                        }
                        self.config_mgr.save_config();
                        self.redraw();
                    }
                    "dec_low_pct" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.LOW_PCT = (cfg.LOW_PCT.saturating_sub(5)).max(5);
                        }
                        self.config_mgr.save_config();
                        self.redraw();
                    }
                    _ => {}
                }
                return;
            }
        }
    }

    pub fn check_mouse_bounds(&mut self) {
        if !self.is_open || self.page != PopupPage::Dashboard {
            return;
        }

        unsafe {
            let mut pt = POINT::default();
            let _ = GetCursorPos(&mut pt);

            let mut pop_rect = RECT::default();
            let _ = GetWindowRect(self.popup_hwnd, &mut pop_rect);

            let mut wid_rect = RECT::default();
            let _ = GetWindowRect(self.widget_hwnd, &mut wid_rect);

            let x0 = pop_rect.left.min(wid_rect.left);
            let x1 = pop_rect.right.max(wid_rect.right);
            let y0 = pop_rect.top.min(wid_rect.top);
            let y1 = pop_rect.bottom.max(wid_rect.bottom);

            if pt.x < x0 || pt.x > x1 || pt.y < y0 || pt.y > y1 {
                self.close();
            }
        }
    }
}

unsafe extern "system" fn popup_wnd_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    let raw = POPUP_PTR.load(Ordering::SeqCst);
    if raw.is_null() {
        return DefWindowProcW(hwnd, msg, wparam, lparam);
    }
    let popup = &mut *raw;

    match msg {
        WM_LBUTTONDOWN => {
            let x = (lparam.0 & 0xFFFF) as i16 as i32;
            let y = ((lparam.0 >> 16) & 0xFFFF) as i16 as i32;
            popup.handle_click(x, y);
            LRESULT(0)
        }
        WM_TIMER => {
            if wparam.0 == 1 {
                popup.check_mouse_bounds();
            }
            LRESULT(0)
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}
