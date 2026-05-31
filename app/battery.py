"""
Battery data queries (psutil + Win32 IOCTL) and display formatters.
Also provides ProcessTracker for per-process wattage attribution.
"""
import ctypes
import ctypes.wintypes
import json
import subprocess
import time
import threading

import psutil


# ── Basic battery queries ────────────────────────────────────────────────────

def get_battery():
    try:
        return psutil.sensors_battery()
    except Exception:
        return None


def format_time(secs):
    """Return 'H:MM' string, or None if unknown / unlimited / implausible."""
    if secs is None or secs <= 0:
        return None
    if secs in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED, -1, -2):
        return None
    if secs >= 99 * 3600:
        return None
    return f"{int(secs // 3600)}:{int((secs % 3600) // 60):02d}"


def format_time_long(secs):
    """Return 'x Hours xx Minutes' (or partial), or None."""
    if secs is None or secs <= 0:
        return None
    if secs in (psutil.POWER_TIME_UNKNOWN, psutil.POWER_TIME_UNLIMITED, -1, -2):
        return None
    if secs >= 99 * 3600:
        return None
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    if h > 0 and m > 0:
        return f"{h} Hour{'s' if h != 1 else ''} {m} Minute{'s' if m != 1 else ''}"
    if h > 0:
        return f"{h} Hour{'s' if h != 1 else ''}"
    return f"{m} Minute{'s' if m != 1 else ''}" if m > 0 else None


def fmt_hm(dt):
    """Format datetime as '1:30 PM' (no leading zero)."""
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def fmt_rate(mw):
    """Format mW rate as '+3.8 W', '-5.2 W', or '—'."""
    if mw is None:
        return "\u2014"
    sign = "+" if mw > 0 else "-"
    return f"{sign}{abs(mw) / 1000:.1f} W"


def fmt_health(designed_mwh, full_mwh):
    """Format battery health as 'xx.x% (xxWh/xxWh)'."""
    if designed_mwh is None or full_mwh is None or designed_mwh <= 0:
        return "\u2014"
    pct = full_mwh / designed_mwh * 100
    return f"{pct:.1f}% ({full_mwh/1000:.0f}Wh/{designed_mwh/1000:.0f}Wh)"


# ── Hardware IOCTL query ──────────────────────────────────────────────────────

