#![allow(dead_code)]

use std::ffi::c_void;
use std::mem::size_of;
use std::sync::Mutex;
use std::time::Instant;
use sysinfo::{ProcessesToUpdate, System};
use windows::core::{GUID, PCWSTR};
use windows::Win32::Devices::DeviceAndDriverInstallation::{
    SetupDiDestroyDeviceInfoList, SetupDiEnumDeviceInterfaces, SetupDiGetClassDevsW,
    SetupDiGetDeviceInterfaceDetailW, DIGCF_DEVICEINTERFACE, DIGCF_PRESENT,
    SP_DEVICE_INTERFACE_DATA, SP_DEVICE_INTERFACE_DETAIL_DATA_W,
};
use windows::Win32::Foundation::{CloseHandle, GENERIC_READ, GENERIC_WRITE};
use windows::Win32::Storage::FileSystem::{CreateFileW, FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING};
use windows::Win32::System::IO::DeviceIoControl;
use windows::Win32::System::Power::{GetSystemPowerStatus, SYSTEM_POWER_STATUS};

#[derive(Debug, Clone, Default)]
pub struct BatteryInfo {
    pub percent: f64,
    pub power_plugged: bool,
    pub secsleft: Option<i64>,
}

#[derive(Debug, Clone, Default)]
pub struct BatteryHwInfo {
    pub rate_mw: Option<i32>,
    pub designed_mwh: Option<u32>,
    pub full_mwh: Option<u32>,
    pub cycle_count: Option<u32>,
    pub temp_c: Option<f64>,
}

#[derive(Debug, Clone)]
pub struct ProcessWattage {
    pub pid: u32,
    pub name: String,
    pub cpu: f32,
    pub mem_mb: f64,
    pub watts: f64,
    pub exe: String,
}

pub fn get_battery_basic() -> Option<BatteryInfo> {
    unsafe {
        let mut status = SYSTEM_POWER_STATUS::default();
        if GetSystemPowerStatus(&mut status).is_ok() {
            let percent = if status.BatteryLifePercent <= 100 {
                status.BatteryLifePercent as f64
            } else {
                100.0
            };
            let power_plugged = status.ACLineStatus == 1;
            let secsleft = if status.BatteryLifeTime != u32::MAX && status.BatteryLifeTime > 0 {
                Some(status.BatteryLifeTime as i64)
            } else {
                None
            };
            Some(BatteryInfo {
                percent,
                power_plugged,
                secsleft,
            })
        } else {
            None
        }
    }
}

pub fn format_time(secs: i64) -> Option<String> {
    if secs <= 0 || secs >= 99 * 3600 {
        return None;
    }
    let h = secs / 3600;
    let m = (secs % 3600) / 60;
    Some(format!("{}:{:02}", h, m))
}

pub fn format_time_long(secs: i64) -> Option<String> {
    if secs <= 0 || secs >= 99 * 3600 {
        return None;
    }
    let h = secs / 3600;
    let m = (secs % 3600) / 60;
    if h > 0 && m > 0 {
        Some(format!("{} Hour{} {} Minute{}", h, if h != 1 { "s" } else { "" }, m, if m != 1 { "s" } else { "" }))
    } else if h > 0 {
        Some(format!("{} Hour{}", h, if h != 1 { "s" } else { "" }))
    } else if m > 0 {
        Some(format!("{} Minute{}", m, if m != 1 { "s" } else { "" }))
    } else {
        None
    }
}

pub fn get_screen_on_seconds() -> Option<u64> {
    unsafe {
        let ms = windows::Win32::System::SystemInformation::GetTickCount64();
        if ms > 0 {
            Some(ms / 1000)
        } else {
            None
        }
    }
}

pub fn format_duration_short(secs: u64) -> String {
    let h = secs / 3600;
    let m = (secs % 3600) / 60;
    if h > 0 {
        format!("{}h {:02}m", h, m)
    } else {
        format!("{}m", m)
    }
}

pub fn fmt_rate(rate_mw: Option<i32>) -> String {
    match rate_mw {
        Some(mw) => {
            let sign = if mw > 0 { "+" } else { "-" };
            format!("{}{:.1} W", sign, mw.abs() as f64 / 1000.0)
        }
        None => "—".to_string(),
    }
}

pub fn fmt_health(designed_mwh: Option<u32>, full_mwh: Option<u32>) -> String {
    match (designed_mwh, full_mwh) {
        (Some(d), Some(f)) if d > 0 => {
            let pct = (f as f64 / d as f64) * 100.0;
            format!("{:.1}% ({:.0}Wh/{:.0}Wh)", pct, f as f64 / 1000.0, d as f64 / 1000.0)
        }
        _ => "—".to_string(),
    }
}

// Win32 IOCTL Battery Structures
const IOCTL_BATTERY_QUERY_TAG: u32 = 0x294040;
const IOCTL_BATTERY_QUERY_STATUS: u32 = 0x29404C;
const IOCTL_BATTERY_QUERY_INFORMATION: u32 = 0x294044;

