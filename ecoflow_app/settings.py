"""Settings: non-secret values in settings.json, password in Windows Credential Manager.
Falls back to EF_* variables from a local .env for development."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass

from dotenv import load_dotenv

from .paths import APP_NAME, RULES_PATH, SETTINGS_PATH
from .rules import RulesConfig

try:
    import keyring
except Exception:  # pragma: no cover
    keyring = None


@dataclass
class Settings:
    email: str = ""
    sn: str = ""
    api_host: str = "api-e.ecoflow.com"
    password: str = ""
    sync_mode: str = ""     # "" = off, "folder" = shared folder, "github" = private GitHub repository
    sync_dir: str = ""      # shared folder (OneDrive, Dropbox, Syncthing, NAS...) for sharing power history
    github_repo: str = ""   # owner/name of the PRIVATE repository (the token lives in the OS credential store)
    machine_id: str = ""    # identifies this install in the shared folder
    outage_region: str = ""  # planned-outage schedule source (see schedule.py), "" = off
    outage_group: str = ""   # queue / group number, e.g. "4.1"

    @property
    def complete(self) -> bool:
        return bool(self.email and self.password and self.sn)


def load_settings() -> Settings:
    s = Settings()
    from_file = False
    try:
        d = json.loads(SETTINGS_PATH.read_text("utf-8"))
        s.email, s.sn, s.api_host = d.get("email", ""), d.get("sn", ""), d.get("api_host", s.api_host)
        s.sync_dir, s.machine_id = d.get("sync_dir", ""), d.get("machine_id", "")
        s.sync_mode, s.github_repo = d.get("sync_mode", ""), d.get("github_repo", "")
        s.outage_region, s.outage_group = d.get("outage_region", ""), d.get("outage_group", "")
        if not s.sync_mode and s.sync_dir:      # settings written before GitHub sync existed
            s.sync_mode = "folder"
        from_file = True
    except (OSError, ValueError):
        pass
    if not s.machine_id:
        s.machine_id = uuid.uuid4().hex[:12]
        if from_file:       # keep it stable across runs
            try:
                d["machine_id"] = s.machine_id
                SETTINGS_PATH.write_text(json.dumps(d, indent=2), "utf-8")
            except OSError:
                pass
    if s.email and keyring:
        try:
            s.password = keyring.get_password(APP_NAME, s.email) or ""
        except Exception:
            pass
    if not s.complete:  # development fallback: .env in the working directory
        load_dotenv()
        s.email = s.email or os.environ.get("EF_EMAIL", "")
        s.password = s.password or os.environ.get("EF_PASSWORD", "")
        s.sn = s.sn or os.environ.get("EF_SN", "")
        if not from_file:
            s.api_host = os.environ.get("EF_API_HOST", s.api_host)
    return s


def save_settings(s: Settings) -> None:
    d = asdict(s)
    d.pop("password")
    SETTINGS_PATH.write_text(json.dumps(d, indent=2), "utf-8")
    if keyring and s.email and s.password:
        keyring.set_password(APP_NAME, s.email, s.password)


def load_rules() -> RulesConfig:
    try:
        return RulesConfig.from_dict(json.loads(RULES_PATH.read_text("utf-8")))
    except (OSError, ValueError, TypeError):
        # First run: do not touch the device until the user saves rules in the Control tab
        return RulesConfig(automation_enabled=False)


def save_rules(r: RulesConfig) -> None:
    RULES_PATH.write_text(json.dumps(r.to_dict(), indent=2), "utf-8")


GITHUB_TOKEN_USER = "github-sync-token"


def get_github_token() -> str:
    """Fine-grained GitHub token for history sync - kept only in the OS credential store, never in a file."""
    if not keyring:
        return ""
    try:
        return keyring.get_password(APP_NAME, GITHUB_TOKEN_USER) or ""
    except Exception:
        return ""


def set_github_token(token: str) -> None:
    if not keyring:
        raise OSError("No credential store available to keep the GitHub token safely")
    if token:
        keyring.set_password(APP_NAME, GITHUB_TOKEN_USER, token)
    else:
        try:
            keyring.delete_password(APP_NAME, GITHUB_TOKEN_USER)
        except Exception:
            pass
