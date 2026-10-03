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
    std::panic::set_hook(Box::new(|info| {
        let _ = std::fs::write("data/panic.log", format!("{:?}", info));
    }));

    // 1. Single-instance protection via named mutex
    let _mutex = unsafe {
        windows::Win32::Foundation::SetLastError(windows::Win32::Foundation::WIN32_ERROR(0));
        let mutex_name = w!("Local\\WinCity_Native_Rust_v4");
        let mutex = CreateMutexW(None, true, mutex_name);
        if GetLastError().0 == 183 {
            // Already running
            return;
        }
        mutex.ok()
    };

    // 2. High-DPI per-monitor awareness
    system::init_dpi_awareness();

    // 3. Load configuration & runtime state
    let config_mgr = config::ConfigManager::new();

    // 4. Start Battery Widget
    let widget = widget::BatteryWidget::new(config_mgr);
    widget.run();
}
