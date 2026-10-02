use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use windows::core::{w, GUID, PCWSTR};
use windows::Win32::Foundation::RECT;
use windows::Win32::UI::HiDpi::{
    GetDpiForSystem, SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows::Win32::UI::WindowsAndMessaging::{
    FindWindowW, GetClassNameW, GetForegroundWindow, GetSystemMetrics, GetWindowRect,
    IsWindowVisible, SM_CXSCREEN, SM_CYSCREEN,
};

use windows::Win32::System::LibraryLoader::{GetProcAddress, LoadLibraryW};

pub fn init_dpi_awareness() {
    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    }
}

pub fn get_dpi_scale() -> f64 {
    unsafe {
        let dpi = GetDpiForSystem();
        if dpi > 0 {
            dpi as f64 / 96.0
        } else {
            1.0
        }
    }
}

pub fn get_taskbar_rect() -> RECT {
    unsafe {
        if let Ok(tb_hwnd) = FindWindowW(w!("Shell_TrayWnd"), PCWSTR::null()) {
            if !tb_hwnd.is_invalid() {
                let mut rect = RECT::default();
                if GetWindowRect(tb_hwnd, &mut rect).is_ok() {
                    if rect.right > rect.left && rect.bottom > rect.top {
                        return rect;
                    }
                }
            }
        }
        let sw = GetSystemMetrics(SM_CXSCREEN);
        let sh = GetSystemMetrics(SM_CYSCREEN);
        RECT {
            left: 0,
            top: sh - 48,
            right: sw,
            bottom: sh,
        }
    }
}

pub fn should_show_widget() -> bool {
    unsafe {
        let tb_hwnd = match FindWindowW(w!("Shell_TrayWnd"), PCWSTR::null()) {
            Ok(h) => h,
            Err(_) => return false,
        };

        if tb_hwnd.is_invalid() || !IsWindowVisible(tb_hwnd).as_bool() {
            return false;
        }
        let mut tb_rect = RECT::default();
        if GetWindowRect(tb_hwnd, &mut tb_rect).is_ok() {
            if (tb_rect.bottom - tb_rect.top).min(tb_rect.right - tb_rect.left) <= 6 {
                return false;
            }
        }

        let fg = GetForegroundWindow();
        if !fg.is_invalid() {
            let mut cls_buf = [0u16; 256];
            let len = GetClassNameW(fg, &mut cls_buf);
            if len > 0 {
                let cls_str = String::from_utf16_lossy(&cls_buf[..len as usize]);
                if !["Shell_TrayWnd", "Progman", "WorkerW", ""].contains(&cls_str.as_str()) {
                    let mut fg_rect = RECT::default();
                    if GetWindowRect(fg, &mut fg_rect).is_ok() {
                        let sw = GetSystemMetrics(SM_CXSCREEN);
                        let sh = GetSystemMetrics(SM_CYSCREEN);
                        if fg_rect.left <= 0
                            && fg_rect.top <= 0
                            && fg_rect.right >= sw
                            && fg_rect.bottom >= sh
                        {
                            return false;
                        }
                    }
                }
            }
        }
        true
    }
}

pub fn is_dark_mode() -> bool {
    use std::ffi::c_void;
    #[repr(C)]
    struct HKEY__ {
        unused: i32,
    }
    type HKEY = *mut HKEY__;
    const HKEY_CURRENT_USER: HKEY = 0x80000002u32 as usize as HKEY;
    const RRF_RT_REG_DWORD: u32 = 0x00000010;

    #[link(name = "advapi32")]
    extern "system" {
        fn RegGetValueW(
            hkey: HKEY,
            lpsubkey: *const u16,
            lpvalue: *const u16,
            dwflags: u32,
            pdwtype: *mut u32,
            pvdata: *mut c_void,
            pcbdata: *mut u32,
        ) -> i32;
    }

    let subkey: Vec<u16> = "Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize\0"
        .encode_utf16()
        .collect();
    let val_name: Vec<u16> = "AppsUseLightTheme\0".encode_utf16().collect();
    let mut data: u32 = 0;
    let mut data_size: u32 = std::mem::size_of::<u32>() as u32;

    unsafe {
        let res = RegGetValueW(
            HKEY_CURRENT_USER,
            subkey.as_ptr(),
            val_name.as_ptr(),
            RRF_RT_REG_DWORD,
            std::ptr::null_mut(),
            &mut data as *mut u32 as *mut c_void,
            &mut data_size,
        );
        if res == 0 {
            data == 0
        } else {
            true // default dark
        }
    }
}