#[repr(C)]
#[allow(non_snake_case)]
struct BATTERY_QUERY_INFORMATION {
    BatteryTag: u32,
    InformationLevel: u32,
    AtRate: i32,
}

#[repr(C)]
#[allow(non_snake_case)]
struct BATTERY_INFORMATION {
    Capabilities: u32,
    Technology: u8,
    Reserved: [u8; 3],
    Chemistry: [u8; 4],
    DesignedCapacity: u32,
    FullChargedCapacity: u32,
    DefaultAlert1: u32,
    DefaultAlert2: u32,
    CriticalBias: u32,
    CycleCount: u32,
}

#[repr(C)]
#[allow(non_snake_case)]
struct BATTERY_WAIT_STATUS {
    BatteryTag: u32,
    Timeout: u32,
    PowerState: u32,
    LowCapacity: u32,
    HighCapacity: u32,
}

#[repr(C)]
#[allow(non_snake_case)]
struct BATTERY_STATUS {
    PowerState: u32,
    Capacity: u32,
    Voltage: u32,
    Rate: i32,
}

pub struct HardwareCache {
    pub designed_mwh: Option<u32>,
    pub full_mwh: Option<u32>,
    pub cycle_count: Option<u32>,
    pub last_query: Instant,
}

static HW_CACHE: Mutex<Option<HardwareCache>> = Mutex::new(None);

pub fn query_battery_hw(include_temp: bool) -> BatteryHwInfo {
    let mut hw_info = BatteryHwInfo::default();

    // Check static cache
    {
        let cache_lock = HW_CACHE.lock().unwrap();
        if let Some(ref c) = *cache_lock {
            if c.last_query.elapsed().as_secs() < 300 {
                hw_info.designed_mwh = c.designed_mwh;
                hw_info.full_mwh = c.full_mwh;
                hw_info.cycle_count = c.cycle_count;
            }
        }
    }

    let guid = GUID::from_u128(0x72631E54_78A4_11D0_BCF7_00AA00B7B32A);

    unsafe {
        let hdev = SetupDiGetClassDevsW(
            Some(&guid),
            PCWSTR::null(),
            None,
            DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
        );

        if let Ok(hdev) = hdev {
            let mut idx = 0;
            loop {
                let mut iface_data = SP_DEVICE_INTERFACE_DATA {
                    cbSize: size_of::<SP_DEVICE_INTERFACE_DATA>() as u32,
                    ..Default::default()
                };

                if SetupDiEnumDeviceInterfaces(hdev, None, &guid, idx, &mut iface_data).is_err() {
                    break;
                }
                idx += 1;

                let mut detail_buf = [0u8; 1024];
                let detail = detail_buf.as_mut_ptr() as *mut SP_DEVICE_INTERFACE_DETAIL_DATA_W;
                (*detail).cbSize = if size_of::<usize>() == 8 { 8 } else { 6 };
                let mut req_size = 0u32;

                if SetupDiGetDeviceInterfaceDetailW(
                    hdev,
                    &iface_data,
                    Some(detail),
                    detail_buf.len() as u32,
                    Some(&mut req_size),
                    None,
                ).is_ok() {
                    let dev_path = PCWSTR::from_raw((*detail).DevicePath.as_ptr());
                    let hbat = CreateFileW(
                        dev_path,
                        (GENERIC_READ | GENERIC_WRITE).0,
                        FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None,
                        OPEN_EXISTING,
                        Default::default(),
                        None,
                    );

                    if let Ok(hbat) = hbat {
                        if !hbat.is_invalid() {
                            let mut tag: u32 = 0;
                            let timeout: u32 = 0;
                            let mut br = 0u32;

                            if DeviceIoControl(
                                hbat,
                                IOCTL_BATTERY_QUERY_TAG,
                                Some(&timeout as *const _ as *const c_void),
                                size_of::<u32>() as u32,
                                Some(&mut tag as *mut _ as *mut c_void),
                                size_of::<u32>() as u32,
                                Some(&mut br),
                                None,
                            ).is_ok() && tag != 0 {
                                let wait = BATTERY_WAIT_STATUS {
                                    BatteryTag: tag,
                                    Timeout: 0,
                                    PowerState: 0,
                                    LowCapacity: 0,
                                    HighCapacity: u32::MAX,
                                };
                                let mut bstatus = BATTERY_STATUS {
                                    PowerState: 0,
                                    Capacity: 0,
                                    Voltage: 0,
                                    Rate: 0,
                                };

                                if DeviceIoControl(
                                    hbat,
                                    IOCTL_BATTERY_QUERY_STATUS,
                                    Some(&wait as *const _ as *const c_void),
                                    size_of::<BATTERY_WAIT_STATUS>() as u32,
                                    Some(&mut bstatus as *mut _ as *mut c_void),
                                    size_of::<BATTERY_STATUS>() as u32,
                                    Some(&mut br),
                                    None,
                                ).is_ok() {
                                    if bstatus.Rate != -2147483648 && bstatus.Rate != 0 {
                                        hw_info.rate_mw = Some(bstatus.Rate);
                                    }
                                }

                                if hw_info.designed_mwh.is_none() {
                                    let qinfo = BATTERY_QUERY_INFORMATION {
                                        BatteryTag: tag,
                                        InformationLevel: 0,
                                        AtRate: 0,
                                    };
                                    let mut binfo: BATTERY_INFORMATION = std::mem::zeroed();

                                    if DeviceIoControl(
                                        hbat,
                                        IOCTL_BATTERY_QUERY_INFORMATION,
                                        Some(&qinfo as *const _ as *const c_void),
                                        size_of::<BATTERY_QUERY_INFORMATION>() as u32,
                                        Some(&mut binfo as *mut _ as *mut c_void),
                                        size_of::<BATTERY_INFORMATION>() as u32,
                                        Some(&mut br),
                                        None,
                                    ).is_ok() {
                                        if binfo.DesignedCapacity > 0 {
                                            hw_info.designed_mwh = Some(binfo.DesignedCapacity);
                                            hw_info.full_mwh = Some(binfo.FullChargedCapacity);
                                        }
                                        if binfo.CycleCount > 0 {
                                            hw_info.cycle_count = Some(binfo.CycleCount);
                                        }

                                        let mut cache_lock = HW_CACHE.lock().unwrap();
                                        *cache_lock = Some(HardwareCache {
                                            designed_mwh: hw_info.designed_mwh,
                                            full_mwh: hw_info.full_mwh,
                                            cycle_count: hw_info.cycle_count,
                                            last_query: Instant::now(),
                                        });
                                    }
                                }

                                if include_temp {
                                    let qtemp = BATTERY_QUERY_INFORMATION {
                                        BatteryTag: tag,
                                        InformationLevel: 2,
                                        AtRate: 0,
                                    };
                                    let mut raw_temp = 0u32;
                                    if DeviceIoControl(
                                        hbat,
                                        IOCTL_BATTERY_QUERY_INFORMATION,
                                        Some(&qtemp as *const _ as *const c_void),
                                        size_of::<BATTERY_QUERY_INFORMATION>() as u32,
                                        Some(&mut raw_temp as *mut _ as *mut c_void),
                                        size_of::<u32>() as u32,
                                        Some(&mut br),
                                        None,
                                    ).is_ok() && raw_temp > 0 {
                                        let temp_c = if raw_temp > 1000 {
                                            raw_temp as f64 / 10.0 - 273.15
                                        } else {
                                            raw_temp as f64 - 273.15
                                        };
                                        if (-20.0..=80.0).contains(&temp_c) {
                                            hw_info.temp_c = Some((temp_c * 10.0).round() / 10.0);
                                        }
                                    }
                                }
                            }
                            let _ = CloseHandle(hbat);
                            break;
                        }
                    }
                }
            }
            let _ = SetupDiDestroyDeviceInfoList(hdev);
        }
    }

    hw_info
}

