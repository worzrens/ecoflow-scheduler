import os
import plistlib
import subprocess
import sys

from ecoflow_app import autostart


def test_launch_agent_plist_is_valid_and_runs_at_login():
    data = plistlib.loads(autostart.launch_agent_plist(["/Apps/EcoFlowScheduler", "--minimized"]))
    assert data["Label"] == autostart.LAUNCH_LABEL
    assert data["ProgramArguments"] == ["/Apps/EcoFlowScheduler", "--minimized"]
    assert data["RunAtLoad"] is True


def test_windows_run_value_quotes_paths_not_flags(monkeypatch):
    monkeypatch.setattr(autostart, "program_args", lambda: [r"C:\Program Files\x\app.exe", "--minimized"])
    assert autostart.command() == r'"C:\Program Files\x\app.exe" --minimized'


def test_data_dir_override_and_platform_default(tmp_path):
    code = "from ecoflow_app import paths; print(paths.APPDIR)"
    env = {**os.environ, "ECOFLOW_DATA_DIR": str(tmp_path / "custom")}
    out = subprocess.check_output([sys.executable, "-c", code], env=env, text=True, cwd=os.getcwd()).strip()
    assert out == str(tmp_path / "custom")
    env.pop("ECOFLOW_DATA_DIR")
    env["APPDATA"] = str(tmp_path / "appdata")
    out = subprocess.check_output([sys.executable, "-c", code], env=env, text=True, cwd=os.getcwd()).strip()
    if sys.platform == "win32":
        assert out == str(tmp_path / "appdata" / "EcoFlowScheduler")
    else:
        assert out.endswith("EcoFlowScheduler")
