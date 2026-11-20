import os
from pathlib import Path

APP_NAME = "EcoFlowScheduler"
APPDIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
APPDIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APPDIR / "history.db"
SETTINGS_PATH = APPDIR / "settings.json"
RULES_PATH = APPDIR / "rules.json"
LOCK_PATH = APPDIR / "app.lock"