pub struct ProcessTracker {
    sys: System,
}

impl ProcessTracker {
    pub fn new() -> Self {
        let mut sys = System::new();
        sys.refresh_processes(ProcessesToUpdate::All, true);
        Self { sys }
    }

    pub fn update(&mut self, total_watts: f64) -> Vec<ProcessWattage> {
        self.sys.refresh_processes(ProcessesToUpdate::All, true);

        let mut list: Vec<ProcessWattage> = Vec::new();
        let mut total_weight = 0.0f32;

        for (pid, proc) in self.sys.processes() {
            let name = proc.name().to_string_lossy().to_string();
            if pid.as_u32() == 0 || name.to_lowercase().contains("idle") {
                continue;
            }
            let cpu = proc.cpu_usage();
            let mem_mb = proc.memory() as f64 / (1024.0 * 1024.0);
            let exe = proc.exe().map(|p| p.to_string_lossy().to_string()).unwrap_or_default();

            let weight = cpu + (mem_mb as f32 / 1024.0) * 0.05 + 0.001;
            total_weight += weight;

            list.push(ProcessWattage {
                pid: pid.as_u32(),
                name,
                cpu,
                mem_mb,
                watts: 0.0,
                exe,
            });
        }

        if total_weight > 0.0 {
            for item in &mut list {
                let weight = item.cpu + (item.mem_mb as f32 / 1024.0) * 0.05 + 0.001;
                item.watts = (total_watts * (weight as f64 / total_weight as f64) * 100.0).round() / 100.0;
            }
        }

        list.sort_by(|a, b| b.watts.partial_cmp(&a.watts).unwrap_or(std::cmp::Ordering::Equal));
        list
    }
}