def query_battery_hw():
    """Query battery via Win32 IOCTL. Returns (rate_mw, designed_mwh, full_mwh, cycle_count, temp_c)."""
    rate_mw = designed_mwh = full_mwh = cycle_count = temp_c = None
    try:
        class _GUID(ctypes.Structure):
            _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort),
                        ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]

        class _SP_IFACE_DATA(ctypes.Structure):
            _fields_ = [('cbSize', ctypes.wintypes.DWORD), ('InterfaceClassGuid', _GUID),
                        ('Flags', ctypes.wintypes.DWORD), ('Reserved', ctypes.c_size_t)]

        class _SP_IFACE_DETAIL(ctypes.Structure):
            _fields_ = [('cbSize', ctypes.wintypes.DWORD), ('DevicePath', ctypes.c_wchar * 512)]

        class _BAT_WAIT(ctypes.Structure):
            _fields_ = [('BatteryTag', ctypes.c_ulong), ('Timeout', ctypes.c_ulong),
                        ('PowerState', ctypes.c_ulong), ('LowCapacity', ctypes.c_ulong),
                        ('HighCapacity', ctypes.c_ulong)]

        class _BAT_STATUS(ctypes.Structure):
            _fields_ = [('PowerState', ctypes.c_ulong), ('Capacity', ctypes.c_ulong),
                        ('Voltage', ctypes.c_ulong), ('Rate', ctypes.c_long)]

        class _BAT_QUERY_INFO(ctypes.Structure):
            _fields_ = [('BatteryTag', ctypes.c_ulong), ('InformationLevel', ctypes.c_ulong),
                        ('AtRate', ctypes.c_long)]

        class _BAT_INFO(ctypes.Structure):
            _fields_ = [('Capabilities', ctypes.c_ulong), ('Technology', ctypes.c_ubyte),
                        ('Reserved', ctypes.c_ubyte * 3), ('Chemistry', ctypes.c_ubyte * 4),
                        ('DesignedCapacity', ctypes.c_ulong), ('FullChargedCapacity', ctypes.c_ulong),
                        ('DefaultAlert1', ctypes.c_ulong), ('DefaultAlert2', ctypes.c_ulong),
                        ('ReservedCapacity', ctypes.c_ulong), ('CycleCount', ctypes.c_ulong)]

        sa  = ctypes.windll.setupapi
        k32 = ctypes.windll.kernel32
        sa.SetupDiGetClassDevsW.restype = ctypes.c_void_p
        k32.CreateFileW.restype         = ctypes.c_void_p

        _ptr_w         = ctypes.sizeof(ctypes.c_void_p) * 8
        INVALID_HANDLE = (1 << _ptr_w) - 1

        guid = _GUID(0x72631E54, 0x78A4, 0x11D0,
                     (ctypes.c_ubyte * 8)(0xBC, 0xF7, 0x00, 0xAA, 0x00, 0xB7, 0xB3, 0x2A))

        DIGCF_PRESENT = 0x02; DIGCF_DEVICEINTERFACE = 0x10
        GENERIC_READ  = 0x80000000; GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x01; FILE_SHARE_WRITE = 0x02; OPEN_EXISTING = 3
        IOCTL_BATTERY_QUERY_TAG         = 0x294040
        IOCTL_BATTERY_QUERY_STATUS      = 0x29404C
        IOCTL_BATTERY_QUERY_INFORMATION = 0x294044
        BATTERY_UNKNOWN_RATE            = -2147483648

        hdev = sa.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                       DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
        if hdev is None or hdev == INVALID_HANDLE:
            return rate_mw, designed_mwh, full_mwh, cycle_count, temp_c

        hdev_p = ctypes.c_void_p(hdev)
        try:
            idx = 0
            while True:
                iface = _SP_IFACE_DATA(); iface.cbSize = ctypes.sizeof(iface)
                if not sa.SetupDiEnumDeviceInterfaces(hdev_p, None, ctypes.byref(guid),
                                                      idx, ctypes.byref(iface)):
                    break
                idx += 1
                detail = _SP_IFACE_DETAIL()
                detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                req = ctypes.wintypes.DWORD()
                sa.SetupDiGetDeviceInterfaceDetailW(hdev_p, ctypes.byref(iface),
                    ctypes.byref(detail), ctypes.sizeof(detail), ctypes.byref(req), None)
                hbat = k32.CreateFileW(detail.DevicePath, GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
                if hbat is None or hbat == INVALID_HANDLE:
                    continue
                hbat_p = ctypes.c_void_p(hbat)
                try:
                    tag = ctypes.c_ulong(0); timeout_in = ctypes.c_ulong(0)
                    br  = ctypes.wintypes.DWORD()
                    if not k32.DeviceIoControl(hbat_p, IOCTL_BATTERY_QUERY_TAG,
                            ctypes.byref(timeout_in), ctypes.sizeof(timeout_in),
                            ctypes.byref(tag), ctypes.sizeof(tag), ctypes.byref(br), None):
                        continue
                    if tag.value == 0:
                        continue

                    wait   = _BAT_WAIT(BatteryTag=tag.value, Timeout=0, PowerState=0,
                                       LowCapacity=0, HighCapacity=0xFFFFFFFF)
                    status = _BAT_STATUS()
                    if k32.DeviceIoControl(hbat_p, IOCTL_BATTERY_QUERY_STATUS,
                            ctypes.byref(wait), ctypes.sizeof(wait),
                            ctypes.byref(status), ctypes.sizeof(status), ctypes.byref(br), None):
                        if status.Rate != BATTERY_UNKNOWN_RATE:
                            rate_mw = status.Rate

                    qinfo = _BAT_QUERY_INFO(BatteryTag=tag.value, InformationLevel=0, AtRate=0)
                    binfo = _BAT_INFO()
                    if k32.DeviceIoControl(hbat_p, IOCTL_BATTERY_QUERY_INFORMATION,
                            ctypes.byref(qinfo), ctypes.sizeof(qinfo),
                            ctypes.byref(binfo), ctypes.sizeof(binfo), ctypes.byref(br), None):
                        if binfo.DesignedCapacity > 0:
                            designed_mwh = int(binfo.DesignedCapacity)
                            full_mwh     = int(binfo.FullChargedCapacity)
                        if binfo.CycleCount > 0:          # CycleCount is the correct field
                            cycle_count  = int(binfo.CycleCount)

                    qtemp = _BAT_QUERY_INFO(BatteryTag=tag.value, InformationLevel=2, AtRate=0)
                    t_raw = ctypes.c_ulong(0)
                    if k32.DeviceIoControl(hbat_p, IOCTL_BATTERY_QUERY_INFORMATION,
                            ctypes.byref(qtemp), ctypes.sizeof(qtemp),
                            ctypes.byref(t_raw), ctypes.sizeof(t_raw),
                            ctypes.byref(br), None) and t_raw.value > 0:
                        v   = t_raw.value
                        t_c = (v / 10.0 - 273.15) if v > 1000 else (v - 273.15)
                        if -20.0 <= t_c <= 80.0:
                            temp_c = round(t_c, 1)
                    break
                finally:
                    k32.CloseHandle(hbat_p)
        finally:
            sa.SetupDiDestroyDeviceInfoList(hdev_p)
    except Exception:
        pass
    if temp_c is None:
        temp_c = _query_temp_wmi()
    return rate_mw, designed_mwh, full_mwh, cycle_count, temp_c


_wmi_temp_cache: dict = {"val": None, "ts": -999.0}


def _query_temp_wmi():
    """Read ACPI thermal zone temperature via WMI PowerShell (cached 60 s)."""
    now = time.monotonic()
    if now - _wmi_temp_cache["ts"] < 60.0:
        return _wmi_temp_cache["val"]
    val = None
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-CimInstance -Namespace root/wmi "
             "-ClassName MSAcpi_ThermalZoneTemperature "
             "-ErrorAction SilentlyContinue | "
             "Select-Object -First 1).CurrentTemperature"],
            capture_output=True, text=True, timeout=5, creationflags=0x08000000)
        raw = r.stdout.strip()
        if raw and raw.lstrip("-").isdigit():
            t_c = round(int(raw) / 10.0 - 273.15, 1)
            if -20.0 <= t_c <= 100.0:
                val = t_c
    except Exception:
        pass
    _wmi_temp_cache["val"] = val
    _wmi_temp_cache["ts"]  = now
    return val


