use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use windows::core::{w, PCWSTR};
use windows::Win32::Foundation::RECT;
use windows::Win32::UI::HiDpi::{
    GetDpiForSystem, SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows::Win32::UI::WindowsAndMessaging::{
    FindWindowW, GetClassNameW, GetForegroundWindow, GetSystemMetrics, GetWindowRect,
    IsWindowVisible, SM_CXSCREEN, SM_CYSCREEN,
};

// system.rs

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
                        // True fullscreen check: must cover the entire screen AND taskbar
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
    use windows::Win32::System::Registry::{RegGetValueW, HKEY_CURRENT_USER, RRF_RT_REG_DWORD};
    use std::ffi::c_void;

    let subkey = w!("Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize");

    unsafe {
        // 1. Check SystemUsesLightTheme (taskbar / system chrome)
        let mut data: u32 = 0;
        let mut data_size = std::mem::size_of::<u32>() as u32;
        let res = RegGetValueW(
            HKEY_CURRENT_USER,
            subkey,
            w!("SystemUsesLightTheme"),
            RRF_RT_REG_DWORD,
            None,
            Some(&mut data as *mut u32 as *mut c_void),
            Some(&mut data_size),
        );
        if res.is_ok() {
            return data == 0;
        }

        // 2. Fallback to AppsUseLightTheme
        let mut data_app: u32 = 0;
        let mut data_app_size = std::mem::size_of::<u32>() as u32;
        let res_app = RegGetValueW(
            HKEY_CURRENT_USER,
            subkey,
            w!("AppsUseLightTheme"),
            RRF_RT_REG_DWORD,
            None,
            Some(&mut data_app as *mut u32 as *mut c_void),
            Some(&mut data_app_size),
        );
        if res_app.is_ok() {
            return data_app == 0;
        }
    }
    true // default dark
}

type PowerGetEffectiveOverlaySchemeFn = unsafe extern "system" fn(*mut windows::core::GUID) -> windows::Win32::Foundation::WIN32_ERROR;

pub fn get_power_mode() -> String {
    unsafe {
        // 1. Windows 10/11 Power Overlay Scheme via powrprof.dll
        let mod_name: Vec<u16> = "powrprof.dll\0".encode_utf16().collect();
        let hmod = windows::Win32::System::LibraryLoader::LoadLibraryW(windows::core::PCWSTR::from_raw(mod_name.as_ptr()));
        if let Ok(hmod) = hmod {
            if !hmod.is_invalid() {
                let proc_name = std::ffi::CString::new("PowerGetEffectiveOverlayScheme").unwrap();
                let proc = windows::Win32::System::LibraryLoader::GetProcAddress(hmod, windows::core::PCSTR(proc_name.as_ptr() as _));
                if let Some(proc) = proc {
                    let func: PowerGetEffectiveOverlaySchemeFn = std::mem::transmute(proc);
                    let mut scheme = windows::core::GUID::zeroed();
                    if func(&mut scheme).0 == 0 {
                        let guid_saver1 = windows::core::GUID::from_u128(0x961cc777_2547_4f9d_8174_7d86181b8a7a);
                        let guid_saver2 = windows::core::GUID::from_u128(0x3a5574dc_007b_40e3_9464_7c590d7324e0);
                        let guid_perf = windows::core::GUID::from_u128(0xded574b5_45a0_4f42_8734_20b1de8d37b3);

                        if scheme == guid_saver1 || scheme == guid_saver2 {
                            return "Energy Saver".to_string();
                        } else if scheme == guid_perf {
                            return "Best Performance".to_string();
                        }
                    }
                }
            }
        }

        // 2. Legacy Battery Saver flag
        let mut sps = windows::Win32::System::Power::SYSTEM_POWER_STATUS::default();
        if windows::Win32::System::Power::GetSystemPowerStatus(&mut sps).is_ok() {
            if sps.SystemStatusFlag == 1 {
                return "Energy Saver".to_string();
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
