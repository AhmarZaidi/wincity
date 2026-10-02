#![allow(dead_code)]

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RowItem {
    pub id: String,
    pub visible: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThemeColors {
    pub bg: String,
    pub fg: String,
    pub fg2: String,
    pub border: String,
    pub icon: String,
    pub danger: String,
    pub hover: String,
    pub widget_body: String,
    pub widget_nub: String,
    pub widget_outline: String,
    pub widget_text: String,
    pub graph_container: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphColors {
    pub charging_fill: String,
    pub charging_line: String,
    pub low_fill: String,
    pub low_line: String,
    pub normal_fill: String,
    pub normal_line: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WidgetColors {
    pub fill_charging: String,
    pub fill_low: String,
    pub fill_saver: String,
    pub fill_normal: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColorsConfig {
    pub dark: ThemeColors,
    pub light: ThemeColors,
    pub graph: GraphColors,
    pub widget: WidgetColors,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[allow(non_snake_case)]
pub struct AppConfig {
    #[serde(default = "default_widget_width")]
    pub WIDGET_WIDTH: i32,
    #[serde(default = "default_widget_height")]
    pub WIDGET_HEIGHT: Option<i32>,
    #[serde(default)]
    pub WIDGET_X: Option<i32>,
    #[serde(default)]
    pub WIDGET_Y: Option<i32>,
    #[serde(default = "default_offset_right")]
    pub OFFSET_FROM_RIGHT: i32,
    #[serde(default)]
    pub OFFSET_FROM_TOP: Option<i32>,
    #[serde(default = "default_update_interval")]
    pub UPDATE_INTERVAL: u64,
    #[serde(default = "default_popup_refresh")]
    pub POPUP_REFRESH_INTERVAL: f64,
    #[serde(default = "default_low_pct")]
    pub LOW_PCT: u32,
    #[serde(default = "default_poll_ms")]
    pub VISIBILITY_POLL_MS: u32,
    #[serde(default = "default_corner_radius")]
    pub CORNER_RADIUS: i32,
    #[serde(default)]
    pub FILL_PADDING: i32,
    #[serde(default)]
    pub FILL_RIGHT_EXTEND: i32,
    #[serde(default = "default_font_size")]
    pub FONT_SIZE: i32,
    #[serde(default = "default_render_scale")]
    pub RENDER_SCALE: i32,
    #[serde(default = "default_outline_width")]
    pub OUTLINE_WIDTH: i32,
    #[serde(default = "default_popup_y_offset")]
    pub POPUP_Y_OFFSET: i32,
    #[serde(default = "default_popup_corner_radius")]
    pub POPUP_CORNER_RADIUS: i32,
    #[serde(default = "default_popup_title_size")]
    pub POPUP_TITLE_SIZE: i32,
    #[serde(default = "default_popup_text_size")]
    pub POPUP_TEXT_SIZE: i32,
    #[serde(default = "default_popup_icon_size")]
    pub POPUP_ICON_SIZE: i32,
    #[serde(default = "default_graph_height")]
    pub GRAPH_HEIGHT: i32,
    #[serde(default = "default_low_critical_pct")]
    pub LOW_CRITICAL_PCT: u32,
    #[serde(default = "default_rows")]
    pub rows: Vec<RowItem>,
    #[serde(default = "default_colors")]
    pub colors: ColorsConfig,
}

fn default_widget_width() -> i32 { 56 }
fn default_widget_height() -> Option<i32> { Some(26) }
fn default_offset_right() -> i32 { 130 }
fn default_update_interval() -> u64 { 10 }
fn default_popup_refresh() -> f64 { 1.0 }
fn default_low_pct() -> u32 { 20 }
fn default_poll_ms() -> u32 { 1000 }
fn default_corner_radius() -> i32 { 8 }
fn default_font_size() -> i32 { 22 }
fn default_render_scale() -> i32 { 8 }
fn default_outline_width() -> i32 { 1 }
fn default_popup_y_offset() -> i32 { 20 }
fn default_popup_corner_radius() -> i32 { 12 }
fn default_popup_title_size() -> i32 { 16 }
fn default_popup_text_size() -> i32 { 12 }
fn default_popup_icon_size() -> i32 { 16 }
fn default_graph_height() -> i32 { 140 }
fn default_low_critical_pct() -> u32 { 10 }

fn default_rows() -> Vec<RowItem> {
    vec![
        RowItem { id: "status".into(), visible: true },
        RowItem { id: "power_mode".into(), visible: true },
        RowItem { id: "percentage".into(), visible: true },
        RowItem { id: "health".into(), visible: true },
        RowItem { id: "time".into(), visible: true },
        RowItem { id: "rate".into(), visible: true },
        RowItem { id: "elapsed".into(), visible: true },
        RowItem { id: "battery_estimate".into(), visible: true },
        RowItem { id: "graph".into(), visible: true },
        RowItem { id: "screen_on".into(), visible: false },
        RowItem { id: "cycle_count".into(), visible: false },
        RowItem { id: "temperature".into(), visible: false },
    ]
}

fn default_colors() -> ColorsConfig {
    ColorsConfig {
        dark: ThemeColors {
            bg: "#1c1c1c".into(),
            fg: "#ffffff".into(),
            fg2: "#9d9d9d".into(),
            border: "#3c3c3c".into(),
            icon: "#c8c8c8".into(),
            danger: "#e04040".into(),
            hover: "#2d2d2d".into(),
            widget_body: "#1a1a1a".into(),
            widget_nub: "#aaaaaa".into(),
            widget_outline: "#888888".into(),
            widget_text: "#ffffff".into(),
            graph_container: "#2c2c32".into(),
        },
        light: ThemeColors {
            bg: "#f9f9f9".into(),
            fg: "#1a1a1a".into(),
            fg2: "#5c5c5c".into(),
            border: "#dedede".into(),
            icon: "#555555".into(),
            danger: "#c42b1c".into(),
            hover: "#ebebeb".into(),
            widget_body: "#ffffff".into(),
            widget_nub: "#1e1e1e".into(),
            widget_outline: "#1e1e1e".into(),
            widget_text: "#1a1a1a".into(),
            graph_container: "#cdcfd7".into(),
        },
        graph: GraphColors {
            charging_fill: "#0078d45f".into(),
            charging_line: "#008ce6eb".into(),
            low_fill: "#f0be2864".into(),
            low_line: "#d7a00ff0".into(),
            normal_fill: "#4cbb6464".into(),
            normal_line: "#28aa46f0".into(),
        },
        widget: WidgetColors {
            fill_charging: "#3296f0".into(),
            fill_low: "#dc3232".into(),
            fill_saver: "#f0be28".into(),
            fill_normal: "#3cc850".into(),
        },
    }
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            WIDGET_WIDTH: default_widget_width(),
            WIDGET_HEIGHT: default_widget_height(),
            WIDGET_X: None,
            WIDGET_Y: None,
            OFFSET_FROM_RIGHT: default_offset_right(),
            OFFSET_FROM_TOP: None,
            UPDATE_INTERVAL: default_update_interval(),
            POPUP_REFRESH_INTERVAL: default_popup_refresh(),
            LOW_PCT: default_low_pct(),
            VISIBILITY_POLL_MS: default_poll_ms(),
            CORNER_RADIUS: default_corner_radius(),
            FILL_PADDING: 0,
            FILL_RIGHT_EXTEND: 0,
            FONT_SIZE: default_font_size(),
            RENDER_SCALE: default_render_scale(),
            OUTLINE_WIDTH: default_outline_width(),
            POPUP_Y_OFFSET: default_popup_y_offset(),
            POPUP_CORNER_RADIUS: default_popup_corner_radius(),
            POPUP_TITLE_SIZE: default_popup_title_size(),
            POPUP_TEXT_SIZE: default_popup_text_size(),
            POPUP_ICON_SIZE: default_popup_icon_size(),
            GRAPH_HEIGHT: default_graph_height(),
            LOW_CRITICAL_PCT: default_low_critical_pct(),
            rows: default_rows(),
            colors: default_colors(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionEntry {
    #[serde(rename = "type")]
    pub session_type: String,
    pub start: f64,
    pub end: f64,
    pub points: Vec<Vec<f64>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RuntimeState {
    #[serde(default = "default_schema")]
    pub schema: u32,
    #[serde(default)]
    pub discharge_start_epoch: Option<f64>,
    #[serde(default)]
    pub charge_start_epoch: Option<f64>,
    #[serde(default)]
    pub show_percent: bool,
    #[serde(default)]
    pub history: Vec<Vec<f64>>,
    #[serde(default)]
    pub sessions: Vec<SessionEntry>,
}

fn default_schema() -> u32 { 1 }

pub struct ConfigManager {
    base_dir: PathBuf,
    pub config: Mutex<AppConfig>,
    pub state: Mutex<RuntimeState>,
}

impl ConfigManager {
    pub fn new() -> Arc<Self> {
        let base_dir = Self::find_base_dir();
        let config = Self::load_config(&base_dir);
        let state = Self::load_state(&base_dir);

        Arc::new(Self {
            base_dir,
            config: Mutex::new(config),
            state: Mutex::new(state),
        })
    }

    pub fn base_dir(&self) -> &Path {
        &self.base_dir
    }

    pub fn data_dir(&self) -> PathBuf {
        self.base_dir.join("data")
    }

    pub fn assets_dir(&self) -> PathBuf {
        self.base_dir.join("assets")
    }

    fn find_base_dir() -> PathBuf {
        if let Ok(exe_path) = std::env::current_exe() {
            if let Some(parent) = exe_path.parent() {
                // Check if running from rust/target/release or rust/target/debug
                let mut p = parent;
                for _ in 0..4 {
                    if p.join("data").exists() || p.join("assets").exists() {
                        return p.to_path_buf();
                    }
                    if let Some(up) = p.parent() {
                        p = up;
                    } else {
                        break;
                    }
                }
            }
        }
        if let Ok(cwd) = std::env::current_dir() {
            if cwd.join("data").exists() {
                return cwd;
            }
            if let Some(parent) = cwd.parent() {
                if parent.join("data").exists() {
                    return parent.to_path_buf();
                }
            }
        }
        PathBuf::from(".")
    }

    fn load_config(base_dir: &Path) -> AppConfig {
        let config_file = base_dir.join("data").join("config.json");
        if let Ok(content) = fs::read_to_string(&config_file) {
            if let Ok(cfg) = serde_json::from_str::<AppConfig>(&content) {
                return cfg;
            }
        }
        let default_cfg = AppConfig::default();
        let _ = fs::create_dir_all(base_dir.join("data"));
        if let Ok(json) = serde_json::to_string_pretty(&default_cfg) {
            let _ = fs::write(config_file, json);
        }
        default_cfg
    }

    pub fn save_config(&self) {
        let cfg = self.config.lock().unwrap().clone();
        let data_dir = self.data_dir();
        let _ = fs::create_dir_all(&data_dir);
        let config_file = data_dir.join("config.json");
        let tmp_file = data_dir.join("config.json.tmp");
        if let Ok(json) = serde_json::to_string_pretty(&cfg) {
            if fs::write(&tmp_file, json).is_ok() {
                let _ = fs::rename(tmp_file, config_file);
            }
        }
    }

    fn load_state(base_dir: &Path) -> RuntimeState {
        let state_file = base_dir.join("data").join("state.json");
        if let Ok(content) = fs::read_to_string(state_file) {
            if let Ok(st) = serde_json::from_str::<RuntimeState>(&content) {
                return st;
            }
        }
        RuntimeState::default()
    }

    pub fn save_state(&self) {
        let st = self.state.lock().unwrap().clone();
        let data_dir = self.data_dir();
        let _ = fs::create_dir_all(&data_dir);
        let state_file = data_dir.join("state.json");
        let tmp_file = data_dir.join("state.json.tmp");
        if let Ok(json) = serde_json::to_string_pretty(&st) {
            if fs::write(&tmp_file, json).is_ok() {
                let _ = fs::rename(tmp_file, state_file);
            }
        }
    }
}
