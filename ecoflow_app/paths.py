import os
import sys
from pathlib import Path

APP_NAME = "EcoFlowScheduler"


def _data_dir() -> Path:
    """Per-user data folder: %APPDATA% (Windows), ~/Library/Application Support (macOS), ~/.config (Linux).
    ECOFLOW_DATA_DIR overrides it (tests, portable use)."""
    override = os.environ.get("ECOFLOW_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


APPDIR = _data_dir()
APPDIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APPDIR / "history.db"
SETTINGS_PATH = APPDIR / "settings.json"
RULES_PATH = APPDIR / "rules.json"
LOCK_PATH = APPDIR / "app.lock"