pub fn get_power_mode() -> String {
    unsafe {
        let mod_name = w!("powrprof.dll");
        if let Ok(hmod) = LoadLibraryW(mod_name) {
            if !hmod.is_invalid() {
                if let Some(func_ptr) = GetProcAddress(hmod, windows::core::s!("PowerGetEffectiveOverlayScheme")) {
                    type FnPowerGetEffectiveOverlayScheme = unsafe extern "system" fn(*mut GUID) -> u32;
                    let func: FnPowerGetEffectiveOverlayScheme = std::mem::transmute(func_ptr);
                    let mut scheme = GUID::default();
                    if func(&mut scheme) == 0 {
                        let s = format!("{:?}", scheme).to_uppercase();
                        if s.contains("961CC777-2547-4F9D-8174-7D86181B8A7A") {
                            return "Battery Saver".to_string();
                        }
                        if s.contains("DED574B5-45A0-4F42-8734-20B1DE8D37B3") {
                            return "Best Performance".to_string();
                        }
                    }
                }
            }
        }
    }
    "Balanced".to_string()
}

pub fn get_startup_shortcut_path() -> PathBuf {
    if let Ok(appdata) = std::env::var("APPDATA") {
        PathBuf::from(appdata)
            .join("Microsoft")
            .join("Windows")
            .join("Start Menu")
            .join("Programs")
            .join("Startup")
            .join("WinCity.lnk")
    } else {
        PathBuf::from(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\WinCity.lnk")
    }
}

pub fn is_autostart_enabled() -> bool {
    get_startup_shortcut_path().exists()
}

pub fn set_autostart(enable: bool, base_dir: &Path) -> bool {
    let lnk = get_startup_shortcut_path();
    if enable {
        let exe_path = match std::env::current_exe() {
            Ok(p) => p,
            Err(_) => return false,
        };
        let icon_path = base_dir.join("assets").join("appicon.ico");
        create_shortcut(&exe_path, &lnk, "", base_dir, &icon_path)
    } else {
        if lnk.exists() {
            let _ = std::fs::remove_file(lnk);
        }
        true
    }
}

pub fn create_shortcut(
    target: &Path,
    shortcut_path: &Path,
    args: &str,
    working_dir: &Path,
    icon_path: &Path,
) -> bool {
    let target_str = target.to_string_lossy().replace('"', "\"\"");
    let shortcut_str = shortcut_path.to_string_lossy().replace('"', "\"\"");
    let args_str = args.replace('"', "\"\"");
    let working_dir_str = working_dir.to_string_lossy().replace('"', "\"\"");
    let icon_str = icon_path.to_string_lossy().replace('"', "\"\"");

    let vbs = format!(
        r#"Set oWS = CreateObject("WScript.Shell")
Set oLink = oWS.CreateShortcut("{shortcut}")
oLink.TargetPath = "{target}"
oLink.Arguments = "{args}"
oLink.WorkingDirectory = "{working_dir}"
if "{icon}" <> "" Then oLink.IconLocation = "{icon}"
oLink.Description = "WinCity Native Battery Indicator"
oLink.Save
"#,
        shortcut = shortcut_str,
        target = target_str,
        args = args_str,
        working_dir = working_dir_str,
        icon = if icon_path.exists() { icon_str } else { "".into() }
    );

    let tmp_vbs = std::env::temp_dir().join(format!("wincity_sc_{}.vbs", std::process::id()));
    if std::fs::write(&tmp_vbs, vbs).is_ok() {
        let _ = std::process::Command::new("cscript")
            .arg("//nologo")
            .arg(&tmp_vbs)
            .creation_flags(0x08000000)
            .status();
        let _ = std::fs::remove_file(tmp_vbs);
        shortcut_path.exists()
    } else {
        false
    }
}
