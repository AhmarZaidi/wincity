"""
Startup and shortcut management for WinCity.
Provides utilities to create Windows shortcuts (.lnk) with custom icons
and manage Windows Startup (shell:startup) auto-start without relying on .exe files.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

from . import config


def get_pythonw_path() -> str:
    """
    Locate pythonw.exe to run WinCity silently without a console window.
    Searches next to sys.executable, pyenv, standard python directories, or PATH.
    """
    # 1. Next to currently running Python executable
    py_dir = pathlib.Path(sys.executable).parent
    pw = py_dir / "pythonw.exe"
    if pw.exists():
        return str(pw.resolve())

    if "pythonw.exe" in sys.executable.lower() and os.path.exists(sys.executable):
        return str(pathlib.Path(sys.executable).resolve())

    # 2. Check PATH
    which_pw = shutil.which("pythonw.exe") or shutil.which("pythonw")
    if which_pw:
        return str(pathlib.Path(which_pw).resolve())

    # 3. Check PyEnv versions
    user_home = pathlib.Path.home()
    pyenv_dir = user_home / ".pyenv" / "pyenv-win" / "versions"
    if pyenv_dir.exists():
        for ver_dir in sorted(pyenv_dir.glob("*"), reverse=True):
            cand = ver_dir / "pythonw.exe"
            if cand.exists():
                return str(cand.resolve())

    # 4. Check AppData Local Programs Python
    local_py = user_home / "AppData" / "Local" / "Programs" / "Python"
    if local_py.exists():
        for ver_dir in sorted(local_py.glob("Python*"), reverse=True):
            cand = ver_dir / "pythonw.exe"
            if cand.exists():
                return str(cand.resolve())

    # Fallback to pythonw in PATH
    return "pythonw.exe"


def create_shortcut(
    target: str,
    shortcut_path: str | pathlib.Path,
    args: str = "",
    working_dir: str = "",
    icon_path: str = "",
    description: str = "",
) -> bool:
    """
    Create a Windows .lnk shortcut using WScript.Shell via VBScript.
    """
    shortcut_path = pathlib.Path(shortcut_path).resolve()
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)

    def vbs_quote(s):
        return '"' + str(s).replace('"', '""') + '"'

    vbs_content = f'''Set oWS = CreateObject("WScript.Shell")
Set oLink = oWS.CreateShortcut({vbs_quote(str(shortcut_path))})
oLink.TargetPath = {vbs_quote(target)}
oLink.Arguments = {vbs_quote(args)}
oLink.WorkingDirectory = {vbs_quote(working_dir)}
if {vbs_quote(icon_path)} <> "" Then oLink.IconLocation = {vbs_quote(icon_path)}
if {vbs_quote(description)} <> "" Then oLink.Description = {vbs_quote(description)}
oLink.Save
'''
    with tempfile.NamedTemporaryFile("w", suffix=".vbs", delete=False) as f:
        f.write(vbs_content)
        vbs_file = f.name

    try:
        res = subprocess.run(
            ["cscript", "//nologo", vbs_file],
            capture_output=True,
            text=True,
            creationflags=0x08000000,
        )
        return res.returncode == 0 and shortcut_path.exists()
    except Exception:
        return False
    finally:
        try:
            os.remove(vbs_file)
        except Exception:
            pass


def get_startup_dir() -> pathlib.Path:
    """Return the Windows user Startup folder path."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return pathlib.Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return pathlib.Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def get_startup_shortcut_path() -> pathlib.Path:
    """Return the path to the WinCity shortcut in the Windows Startup directory."""
    return get_startup_dir() / "WinCity.lnk"


def is_autostart_enabled() -> bool:
    """Return True if WinCity is configured to run at Windows startup."""
    return get_startup_shortcut_path().exists()


def _find_main_py() -> pathlib.Path:
    base_dir = config._BASE_DIR.resolve()
    cand1 = base_dir / "python" / "main.py"
    if cand1.exists():
        return cand1
    cand2 = base_dir / "main.py"
    if cand2.exists():
        return cand2
    return cand1


def get_target_command(variant: str = "auto") -> tuple[str, str]:
    """
    Get (target_path, arguments) for launching WinCity.
    variant can be 'rust', 'python', or 'auto' (prefers rust if built).
    """
    base_dir = config._BASE_DIR.resolve()
    rust_exe = base_dir / "rust" / "target" / "release" / "wincity.exe"

    if variant == "rust" or (variant == "auto" and rust_exe.exists()):
        if rust_exe.exists():
            return str(rust_exe), ""

    main_py = _find_main_py().resolve()
    pythonw = get_pythonw_path()
    return pythonw, f'"{main_py}"'


def set_autostart(enable: bool, variant: str = "auto") -> bool:
    """
    Enable or disable auto-starting WinCity at Windows login.
    Creates or removes WinCity.lnk in shell:startup.
    """
    lnk = get_startup_shortcut_path()
    if enable:
        base_dir = config._BASE_DIR.resolve()
        icon = (base_dir / "assets" / "appicon.ico").resolve()
        target, args = get_target_command(variant)
        return create_shortcut(
            target=target,
            shortcut_path=lnk,
            args=args,
            working_dir=str(base_dir),
            icon_path=f"{icon},0" if icon.exists() else "",
            description="WinCity Taskbar Battery Indicator",
        )
    else:
        try:
            if lnk.exists():
                lnk.unlink()
            return True
        except Exception:
            return False


def create_project_shortcut(variant: str = "auto") -> pathlib.Path | None:
    """Create WinCity.lnk in the root project directory with the app icon."""
    base_dir = config._BASE_DIR.resolve()
    icon = (base_dir / "assets" / "appicon.ico").resolve()
    lnk = base_dir / "WinCity.lnk"
    target, args = get_target_command(variant)

    ok = create_shortcut(
        target=target,
        shortcut_path=lnk,
        args=args,
        working_dir=str(base_dir),
        icon_path=f"{icon},0" if icon.exists() else "",
        description="WinCity Taskbar Battery Indicator",
    )
    return lnk if ok else None


def create_desktop_shortcut(variant: str = "auto") -> pathlib.Path | None:
    """Create WinCity.lnk on the user's Desktop with the app icon."""
    user_home = pathlib.Path.home()
    desktop = user_home / "Desktop"
    if not desktop.exists():
        return None

    base_dir = config._BASE_DIR.resolve()
    icon = (base_dir / "assets" / "appicon.ico").resolve()
    lnk = desktop / "WinCity.lnk"
    target, args = get_target_command(variant)

    ok = create_shortcut(
        target=target,
        shortcut_path=lnk,
        args=args,
        working_dir=str(base_dir),
        icon_path=f"{icon},0" if icon.exists() else "",
        description="WinCity Taskbar Battery Indicator",
    )
    return lnk if ok else None

