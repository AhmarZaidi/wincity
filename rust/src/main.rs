#![windows_subsystem = "windows"]

mod battery;
mod config;
mod popup;
mod render;
mod system;
mod widget;

use windows::core::w;
use windows::Win32::Foundation::GetLastError;
use windows::Win32::System::Threading::CreateMutexW;

fn main() {
    // 1. Single-instance protection via named mutex
    unsafe {
        let mutex_name = w!("WinCity_SingleInstance_Mutex_Rust");
        let mutex = CreateMutexW(None, false, mutex_name);
        if mutex.is_err() || GetLastError().0 == 183 {
            // Already running
            return;
        }
    }

    // 2. High-DPI per-monitor awareness
    system::init_dpi_awareness();

    // 3. Load configuration & runtime state
    let config_mgr = config::ConfigManager::new();

    // 4. Start Battery Widget
    let widget = widget::BatteryWidget::new(config_mgr);
    widget.run();
}
