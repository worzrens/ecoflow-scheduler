"""Start at login: Windows = HKCU\\...\\Run (no admin rights), macOS = a LaunchAgent in ~/Library/LaunchAgents."""
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

from .paths import APP_NAME

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LAUNCH_LABEL = "com.ecoflowscheduler.app"


def program_args() -> list[str]:
    """Command line that starts the app minimized to the tray."""
    if getattr(sys, "frozen", False):                      # PyInstaller exe / .app
        return [sys.executable, "--minimized"]
    exe = sys.executable
    if sys.platform == "win32":                            # no console window
        pyw = Path(exe).with_name("pythonw.exe")
        exe = str(pyw) if pyw.exists() else exe
    return [exe, str(Path(__file__).resolve().parent.parent / "main.py"), "--minimized"]


def command() -> str:
    """Windows Run-key value: paths quoted, flags not."""
    return " ".join(a if a.startswith("--") else f'"{a}"' for a in program_args())


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"


def launch_agent_plist(args: list[str]) -> bytes:
    return plistlib.dumps({"Label": LAUNCH_LABEL, "ProgramArguments": args, "RunAtLoad": True,
                           "ProcessType": "Interactive"})


def is_enabled() -> bool:
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, APP_NAME)
                return True
        except OSError:
            return False
    if sys.platform == "darwin":
        return launch_agent_path().exists()
    return False


def set_enabled(enabled: bool) -> None:
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, command())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
    elif sys.platform == "darwin":
        path = launch_agent_path()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(launch_agent_plist(program_args()))   # picked up at the next login
        else:
            path.unlink(missing_ok=True)
    else:
        raise OSError("Start at login is not supported on this platform")