# ── Per-process wattage tracking ─────────────────────────────────────────────

class ProcessTracker:
    """
    Tracks per-process CPU/RAM footprints and attributes wattage proportionally
    to the total system discharge rate (from IOCTL or WMI fallback).

    Usage:
        tracker = ProcessTracker()
        # Call update() periodically (e.g. every 2 s):
        result = tracker.update(total_watts)
        # result is a list of dicts: [{"name", "pid", "cpu", "mem_mb", "watts"}, ...]
    """

    def __init__(self):
        self._cache: dict[int, psutil.Process] = {}
        self._lock  = threading.Lock()
        # Pre-seed the cpu_percent baselines (first call returns 0.0)
        try:
            for proc in psutil.process_iter(attrs=["pid"]):
                try:
                    pid = proc.info["pid"]
                    p_obj = psutil.Process(pid)
                    p_obj.cpu_percent(interval=None)
                    self._cache[pid] = p_obj
                except Exception:
                    pass
        except Exception:
            pass

    def update(self, total_watts: float) -> list:
        """
        Compute per-process wattage.
        total_watts should be the measured (or estimated) system discharge rate in Watts.
        Returns a list sorted by watts descending.
        """
        with self._lock:
            processes = []
            current_pids: set[int] = set()

            try:
                for proc in psutil.process_iter(attrs=["pid", "name", "memory_info", "exe"]):
                    try:
                        info = proc.info
                        pid  = info["pid"]
                        name = info["name"] or ""
                        if pid == 0 or name.lower() in ("system idle process", "idle"):
                            continue
                        current_pids.add(pid)
                        if pid not in self._cache:
                            p_obj = psutil.Process(pid)
                            p_obj.cpu_percent(interval=None)  # register baseline
                            self._cache[pid] = p_obj
                        cpu = self._cache[pid].cpu_percent(interval=None)
                        mem_info = info["memory_info"]
                        mem_mb = mem_info.rss / (1024 * 1024) if mem_info else 0.0
                        exe_path = info["exe"] or ""
                        processes.append({"pid": pid, "name": name,
                                          "cpu": cpu, "mem_mb": mem_mb, "exe": exe_path})
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass
            except Exception:
                pass

            # Prune stale pids
            self._cache = {p: v for p, v in self._cache.items() if p in current_pids}

            if not processes:
                return []

            # Hybrid weight: CPU dominates, memory provides minor background load
            total_weight = 0.0
            for proc in processes:
                proc["weight"] = proc["cpu"] + (proc["mem_mb"] / 1024.0) * 0.05 + 0.001
                total_weight += proc["weight"]

            for proc in processes:
                share = proc["weight"] / total_weight if total_weight > 0 else 0.0
                proc["watts"] = total_watts * share

            processes.sort(key=lambda x: x["watts"], reverse=True)
            return processes


def get_screen_on_seconds() -> int | None:
    """
    Return system uptime in seconds as a proxy for screen-on time.
    Uses GetTickCount64 (ms since last boot).
    """
    try:
        return int(ctypes.windll.kernel32.GetTickCount64() / 1000)
    except Exception:
        return None


def get_total_watts(rate_mw=None) -> float:
    """
    Best-effort system power draw in Watts.
    Prefers the IOCTL rate_mw; falls back to a WMI/CPU-based estimate.
    """
    if rate_mw is not None:
        w = abs(rate_mw) / 1000.0
        if w > 0.1:
            return w

    # WMI fallback (from battery_tracker approach)
    try:
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               "Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus | "
               "Select-Object -Property DischargeRate, Discharging, Voltage | ConvertTo-Json"]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=2, creationflags=0x08000000)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list):
                data = data[0] if data else {}
            discharge_rate = data.get("DischargeRate", 0)
            if data.get("Discharging") and discharge_rate > 0:
                return discharge_rate / 1000.0
    except Exception:
        pass

    # Dynamic CPU-based fallback
    try:
        cpu = psutil.cpu_percent(interval=None)
    except Exception:
        cpu = 30.0
    return round(12.5 + cpu * 0.18, 2)


def kill_process(pid: int) -> bool:
    """Attempt to terminate a process by PID. Returns True on success."""
    try:
        proc = psutil.Process(pid)
        proc.kill()
        return True
    except Exception:
        return False
