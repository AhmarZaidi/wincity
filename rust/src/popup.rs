use std::sync::atomic::{AtomicPtr, Ordering};
use std::sync::Arc;
use windows::core::{w, PCWSTR};
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::System::SystemInformation::GetLocalTime;
use windows::Win32::UI::Shell::ShellExecuteW;
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, GetCursorPos, GetWindowRect, PostMessageW, PostQuitMessage,
    RegisterClassExW, SetTimer, SetWindowPos, ShowWindow, HWND_TOPMOST, SW_HIDE, SW_SHOW,
    WM_LBUTTONDOWN, WM_MOUSEWHEEL, WM_TIMER, WNDCLASSEXW, WS_EX_LAYERED, WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW, WS_POPUP,
};

use crate::battery::{self, BatteryHwInfo, BatteryInfo, ProcessTracker, ProcessWattage};
use crate::config::ConfigManager;
use crate::render::{parse_hex_color, BitmapBuffer};
use crate::system;
use crate::widget::WM_APP_SETTINGS_CHANGED;

// ── Segoe MDL2 Assets Icons ──────────────────────────────────────────────────
const ICON_STATUS: char = '\u{E8A1}';
const ICON_THUNDER: char = '\u{E945}';
const ICON_PCT: char = '\u{E83F}';
const ICON_TIME: char = '\u{E916}';
const ICON_RATE: char = '\u{E7EF}';
const ICON_ELAPSED: char = '\u{E81C}';
const ICON_SCREEN: char = '\u{E7F4}';
const ICON_POWER: char = '\u{E7E8}';
const ICON_HEALTH: char = '\u{EB52}';
const ICON_CYCLE: char = '\u{E117}';
const ICON_TEMP: char = '\u{E9CA}';
const ICON_SETTINGS: char = '\u{E713}';
const ICON_CLOSE: char = '\u{E8BB}';
const ICON_APPS: char = '\u{E179}';
const ICON_INFO: char = '\u{E946}';
const ICON_BACK: char = '\u{E72B}';
const ICON_RESET: char = '\u{E72C}';
const ICON_CHEV_L: char = '\u{E76B}';
const ICON_CHEV_R: char = '\u{E76C}';
const ICON_MOVE: char = '\u{E7C2}';
const ICON_CHECK_ON: char = '\u{E73E}';
const ICON_CHECK_OFF: char = '\u{E739}';
const ICON_ARROW_UP: char = '\u{E74A}';
const ICON_ARROW_DN: char = '\u{E74B}';
const ICON_MINUS: char = '\u{E738}';
const ICON_PLUS: char = '\u{E710}';

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
    graph_index: i32, // -1 = live session, >= 0 = historical session
    app_scroll: usize,
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
                buffer: BitmapBuffer::new(320, 420),
                page: PopupPage::Closed,
                last_battery: None,
                last_label: None,
                hw_info: BatteryHwInfo::default(),
                process_tracker: None,
                apps_list: Vec::new(),
                hit_regions: Vec::new(),
                graph_index: -1,
                app_scroll: 0,
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
            let _ = SetTimer(self.popup_hwnd, 1, 100, None);
        }
    }

    pub fn open_settings(&mut self, bat: Option<BatteryInfo>, label: Option<String>) {
        self.page = PopupPage::Settings;
        self.show(bat, label);
    }

    pub fn on_mouse_leave(&mut self) {
        // Checked continuously via check_mouse_bounds
    }

    pub fn close(&mut self) {
        self.is_open = false;
        self.page = PopupPage::Closed;
        self.graph_index = -1;
        unsafe {
            let _ = ShowWindow(self.popup_hwnd, SW_HIDE);
        }
    }

    fn compute_height(&self, scale: f64) -> i32 {
        let cfg = self.config_mgr.config.lock().unwrap();
        let pad = (16.0 * scale) as i32;
        let title_h = (30.0 * scale) as i32;
        let sep_h = (10.0 * scale) as i32;
        let btm_h = (38.0 * scale) as i32;
        let rh = ((cfg.POPUP_TEXT_SIZE as f64 * 2.2).max(26.0) * scale) as i32;

        match self.page {
            PopupPage::Dashboard => {
                let mut content_h = 0;
                let gh = ((cfg.GRAPH_HEIGHT as f64).max(120.0) * scale) as i32;

                for r in &cfg.rows {
                    if !r.visible {
                        continue;
                    }
                    if r.id == "graph" {
                        content_h += gh + (8.0 * scale) as i32;
                    } else {
                        content_h += rh;
                    }
                }
                pad * 2 + title_h + sep_h + content_h + sep_h + btm_h
            }
            PopupPage::Settings => {
                // 1 toggle + 9 steppers + 3 buttons
                let rh_set = ((cfg.POPUP_TEXT_SIZE as f64 * 2.2).max(28.0) * scale) as i32;
                pad * 2 + title_h + sep_h + (13 * rh_set) + (26.0 * scale) as i32
            }
            PopupPage::RowsConfig => {
                let n = cfg.rows.len() as i32;
                pad * 2 + title_h + sep_h + (n * rh) + (10.0 * scale) as i32
            }
            PopupPage::Apps => {
                pad * 2 + title_h + sep_h + (10 * rh) + (20.0 * scale) as i32
            }
            PopupPage::About => {
                // Title (42px) + Card (112px) + Spacing (16px) + Buttons (32px) + Spacing (16px) + Footer (20px)
                pad * 2 + title_h + sep_h + (238.0 * scale) as i32
            }
            PopupPage::Closed => (400.0 * scale) as i32,
        }
    }

    pub fn reposition(&mut self) {
        let scale = system::get_dpi_scale();
        let w = (310.0 * scale).round() as i32;
        let h = self.compute_height(scale);

        let sw = unsafe { windows::Win32::UI::WindowsAndMessaging::GetSystemMetrics(windows::Win32::UI::WindowsAndMessaging::SM_CXSCREEN) };
        let sh = unsafe { windows::Win32::UI::WindowsAndMessaging::GetSystemMetrics(windows::Win32::UI::WindowsAndMessaging::SM_CYSCREEN) };
        let tb = system::get_taskbar_rect();

        let margin_right = (16.0 * scale) as i32;
        let margin_bottom = (12.0 * scale) as i32;

        let x = (sw - w - margin_right).clamp(10, (sw - w - 10).max(10));
        let y = (tb.top - h - margin_bottom).clamp(10, (sh - h - 10).max(10));

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
        let icon_color = parse_hex_color(&theme.icon) & 0x00FFFFFF;
        let danger_color = parse_hex_color(&theme.danger) & 0x00FFFFFF;
        let hover_color = parse_hex_color(&theme.hover);
        let accent_color = 0x000078D4;

        // 1. Draw Card Background and Border
        buf.fill_rounded_rect(0, 0, w, h, r, bg_color);
        buf.outline_rounded_rect(0, 0, w, h, r, 1, border_color);

        let pad = (16.0 * scale) as i32;
        let title_size = ((cfg.POPUP_TITLE_SIZE as f64) * scale).round() as i32;
        let text_size = ((cfg.POPUP_TEXT_SIZE as f64) * scale).round() as i32;
        let icon_size = ((cfg.POPUP_ICON_SIZE as f64) * scale).round() as i32;
        let rh = ((cfg.POPUP_TEXT_SIZE as f64 * 2.2).max(26.0) * scale) as i32;
        let mut y = pad;

        match self.page {
            PopupPage::Dashboard => {
                // Header: "WinCity" on left, "v1.1.0" on right
                let ty = y + (12.0 * scale) as i32;
                buf.draw_text_aligned("WinCity", pad, ty, title_size, fg_color, false);
                buf.draw_text_aligned("v1.1.0", w - pad, ty, text_size, fg2_color, true);
                y += (28.0 * scale) as i32;

                // Separator line
                buf.draw_line(pad, y, w - pad, y, 1, border_color);
                y += (10.0 * scale) as i32;

                let bat_opt = &self.last_battery;
                let pct = bat_opt.as_ref().map(|b| b.percent).unwrap_or(50.0);
                let plugged = bat_opt.as_ref().map(|b| b.power_plugged).unwrap_or(false);

                // Render dynamic rows
                for row in &cfg.rows {
                    if !row.visible {
                        continue;
                    }
                    let my = y + rh / 2;
                    match row.id.as_str() {
                        "status" => {
                            let status_str = if plugged {
                                if pct >= 100.0 { "Fully Charged" } else { "Charging" }
                            } else {
                                "Discharging"
                            };
                            buf.draw_icon_left(ICON_STATUS, pad, my, icon_size, icon_color);
                            buf.draw_text_aligned("Status", pad + (24.0 * scale) as i32, my, text_size, fg2_color, false);
                            if plugged {
                                buf.draw_icon(ICON_THUNDER, w - pad - (60.0 * scale) as i32, my, icon_size, fg_color);
                            }
                            buf.draw_text_aligned(status_str, w - pad, my, text_size, fg_color, true);
                            y += rh;
                        }
                        "power_mode" => {
                            let power_mode = system::get_power_mode();
                            buf.draw_icon_left(ICON_POWER, pad, my, icon_size, icon_color);
                            buf.draw_text_aligned("Power Mode", pad + (24.0 * scale) as i32, my, text_size, fg2_color, false);
                            buf.draw_text_aligned(&power_mode, w - pad, my, text_size, fg_color, true);
                            y += rh;
                        }
                        "percentage" => {
                            let pct_str = if let Some(full) = self.hw_info.full_mwh {
                                let rem_wh = (full as f64 * pct / 100.0) / 1000.0;
                                format!("{:.0}% ({:.1} Wh)", pct, rem_wh)
                            } else {
                                format!("{:.0}%", pct)
                            };
                            buf.draw_icon_left(ICON_PCT, pad, my, icon_size, icon_color);
                            buf.draw_text_aligned("Percentage", pad + (24.0 * scale) as i32, my, text_size, fg2_color, false);
                            buf.draw_text_aligned(&pct_str, w - pad, my, text_size, fg_color, true);
                            y += rh;
                        }
                        "health" => {
                            let health_str = battery::fmt_health(self.hw_info.designed_mwh, self.hw_info.full_mwh);
                            buf.draw_icon_left(ICON_HEALTH, pad, my, icon_size, icon_color);
                            buf.draw_text_aligned("Health", pad + (24.0 * scale) as i32, my, text_size, fg2_color, false);
                            buf.draw_text_aligned(&health_str, w - pad, my, text_size, fg_color, true);
                            y += rh;
                        }
                        "time" => {
                            let label = if plugged { "Time to Full" } else { "Time Remaining" };
                            let time_str = if plugged && pct >= 100.0 {
                                "Full".into()
                            } else if let Some(secs) = bat_opt.as_ref().and_then(|b| b.secsleft) {
                                battery::format_time(secs).unwrap_or_else(|| "—".into())
                            } else {
                                "—".into()
                            };
                            buf.draw_icon_left(ICON_TIME, pad, my, icon_size, icon_color);
                            buf.draw_text_aligned(label, pad + (24.0 * scale) as i32, my, text_size, fg2_color, false);
                            buf.draw_text_aligned(&time_str, w - pad, my, text_size, fg_color, true);
                            y += rh;
                        }
                        "rate" => {
                            let rate_str = battery::fmt_rate(self.hw_info.rate_mw);
                            let rate_label = if plugged { "Charge Rate" } else { "Discharge Rate" };
                            buf.draw_icon_left(ICON_RATE, pad, my, icon_size, icon_color);
                            buf.draw_text_aligned(rate_label, pad + (24.0 * scale) as i32, my, text_size, fg2_color, false);
                            buf.draw_text_aligned(&rate_str, w - pad, my, text_size, fg_color, true);
                            y += rh;
                        }
                        "elapsed" => {
                            let state = self.config_mgr.state.lock().unwrap();
                            let now_ep = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
                            let el_sec = if plugged {
                                state.charge_start_epoch.map(|s| (now_ep - s).max(0.0) as u64)
                            } else {
                                state.discharge_start_epoch.map(|s| (now_ep - s).max(0.0) as u64)
                            };
                            let el_str = el_sec.and_then(|s| battery::format_time(s as i64)).unwrap_or_else(|| "—".to_string());
                            buf.draw_icon_left(ICON_ELAPSED, pad, my, icon_size, icon_color);
                            buf.draw_text_aligned("Elapsed", pad + (24.0 * scale) as i32, my, text_size, fg2_color, false);
                            buf.draw_text_aligned(&el_str, w - pad, my, text_size, fg_color, true);
                            y += rh;
                        }
                        "screen_on" => {
                            let son_secs = battery::get_screen_on_seconds().unwrap_or(0);
                            let son_str = battery::format_duration_short(son_secs);
                            buf.draw_icon_left(ICON_SCREEN, pad, my, icon_size, icon_color);
                            buf.draw_text_aligned("Screen On", pad + (24.0 * scale) as i32, my, text_size, fg2_color, false);
                            buf.draw_text_aligned(&son_str, w - pad, my, text_size, fg_color, true);
                            y += rh;
                        }
                        "battery_estimate" => {
                            let est_str = if let Some(rate) = self.hw_info.rate_mw {
                                if rate.abs() > 50 && self.hw_info.full_mwh.is_some() {
                                    let hrs = (self.hw_info.full_mwh.unwrap() as f64) / (rate.abs() as f64);
                                    format!("{:.1} hrs full", hrs)
                                } else {
                                    "—".into()
                                }
                            } else {
                                "—".into()
                            };
                            buf.draw_icon_left(ICON_TIME, pad, my, icon_size, icon_color);
                            buf.draw_text_aligned("Est. Runtime", pad + (24.0 * scale) as i32, my, text_size, fg2_color, false);
                            buf.draw_text_aligned(&est_str, w - pad, my, text_size, fg_color, true);
                            y += rh;
                        }
                        "cycle_count" => {
                            let cyc_str = self.hw_info.cycle_count.map(|c| format!("{}", c)).unwrap_or_else(|| "—".into());
                            buf.draw_icon_left(ICON_CYCLE, pad, my, icon_size, icon_color);
                            buf.draw_text_aligned("Cycle Count", pad + (24.0 * scale) as i32, my, text_size, fg2_color, false);
                            buf.draw_text_aligned(&cyc_str, w - pad, my, text_size, fg_color, true);
                            y += rh;
                        }
                        "temperature" => {
                            let temp_str = self.hw_info.temp_c.map(|t| format!("{:.1} °C", t)).unwrap_or_else(|| "—".into());
                            buf.draw_icon_left(ICON_TEMP, pad, my, icon_size, icon_color);
                            buf.draw_text_aligned("Temperature", pad + (24.0 * scale) as i32, my, text_size, fg2_color, false);
                            buf.draw_text_aligned(&temp_str, w - pad, my, text_size, fg_color, true);
                            y += rh;
                        }
                        "graph" => {
                            // Graph Box Container
                            let gh = ((cfg.GRAPH_HEIGHT as f64).max(120.0) * scale) as i32;
                            let g_y0 = y + (4.0 * scale) as i32;
                            let g_y1 = g_y0 + gh;
                            let g_container = parse_hex_color(&theme.graph_container);
                            buf.fill_rounded_rect(pad, g_y0, w - pad, g_y1, 6, g_container);

                            let state = self.config_mgr.state.lock().unwrap().clone();
                            let is_live = self.graph_index == -1;

                            // Navigation Chevrons
                            let nav_y = g_y0 + (12.0 * scale) as i32;
                            let rx1 = w - pad - (8.0 * scale) as i32;
                            let rx0 = rx1 - (16.0 * scale) as i32;
                            let lx1 = rx0 - (6.0 * scale) as i32;
                            let lx0 = lx1 - (16.0 * scale) as i32;

                            let can_left = is_live && !state.sessions.is_empty() || self.graph_index > 0;
                            let can_right = !is_live;

                            buf.draw_icon(ICON_CHEV_L, (lx0 + lx1) / 2, nav_y, (12.0 * scale) as i32, if can_left { fg_color } else { fg2_color });
                            buf.draw_icon(ICON_CHEV_R, (rx0 + rx1) / 2, nav_y, (12.0 * scale) as i32, if can_right { accent_color } else { fg2_color });

                            self.hit_regions.push((RECT { left: lx0 - 4, top: g_y0, right: lx1 + 2, bottom: g_y0 + 26 }, "graph_prev".into()));
                            self.hit_regions.push((RECT { left: rx0 - 2, top: g_y0, right: rx1 + 4, bottom: g_y0 + 26 }, "graph_next".into()));

                            // Header inside graph: "100%" top-left, "Live" / Session type top-center
                            let l_fnt = (10.0 * scale) as i32;
                            buf.draw_text_aligned("100%", pad + (8.0 * scale) as i32, g_y0 + (10.0 * scale) as i32, l_fnt, fg_color, false);

                            let center_label = if is_live {
                                "Live"
                            } else if let Some(sess) = state.sessions.get(self.graph_index as usize) {
                                if sess.session_type == "charging" { "Charging" } else { "Discharging" }
                            } else {
                                ""
                            };
                            buf.draw_text(center_label, w / 2, g_y0 + (10.0 * scale) as i32, l_fnt, accent_color, false);

                            // Geometry for plot curve
                            let gx0 = pad + (8.0 * scale) as i32;
                            let gx1 = w - pad - (8.0 * scale) as i32;
                            let gy0 = g_y0 + (22.0 * scale) as i32;
                            let gy1 = g_y1 - (22.0 * scale) as i32;
                            let gw = (gx1 - gx0).max(1);
                            let gh_plot = (gy1 - gy0).max(1);

                            let is_charging_plot = if is_live { plugged } else {
                                state.sessions.get(self.graph_index as usize).map(|s| s.session_type == "charging").unwrap_or(false)
                            };

                            let (elapsed_s, secs_right, sess_start_ep, sess_end_ep, pts_data) = if is_live {
                                let now_ep = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
                                let start_ep = if plugged {
                                    state.charge_start_epoch.unwrap_or(now_ep)
                                } else {
                                    state.discharge_start_epoch.unwrap_or(now_ep)
                                };
                                let el = (now_ep - start_ep).max(0.0);
                                let sr = bat_opt.as_ref().and_then(|b| b.secsleft).unwrap_or(0).max(0) as f64;
                                let pts: Vec<(f64, f64, bool)> = state.history.iter().filter_map(|v| {
                                    if v.len() >= 3 {
                                        Some((v[0], v[1], v[2] > 0.5))
                                    } else {
                                        None
                                    }
                                }).collect();
                                (el, sr, start_ep, None, pts)
                            } else if let Some(sess) = state.sessions.get(self.graph_index as usize) {
                                let el = (sess.end - sess.start).max(0.0);
                                let pts: Vec<(f64, f64, bool)> = sess.points.iter().filter_map(|v| {
                                    if v.len() >= 3 {
                                        Some((v[0], v[1], v[2] > 0.5))
                                    } else {
                                        None
                                    }
                                }).collect();
                                (el, 0.0, sess.start, Some(sess.end), pts)
                            } else {
                                (0.0, 0.0, 0.0, None, Vec::new())
                            };

                            let pwr_mode = system::get_power_mode();
                            let is_saver = pwr_mode == "Energy Saver" || pwr_mode == "Battery Saver" || pwr_mode == "Best power efficiency";

                            let (fill_col, line_col) = if is_charging_plot {
                                (parse_hex_color(&cfg.colors.graph.charging_fill), parse_hex_color(&cfg.colors.graph.charging_line))
                            } else if pct <= cfg.LOW_CRITICAL_PCT as f64 {
                                (parse_hex_color(&cfg.colors.graph.low_fill), parse_hex_color(&cfg.colors.graph.low_line))
                            } else if pct <= cfg.LOW_PCT as f64 || is_saver {
                                (0x64f0be28, 0xF0f0be28) // Amber / Yellow Saver fill & line
                            } else {
                                (parse_hex_color(&cfg.colors.graph.normal_fill), parse_hex_color(&cfg.colors.graph.normal_line))
                            };

                            let total_s = (elapsed_s + secs_right).max(60.0);
                            let now_px = (gx0 as f64 + (elapsed_s / total_s).clamp(0.0, 1.0) * gw as f64).round() as i32;
                            let cur_y = gy1 - ((pct.clamp(0.0, 100.0) / 100.0) * gh_plot as f64).round() as i32;

                            let mut last_px = gx0;
                            let mut last_py = cur_y;

                            if pts_data.len() >= 2 {
                                let mut poly_pts = Vec::new();
                                let mut line_pts = Vec::new();
                                poly_pts.push((gx0, gy1));

                                for (t, p, _) in &pts_data {
                                    let off = (t - sess_start_ep).max(0.0);
                                    let cur_x = (gx0 as f64 + (off / total_s).clamp(0.0, 1.0) * gw as f64).round() as i32;
                                    let cur_y_pt = gy1 - ((p.clamp(0.0, 100.0) / 100.0) * gh_plot as f64).round() as i32;
                                    poly_pts.push((cur_x, cur_y_pt));
                                    line_pts.push((cur_x, cur_y_pt));
                                    last_px = cur_x;
                                    last_py = cur_y_pt;
                                }
                                if is_live {
                                    poly_pts.push((now_px, cur_y));
                                    line_pts.push((now_px, cur_y));
                                    last_px = now_px;
                                    last_py = cur_y;
                                }
                                poly_pts.push((last_px, gy1));

                                buf.draw_polygon_fill(&poly_pts, fill_col);
                                buf.draw_polyline(&line_pts, 2, line_col);

                                // Start % label
                                let start_pct = pts_data[0].1;
                                let start_y = gy1 - ((start_pct.clamp(0.0, 100.0) / 100.0) * gh_plot as f64).round() as i32;
                                if start_y > gy0 + (14.0 * scale) as i32 {
                                    buf.draw_text_aligned(&format!("{:.0}%", start_pct), gx0 + 4, start_y - 8, l_fnt, fg2_color, false);
                                }
                            } else {
                                buf.draw_line(gx0, cur_y, now_px.max(gx0 + 10), cur_y, 2, line_col);
                                last_px = now_px;
                                last_py = cur_y;
                            }

                            // Dotted projection line if live session
                            if is_live && secs_right > 0.0 {
                                let end_y = if plugged { gy1 - gh_plot } else { gy1 };
                                buf.draw_dotted_line(last_px, last_py, gx1, end_y, 2, line_col);
                            }

                            // Axis lines
                            buf.draw_line(gx0, gy0, gx0, gy1, 1, fg2_color);
                            buf.draw_line(gx0, gy1, gx1, gy1, 1, fg2_color);

                            // Timeline Labels below X-Axis
                            let lbl_y = gy1 + (4.0 * scale) as i32;
                            if is_live {
                                buf.draw_text_aligned(&format_epoch_hm(sess_start_ep), gx0, lbl_y, l_fnt, fg2_color, false);
                                if secs_right > 0.0 {
                                    let now_ep = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
                                    let end_ep = now_ep + secs_right;
                                    buf.draw_text_aligned(&format_epoch_hm(end_ep), gx1, lbl_y, l_fnt, fg2_color, true);
                                }
                                let total_est = elapsed_s + (if secs_right > 0.0 { secs_right } else { 0.0 });
                                if total_est > 60.0 {
                                    let h_ = (total_est as u64) / 3600;
                                    let m_ = ((total_est as u64) % 3600) / 60;
                                    let dur_str = if h_ > 0 { format!("{}h {:02}m", h_, m_) } else { format!("{}m", m_) };
                                    buf.draw_text(&dur_str, (gx0 + gx1) / 2, lbl_y + (6.0 * scale) as i32, l_fnt, fg2_color, false);
                                }
                            } else if let Some(end_ep) = sess_end_ep {
                                buf.draw_text_aligned(&format_epoch_hm(sess_start_ep), gx0, lbl_y, l_fnt, fg2_color, false);
                                buf.draw_text_aligned(&format_epoch_hm(end_ep), gx1, lbl_y, l_fnt, fg2_color, true);
                                let dur = (end_ep - sess_start_ep).max(0.0) as u64;
                                if dur > 60 {
                                    let h_ = dur / 3600;
                                    let m_ = (dur % 3600) / 60;
                                    let dur_str = if h_ > 0 { format!("{}h {:02}m", h_, m_) } else { format!("{}m", m_) };
                                    buf.draw_text(&dur_str, (gx0 + gx1) / 2, lbl_y + (6.0 * scale) as i32, l_fnt, fg2_color, false);
                                }
                            }

                            y = g_y1 + (8.0 * scale) as i32;
                        }
                        _ => {}
                    }
                }

                // Bottom separator
                y += (4.0 * scale) as i32;
                buf.draw_line(pad, y, w - pad, y, 1, border_color);
                y += (8.0 * scale) as i32;

                // Bottom 4-Button Navigation Bar with MDL2 glyphs
                let btm_cy = y + (16.0 * scale) as i32;
                let b_size = (16.0 * scale) as i32;
                let gap = (w - 2 * pad) / 4;

                // [Settings ⚙]
                let s_cx = pad + gap / 2;
                buf.draw_icon(ICON_SETTINGS, s_cx, btm_cy, b_size, icon_color);
                self.hit_regions.push((RECT { left: pad, top: y, right: pad + gap, bottom: h }, "nav_settings".into()));

                // [Apps ▦]
                let a_cx = pad + gap + gap / 2;
                buf.draw_icon(ICON_APPS, a_cx, btm_cy, b_size, icon_color);
                self.hit_regions.push((RECT { left: pad + gap, top: y, right: pad + gap * 2, bottom: h }, "nav_apps".into()));

                // [About ℹ]
                let ab_cx = pad + gap * 2 + gap / 2;
                buf.draw_icon(ICON_INFO, ab_cx, btm_cy, b_size, icon_color);
                self.hit_regions.push((RECT { left: pad + gap * 2, top: y, right: pad + gap * 3, bottom: h }, "nav_about".into()));

                // [Quit ✕]
                let q_cx = pad + gap * 3 + gap / 2;
                buf.draw_icon(ICON_CLOSE, q_cx, btm_cy, b_size, danger_color);
                self.hit_regions.push((RECT { left: pad + gap * 3, top: y, right: w - pad, bottom: h }, "nav_quit".into()));
            }

            PopupPage::Settings => {
                // Header with Back Arrow
                let ty = y + (12.0 * scale) as i32;
                buf.draw_icon_left(ICON_BACK, pad, ty, icon_size, fg_color);
                buf.draw_text_aligned("Settings", pad + (24.0 * scale) as i32, ty, title_size, fg_color, false);
                self.hit_regions.push((RECT { left: pad, top: y, right: pad + 80, bottom: y + 30 }, "nav_dashboard".into()));
                y += (28.0 * scale) as i32;

                buf.draw_line(pad, y, w - pad, y, 1, border_color);
                y += (10.0 * scale) as i32;

                let rh_set = ((cfg.POPUP_TEXT_SIZE as f64 * 2.2).max(28.0) * scale) as i32;

                // 1. Start with Windows Toggle
                let autostart_on = system::is_autostart_enabled();
                let my = y + rh_set / 2;
                buf.draw_icon_left(if autostart_on { ICON_CHECK_ON } else { ICON_CHECK_OFF }, pad, my, icon_size, if autostart_on { accent_color } else { fg2_color });
                buf.draw_text_aligned("Start with Windows", pad + (24.0 * scale) as i32, my, text_size, fg_color, false);
                buf.draw_text_aligned(if autostart_on { "[ ON ]" } else { "[ OFF ]" }, w - pad, my, text_size, if autostart_on { 0x0032CD32 } else { fg2_color }, true);
                self.hit_regions.push((RECT { left: pad, top: y, right: w - pad, bottom: y + rh_set }, "toggle_autostart".into()));
                y += rh_set;

                // Helper for stepper row rendering
                let mut draw_stepper = |label: &str, val_str: &str, key_dec: &str, key_inc: &str, key_rst: &str, cur_y: &mut i32| {
                    let smy = *cur_y + rh_set / 2;
                    buf.draw_text_aligned(label, pad + (6.0 * scale) as i32, smy, text_size, fg2_color, false);

                    let btn_w = (20.0 * scale) as i32;
                    let rst_x = w - pad - btn_w / 2;
                    let inc_x = rst_x - (22.0 * scale) as i32;
                    let val_x = inc_x - (28.0 * scale) as i32;
                    let dec_x = val_x - (28.0 * scale) as i32;

                    // Reset icon
                    buf.draw_icon(ICON_RESET, rst_x, smy, (12.0 * scale) as i32, fg2_color);
                    self.hit_regions.push((RECT { left: rst_x - 10, top: *cur_y, right: rst_x + 10, bottom: *cur_y + rh_set }, key_rst.into()));

                    // [+] icon
                    buf.draw_icon(ICON_PLUS, inc_x, smy, (12.0 * scale) as i32, icon_color);
                    self.hit_regions.push((RECT { left: inc_x - 10, top: *cur_y, right: inc_x + 10, bottom: *cur_y + rh_set }, key_inc.into()));

                    // Value
                    buf.draw_text_aligned(val_str, val_x, smy, text_size - 1, fg_color, false);

                    // [-] icon
                    buf.draw_icon(ICON_MINUS, dec_x, smy, (12.0 * scale) as i32, icon_color);
                    self.hit_regions.push((RECT { left: dec_x - 10, top: *cur_y, right: dec_x + 10, bottom: *cur_y + rh_set }, key_dec.into()));

                    *cur_y += rh_set;
                };

                draw_stepper("Popup Font Size", &format!("{}pt", cfg.POPUP_TEXT_SIZE), "dec_popup_font", "inc_popup_font", "rst_popup_font", &mut y);
                draw_stepper("Popup Refresh", &format!("{:.1}s", cfg.POPUP_REFRESH_INTERVAL), "dec_popup_ref", "inc_popup_ref", "rst_popup_ref", &mut y);
                draw_stepper("Icon Refresh", &format!("{}s", cfg.UPDATE_INTERVAL), "dec_poll", "inc_poll", "rst_poll", &mut y);
                draw_stepper("Icon Width", &format!("{}px", cfg.WIDGET_WIDTH), "dec_width", "inc_width", "rst_width", &mut y);
                draw_stepper("Icon Height", &format!("{}px", cfg.WIDGET_HEIGHT.unwrap_or(26)), "dec_height", "inc_height", "rst_height", &mut y);
                draw_stepper("Icon Font Size", &format!("{}pt", cfg.FONT_SIZE), "dec_font", "inc_font", "rst_font", &mut y);
                draw_stepper("Corner Radius", &format!("{}px", cfg.CORNER_RADIUS), "dec_radius", "inc_radius", "rst_radius", &mut y);
                draw_stepper("Icon Offset Right", &format!("{}px", cfg.OFFSET_FROM_RIGHT), "dec_offset", "inc_offset", "rst_offset", &mut y);
                draw_stepper("Critical Low %", &format!("{}%", cfg.LOW_CRITICAL_PCT), "dec_crit", "inc_crit", "rst_crit", &mut y);

                // Customize Rows Button
                y += (4.0 * scale) as i32;
                buf.fill_rounded_rect(pad, y, w - pad, y + rh_set, 6, hover_color);
                buf.draw_text_aligned("Customize Rows & Order >", pad + (12.0 * scale) as i32, y + rh_set / 2, text_size, fg_color, false);
                self.hit_regions.push((RECT { left: pad, top: y, right: w - pad, bottom: y + rh_set }, "open_rows_config".into()));
                y += rh_set + (6.0 * scale) as i32;

                // Move Icon (Drag) Button
                buf.fill_rounded_rect(pad, y, w - pad, y + rh_set, 6, hover_color);
                buf.draw_icon_left(ICON_MOVE, pad + (10.0 * scale) as i32, y + rh_set / 2, icon_size, icon_color);
                buf.draw_text_aligned("Move Icon on Taskbar", pad + (32.0 * scale) as i32, y + rh_set / 2, text_size, fg_color, false);
                self.hit_regions.push((RECT { left: pad, top: y, right: w - pad, bottom: y + rh_set }, "move_icon_drag".into()));
                y += rh_set + (6.0 * scale) as i32;

                // Reset Defaults
                buf.draw_icon_left(ICON_RESET, pad, y + rh_set / 2, (12.0 * scale) as i32, danger_color);
                buf.draw_text_aligned("Reset all to Defaults", pad + (20.0 * scale) as i32, y + rh_set / 2, text_size - 1, danger_color, false);
                self.hit_regions.push((RECT { left: pad, top: y, right: pad + 160, bottom: y + rh_set }, "reset_defaults".into()));
            }

            PopupPage::RowsConfig => {
                let ty = y + (12.0 * scale) as i32;
                buf.draw_icon_left(ICON_BACK, pad, ty, icon_size, fg_color);
                buf.draw_text_aligned("Customize Rows", pad + (24.0 * scale) as i32, ty, title_size, fg_color, false);
                self.hit_regions.push((RECT { left: pad, top: y, right: pad + 80, bottom: y + 30 }, "nav_settings".into()));
                y += (28.0 * scale) as i32;

                buf.draw_line(pad, y, w - pad, y, 1, border_color);
                y += (10.0 * scale) as i32;

                for (i, row) in cfg.rows.iter().enumerate() {
                    let my = y + rh / 2;
                    let chk_ic = if row.visible { ICON_CHECK_ON } else { ICON_CHECK_OFF };
                    let chk_col = if row.visible { accent_color } else { fg2_color };

                    buf.draw_icon_left(chk_ic, pad, my, icon_size, chk_col);

                    let label_str = match row.id.as_str() {
                        "status" => "Status",
                        "power_mode" => "Power Mode",
                        "percentage" => "Percentage",
                        "health" => "Battery Health",
                        "time" => "Time Remaining",
                        "rate" => "Charge/Discharge Rate",
                        "elapsed" => "Session Elapsed",
                        "screen_on" => "Screen On Time",
                        "cycle_count" => "Cycle Count",
                        "temperature" => "Temperature",
                        "battery_estimate" => "Est. Runtime",
                        "graph" => "History Graph",
                        other => other,
                    };

                    buf.draw_text_aligned(label_str, pad + (24.0 * scale) as i32, my, text_size, if row.visible { fg_color } else { fg2_color }, false);

                    // Up / Down arrows
                    let dn_x = w - pad - (12.0 * scale) as i32;
                    let up_x = dn_x - (22.0 * scale) as i32;

                    buf.draw_icon(ICON_ARROW_UP, up_x, my, (12.0 * scale) as i32, if i > 0 { icon_color } else { fg2_color });
                    buf.draw_icon(ICON_ARROW_DN, dn_x, my, (12.0 * scale) as i32, if i + 1 < cfg.rows.len() { icon_color } else { fg2_color });

                    self.hit_regions.push((RECT { left: pad, top: y, right: up_x - 10, bottom: y + rh }, format!("toggle_row_{}", i)));
                    self.hit_regions.push((RECT { left: up_x - 10, top: y, right: up_x + 10, bottom: y + rh }, format!("row_up_{}", i)));
                    self.hit_regions.push((RECT { left: dn_x - 10, top: y, right: dn_x + 10, bottom: y + rh }, format!("row_dn_{}", i)));

                    y += rh;
                }
            }

            PopupPage::Apps => {
                let ty = y + (12.0 * scale) as i32;
                buf.draw_icon_left(ICON_BACK, pad, ty, icon_size, fg_color);
                buf.draw_text_aligned("App Battery Usage", pad + (24.0 * scale) as i32, ty, title_size, fg_color, false);
                self.hit_regions.push((RECT { left: pad, top: y, right: pad + 80, bottom: y + 30 }, "nav_dashboard".into()));
                y += (28.0 * scale) as i32;

                buf.draw_line(pad, y, w - pad, y, 1, border_color);
                y += (8.0 * scale) as i32;

                // Header columns
                let hmy = y + rh / 2;
                buf.draw_text_aligned("Process", pad + (26.0 * scale) as i32, hmy, text_size, fg2_color, false);
                buf.draw_text_aligned("Watts", w - pad - (30.0 * scale) as i32, hmy, text_size, fg2_color, true);
                y += rh;

                if self.process_tracker.is_none() {
                    self.process_tracker = Some(ProcessTracker::new());
                }

                if let Some(ref mut tracker) = self.process_tracker {
                    let total_watts = self.hw_info.rate_mw.map(|mw| (mw.abs() as f64) / 1000.0).unwrap_or(15.0);
                    self.apps_list = tracker.update(total_watts);
                }

                let visible_count = 8;
                let start = self.app_scroll.min(self.apps_list.len().saturating_sub(visible_count));
                let end = (start + visible_count).min(self.apps_list.len());

                for (_idx, app) in self.apps_list[start..end].iter().enumerate() {
                    let my = y + rh / 2;

                    // App Badge Circle with Initial
                    let circle_r = (8.0 * scale) as i32;
                    let cx_badge = pad + circle_r + 2;
                    let initial_col = match app.name.chars().next().unwrap_or('?').to_ascii_uppercase() {
                        'A'..='F' => 0xFF2196F3,
                        'G'..='L' => 0xFF4CAF50,
                        'M'..='R' => 0xFFFF9800,
                        _ => 0xFF9C27B0,
                    };
                    buf.fill_rounded_rect(cx_badge - circle_r, my - circle_r, cx_badge + circle_r, my + circle_r, circle_r, initial_col);
                    let init_char = app.name.chars().next().unwrap_or('?').to_ascii_uppercase().to_string();
                    buf.draw_text(&init_char, cx_badge, my, (9.0 * scale) as i32, 0x00FFFFFF, true);

                    let name_trunc = if app.name.len() > 17 { format!("{}...", &app.name[..14]) } else { app.name.clone() };
                    buf.draw_text_aligned(&name_trunc, pad + (26.0 * scale) as i32, my, text_size, fg_color, false);
                    buf.draw_text_aligned(&format!("{:.2} W", app.watts), w - pad - (28.0 * scale) as i32, my, text_size, fg_color, true);

                    // Kill icon
                    let kill_x = w - pad - (10.0 * scale) as i32;
                    buf.draw_icon(ICON_CLOSE, kill_x, my, (11.0 * scale) as i32, danger_color);
                    self.hit_regions.push((RECT { left: kill_x - 12, top: y, right: kill_x + 12, bottom: y + rh }, format!("kill_pid_{}", app.pid)));

                    y += rh;
                }

                // Summary footer
                y += (6.0 * scale) as i32;
                buf.draw_line(pad, y, w - pad, y, 1, border_color);
                y += (8.0 * scale) as i32;

                let tot_w: f64 = self.apps_list.iter().map(|a| a.watts).sum();
                let actual_w = self.hw_info.rate_mw.map(|mw| mw.abs() as f64 / 1000.0).unwrap_or(tot_w);
                buf.draw_text_aligned(&format!("Total: {:.2} W", tot_w), pad, y + rh / 2, text_size, fg_color, false);
                buf.draw_text_aligned(&format!("({:.2} W meas.)", actual_w), w - pad, y + rh / 2, text_size, fg2_color, true);
            }

            PopupPage::About => {
                let ty = y + (12.0 * scale) as i32;
                buf.draw_icon_left(ICON_BACK, pad, ty, icon_size, fg_color);
                buf.draw_text_aligned("About WinCity", pad + (24.0 * scale) as i32, ty, title_size, fg_color, false);
                self.hit_regions.push((RECT { left: pad, top: y, right: pad + 80, bottom: y + 30 }, "nav_dashboard".into()));
                y += (28.0 * scale) as i32;

                buf.draw_line(pad, y, w - pad, y, 1, border_color);
                y += (14.0 * scale) as i32;

                // Header Title & Subtitle centered
                buf.draw_text("WinCity Native", w / 2, y, title_size + (2.0 * scale) as i32, fg_color, true);
                y += (20.0 * scale) as i32;
                buf.draw_text("Rust Edition • v1.1.0 • Ultra-low overhead", w / 2, y, text_size - 1, fg2_color, false);
                y += (22.0 * scale) as i32;

                // Hardware Telemetry Card Container
                let card_h = (112.0 * scale) as i32;
                let c_bg = parse_hex_color(&theme.graph_container);
                buf.fill_rounded_rect(pad, y, w - pad, y + card_h, 8, c_bg);
                buf.outline_rounded_rect(pad, y, w - pad, y + card_h, 8, 1, border_color);

                let mut cy_inner = y + (12.0 * scale) as i32;
                let rh_sp = (18.0 * scale) as i32;
                let c_pad = pad + (12.0 * scale) as i32;

                buf.draw_icon_left(ICON_HEALTH, c_pad, cy_inner, (12.0 * scale) as i32, icon_color);
                buf.draw_text_aligned("Hardware Telemetry", c_pad + (18.0 * scale) as i32, cy_inner, text_size, fg_color, false);
                cy_inner += (20.0 * scale) as i32;

                let des = self.hw_info.designed_mwh.map(|m| format!("{} mWh", m)).unwrap_or_else(|| "N/A".into());
                let full = self.hw_info.full_mwh.map(|m| format!("{} mWh", m)).unwrap_or_else(|| "N/A".into());
                let health = battery::fmt_health(self.hw_info.designed_mwh, self.hw_info.full_mwh);
                let cyc = self.hw_info.cycle_count.map(|c| format!("{}", c)).unwrap_or_else(|| "N/A".into());

                buf.draw_text_aligned("• Designed Capacity:", c_pad, cy_inner, text_size - 1, fg2_color, false);
                buf.draw_text_aligned(&des, w - c_pad, cy_inner, text_size - 1, fg_color, true);
                cy_inner += rh_sp;

                buf.draw_text_aligned("• Full Charge Capacity:", c_pad, cy_inner, text_size - 1, fg2_color, false);
                buf.draw_text_aligned(&full, w - c_pad, cy_inner, text_size - 1, fg_color, true);
                cy_inner += rh_sp;

                buf.draw_text_aligned("• Battery Health:", c_pad, cy_inner, text_size - 1, fg2_color, false);
                buf.draw_text_aligned(&health, w - c_pad, cy_inner, text_size - 1, fg_color, true);
                cy_inner += rh_sp;

                buf.draw_text_aligned("• Cycle Count:", c_pad, cy_inner, text_size - 1, fg2_color, false);
                buf.draw_text_aligned(&cyc, w - c_pad, cy_inner, text_size - 1, fg_color, true);

                y += card_h + (16.0 * scale) as i32;

                // GitHub + Donate Buttons
                let btn_w = (w - 2 * pad - (10.0 * scale) as i32) / 2;
                let btn_h = (32.0 * scale) as i32;

                // GitHub
                buf.fill_rounded_rect(pad, y, pad + btn_w, y + btn_h, 6, hover_color);
                buf.outline_rounded_rect(pad, y, pad + btn_w, y + btn_h, 6, 1, border_color);
                buf.draw_icon_left(ICON_APPS, pad + (10.0 * scale) as i32, y + btn_h / 2, (12.0 * scale) as i32, icon_color);
                buf.draw_text_aligned("GitHub", pad + (30.0 * scale) as i32, y + btn_h / 2, text_size, fg_color, false);
                self.hit_regions.push((RECT { left: pad, top: y, right: pad + btn_w, bottom: y + btn_h }, "open_github".into()));

                // Donate
                let don_x0 = pad + btn_w + (10.0 * scale) as i32;
                buf.fill_rounded_rect(don_x0, y, w - pad, y + btn_h, 6, hover_color);
                buf.outline_rounded_rect(don_x0, y, w - pad, y + btn_h, 6, 1, border_color);
                buf.draw_text("☕ Donate", don_x0 + btn_w / 2, y + btn_h / 2, text_size, accent_color, false);
                self.hit_regions.push((RECT { left: don_x0, top: y, right: w - pad, bottom: y + btn_h }, "open_donate".into()));

                y += btn_h + (16.0 * scale) as i32;
                buf.draw_text("Created with ❤️ by Ahmar Zaidi", w / 2, y, text_size - 1, fg2_color, false);
            }

            _ => {}
        }

        // Present to Layered Window
        let mut rect = RECT::default();
        unsafe {
            let _ = GetWindowRect(self.popup_hwnd, &mut rect);
        }
        buf.present_to_window(self.popup_hwnd, rect.left, rect.top);
    }

    pub fn handle_scroll(&mut self, delta: i16) {
        if self.page == PopupPage::Apps {
            if delta > 0 {
                self.app_scroll = self.app_scroll.saturating_sub(1);
            } else if delta < 0 {
                if self.app_scroll + 8 < self.apps_list.len() {
                    self.app_scroll += 1;
                }
            }
            self.redraw();
        }
    }

    fn notify_widget_settings_changed(&mut self) {
        self.config_mgr.save_config();
        unsafe {
            let _ = PostMessageW(
                self.widget_hwnd,
                WM_APP_SETTINGS_CHANGED,
                WPARAM(0),
                LPARAM(0),
            );
        }
        self.reposition();
        self.redraw();
    }

    pub fn handle_click(&mut self, x: i32, y: i32) {
        for (rect, action) in &self.hit_regions {
            if x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom {
                let action_str = action.clone();
                match action_str.as_str() {
                    "nav_dashboard" => {
                        self.page = PopupPage::Dashboard;
                        self.reposition();
                        self.redraw();
                    }
                    "nav_settings" => {
                        self.page = PopupPage::Settings;
                        self.reposition();
                        self.redraw();
                    }
                    "nav_apps" => {
                        self.page = PopupPage::Apps;
                        self.reposition();
                        self.redraw();
                    }
                    "nav_about" => {
                        self.page = PopupPage::About;
                        self.reposition();
                        self.redraw();
                    }
                    "nav_quit" => {
                        unsafe {
                            PostQuitMessage(0);
                        }
                    }
                    "open_rows_config" => {
                        self.page = PopupPage::RowsConfig;
                        self.reposition();
                        self.redraw();
                    }
                    "move_icon_drag" => {
                        // Nudge right offset
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.OFFSET_FROM_RIGHT = (cfg.OFFSET_FROM_RIGHT + 20) % 400;
                        }
                        self.notify_widget_settings_changed();
                    }
                    "open_github" => {
                        unsafe {
                            let _ = ShellExecuteW(
                                None,
                                w!("open"),
                                w!("https://github.com/AhmarZaidi/wincity"),
                                PCWSTR::null(),
                                PCWSTR::null(),
                                SW_SHOW,
                            );
                        }
                    }
                    "open_donate" => {
                        unsafe {
                            let _ = ShellExecuteW(
                                None,
                                w!("open"),
                                w!("https://github.com/sponsors/AhmarZaidi"),
                                PCWSTR::null(),
                                PCWSTR::null(),
                                SW_SHOW,
                            );
                        }
                    }
                    "graph_prev" => {
                        let state = self.config_mgr.state.lock().unwrap();
                        if self.graph_index == -1 && !state.sessions.is_empty() {
                            self.graph_index = state.sessions.len() as i32 - 1;
                        } else if self.graph_index > 0 {
                            self.graph_index -= 1;
                        }
                        drop(state);
                        self.redraw();
                    }
                    "graph_next" => {
                        let state = self.config_mgr.state.lock().unwrap();
                        if self.graph_index >= 0 {
                            if self.graph_index + 1 < state.sessions.len() as i32 {
                                self.graph_index += 1;
                            } else {
                                self.graph_index = -1; // back to live
                            }
                        }
                        drop(state);
                        self.redraw();
                    }
                    "toggle_autostart" => {
                        let cur = system::is_autostart_enabled();
                        system::set_autostart(!cur, self.config_mgr.base_dir());
                        self.redraw();
                    }
                    "inc_popup_font" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.POPUP_TEXT_SIZE = (cfg.POPUP_TEXT_SIZE + 1).min(24);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "dec_popup_font" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.POPUP_TEXT_SIZE = (cfg.POPUP_TEXT_SIZE.saturating_sub(1)).max(8);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "rst_popup_font" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.POPUP_TEXT_SIZE = 12;
                        }
                        self.notify_widget_settings_changed();
                    }
                    "inc_popup_ref" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.POPUP_REFRESH_INTERVAL = (cfg.POPUP_REFRESH_INTERVAL + 0.5).min(30.0);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "dec_popup_ref" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.POPUP_REFRESH_INTERVAL = (cfg.POPUP_REFRESH_INTERVAL - 0.5).max(0.5);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "rst_popup_ref" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.POPUP_REFRESH_INTERVAL = 1.0;
                        }
                        self.notify_widget_settings_changed();
                    }
                    "inc_poll" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.UPDATE_INTERVAL = (cfg.UPDATE_INTERVAL + 1).min(60);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "dec_poll" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.UPDATE_INTERVAL = (cfg.UPDATE_INTERVAL.saturating_sub(1)).max(1);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "rst_poll" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.UPDATE_INTERVAL = 10;
                        }
                        self.notify_widget_settings_changed();
                    }
                    "inc_width" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.WIDGET_WIDTH = (cfg.WIDGET_WIDTH + 2).min(160);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "dec_width" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.WIDGET_WIDTH = (cfg.WIDGET_WIDTH - 2).max(30);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "rst_width" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.WIDGET_WIDTH = 56;
                        }
                        self.notify_widget_settings_changed();
                    }
                    "inc_height" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            let h = cfg.WIDGET_HEIGHT.unwrap_or(26) + 2;
                            cfg.WIDGET_HEIGHT = Some(h.min(50));
                        }
                        self.notify_widget_settings_changed();
                    }
                    "dec_height" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            let h = cfg.WIDGET_HEIGHT.unwrap_or(26) - 2;
                            cfg.WIDGET_HEIGHT = Some(h.max(14));
                        }
                        self.notify_widget_settings_changed();
                    }
                    "rst_height" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.WIDGET_HEIGHT = Some(26);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "inc_font" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.FONT_SIZE = (cfg.FONT_SIZE + 1).min(36);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "dec_font" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.FONT_SIZE = (cfg.FONT_SIZE - 1).max(10);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "rst_font" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.FONT_SIZE = 22;
                        }
                        self.notify_widget_settings_changed();
                    }
                    "inc_radius" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.CORNER_RADIUS = (cfg.CORNER_RADIUS + 1).min(16);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "dec_radius" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.CORNER_RADIUS = (cfg.CORNER_RADIUS - 1).max(0);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "rst_radius" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.CORNER_RADIUS = 4;
                        }
                        self.notify_widget_settings_changed();
                    }
                    "inc_offset" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.OFFSET_FROM_RIGHT = (cfg.OFFSET_FROM_RIGHT + 5).min(500);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "dec_offset" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.OFFSET_FROM_RIGHT = (cfg.OFFSET_FROM_RIGHT - 5).max(0);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "rst_offset" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.OFFSET_FROM_RIGHT = 130;
                        }
                        self.notify_widget_settings_changed();
                    }
                    "inc_crit" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.LOW_CRITICAL_PCT = (cfg.LOW_CRITICAL_PCT + 2).min(50);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "dec_crit" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.LOW_CRITICAL_PCT = (cfg.LOW_CRITICAL_PCT.saturating_sub(2)).max(2);
                        }
                        self.notify_widget_settings_changed();
                    }
                    "rst_crit" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            cfg.LOW_CRITICAL_PCT = 10;
                        }
                        self.notify_widget_settings_changed();
                    }
                    "reset_defaults" => {
                        {
                            let mut cfg = self.config_mgr.config.lock().unwrap();
                            *cfg = crate::config::AppConfig::default();
                        }
                        self.notify_widget_settings_changed();
                    }
                    s if s.starts_with("toggle_row_") => {
                        if let Ok(idx) = s["toggle_row_".len()..].parse::<usize>() {
                            {
                                let mut cfg = self.config_mgr.config.lock().unwrap();
                                if idx < cfg.rows.len() {
                                    cfg.rows[idx].visible = !cfg.rows[idx].visible;
                                }
                            }
                            self.notify_widget_settings_changed();
                        }
                    }
                    s if s.starts_with("row_up_") => {
                        if let Ok(idx) = s["row_up_".len()..].parse::<usize>() {
                            if idx > 0 {
                                {
                                    let mut cfg = self.config_mgr.config.lock().unwrap();
                                    if idx < cfg.rows.len() {
                                        cfg.rows.swap(idx, idx - 1);
                                    }
                                }
                                self.notify_widget_settings_changed();
                            }
                        }
                    }
                    s if s.starts_with("row_dn_") => {
                        if let Ok(idx) = s["row_dn_".len()..].parse::<usize>() {
                            {
                                let mut cfg = self.config_mgr.config.lock().unwrap();
                                if idx + 1 < cfg.rows.len() {
                                    cfg.rows.swap(idx, idx + 1);
                                }
                            }
                            self.notify_widget_settings_changed();
                        }
                    }
                    s if s.starts_with("kill_pid_") => {
                        if let Ok(pid) = s["kill_pid_".len()..].parse::<u32>() {
                            unsafe {
                                use windows::Win32::System::Threading::{OpenProcess, TerminateProcess, PROCESS_TERMINATE};
                                if let Ok(hproc) = OpenProcess(PROCESS_TERMINATE, false, pid) {
                                    if !hproc.is_invalid() {
                                        let _ = TerminateProcess(hproc, 1);
                                        let _ = windows::Win32::Foundation::CloseHandle(hproc);
                                    }
                                }
                            }
                            self.redraw();
                        }
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

            let x0 = pop_rect.left.min(wid_rect.left) - 10;
            let x1 = pop_rect.right.max(wid_rect.right) + 10;
            let y0 = pop_rect.top.min(wid_rect.top) - 10;
            let y1 = pop_rect.bottom.max(wid_rect.bottom) + 10;

            if pt.x < x0 || pt.x > x1 || pt.y < y0 || pt.y > y1 {
                self.close();
            }
        }
    }
}

fn format_epoch_hm(epoch_sec: f64) -> String {
    let now_ep = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
    let diff_sec = (epoch_sec - now_ep) as i64;

    unsafe {
        let st = GetLocalTime();
        let mut total_min = st.wHour as i64 * 60 + st.wMinute as i64 + (diff_sec + 30) / 60;
        while total_min < 0 {
            total_min += 24 * 60;
        }
        total_min %= 24 * 60;
        let h = total_min / 60;
        let m = total_min % 60;
        let ampm = if h >= 12 { "PM" } else { "AM" };
        let hour = if h % 12 == 0 { 12 } else { h % 12 };
        format!("{}:{:02} {}", hour, m, ampm)
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
        WM_MOUSEWHEEL => {
            let delta = ((wparam.0 >> 16) & 0xFFFF) as i16;
            popup.handle_scroll(delta);
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
