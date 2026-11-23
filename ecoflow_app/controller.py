"""Glue object: owns client, history and rule engine; forwards signals to the UI."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from collections import deque
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, Signal

from . import importer, schedule, sync
from .api import POLL_FAST, POLL_SLOW, EcoflowClient, Telemetry
from .engine import RuleEngine
from .paths import DB_PATH, SETTINGS_PATH
from .power import state_of, state_since
from .settings import Settings, load_rules, load_settings, save_settings, set_github_token
from .storage import History

STALE_AFTER = 60  # seconds without telemetry -> treated as offline


class Controller(QObject):
    telemetry = Signal(object)
    online = Signal(bool)
    status = Signal(str)
    sync_done = Signal(object)      # SyncResult, emitted from the sync worker thread
    sync_status = Signal(str)       # final text of a sync round (Settings tab)
    schedule_done = Signal(object)  # ScheduleResult from the fetch thread
    schedule_status = Signal(str)   # text for the Settings tab; also tells the graphs to refresh
    sync_progress = Signal(str)     # phase text while a round is running: connecting / sending / reading

    def __init__(self):
        super().__init__()
        self.history = History(DB_PATH)
        self.settings: Settings = load_settings()
        if self.settings.complete and not SETTINGS_PATH.exists():
            save_settings(self.settings)  # migrate .env values so autostart works from anywhere
        self.engine = RuleEngine(None, load_rules())
        self.client: EcoflowClient | None = None
        self.last: Telemetry | None = None
        self.is_online = False
        self.window_active = False
        # power state (charging/discharging/full/ongrid) and when the current run started; seeded from history
        self.power_state, self.state_since_ts = state_since(self.history.range(time.time() - 3 * 86400))
        self.live: deque = deque(maxlen=8000)  # ~1 Hz samples, enough for the 1 hour graph
        self.status_text = "Not configured" if not self.settings.complete else "Starting..."
        # automatic, read-only sharing of power history with other installs (see sync.py)
        self.sync_result: sync.SyncResult | None = None
        self._sync_busy = False
        self.sync_done.connect(self._on_sync_done)
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self.sync_now)
        self._apply_sync_timer()
        QTimer.singleShot(8000, self.sync_now)
        # planned outages from the distribution company's public page, saved daily for expected-vs-real graphs
        self.schedule_result: schedule.ScheduleResult | None = None
        self._schedule_busy = False
        self.schedule_done.connect(self._on_schedule_done)
        self._schedule_timer = QTimer(self)
        self._schedule_timer.timeout.connect(lambda: self.fetch_schedule(manual=False))
        self._schedule_timer.start(schedule.FETCH_EVERY * 1000)
        QTimer.singleShot(20000, self.fetch_schedule)
        self._blocked_until = 0.0         # after a bot-protection answer the automatic fetch pauses
        self._import_server = importer.start(schedule.IMPORT_PORT, self.import_schedule)   # 'Send from browser'

    @property
    def fresh(self) -> bool:
        return bool(self.last and self.is_online and time.time() - self.last.ts < STALE_AFTER)

    def recent(self, since: float) -> list[tuple]:
        """Rows (ts, soc, in_w, out_w) since `since`: 1 Hz live buffer, older part from the 30 s history."""
        live = [r for r in self.live if r[0] >= since]
        if live and live[0][0] <= since + 2:
            return live
        cutoff = live[0][0] if live else time.time() + 1
        old = [(r[0], r[1], r[2], r[3]) for r in self.history.range(since, cutoff - 0.001, with_prev=True)]
        return old + live

    def start(self):
        if not self.settings.complete:
            return
        self._stop_client()
        c = EcoflowClient(self.settings.api_host, self.settings.email, self.settings.password, self.settings.sn)
        c.telemetry.connect(self._on_telemetry)
        c.online.connect(self._on_online)
        c.status.connect(self._on_status)
        self.client = c
        self.engine.client = c
        c.set_poll_interval(POLL_FAST if self.window_active else POLL_SLOW)
        c.start()

    def set_window_active(self, active: bool):
        """Window open and visible -> poll every 1 s, otherwise (tray) every 10 s."""
        self.window_active = active
        if self.client:
            self.client.set_poll_interval(POLL_FAST if active else POLL_SLOW)

    # ---- planned-outage schedule
    @property
    def schedule_configured(self) -> bool:
        st = self.settings
        return st.outage_region in schedule.REGIONS and st.outage_group in schedule.GROUPS

    def fetch_schedule(self, manual: bool = True):
        if not self.schedule_configured or self._schedule_busy:
            return
        if not manual and time.time() < self._blocked_until:
            return
        self._schedule_busy = True
        threading.Thread(target=self._schedule_worker, args=(self.settings.outage_region,), daemon=True,
                         name="ecoflow-schedule").start()

    def _schedule_worker(self, region: str):
        res = schedule.ScheduleResult(at=time.time())
        try:
            self._store_schedule(region, schedule.fetch(region), res)
        except schedule.Blocked as e:
            res.error = str(e)
            self._blocked_until = time.time() + 3600
        except (OSError, ValueError) as e:      # requests' errors are OSErrors too
            res.error = str(e)
        self.schedule_done.emit(res)

    def _store_schedule(self, region: str, data, res):
        self.history.schedule_put(region, data.days, data.update)
        res.update, res.days = data.update, len(data.days)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        res.has_today = any(today <= d < today + 86400 for d in data.days)
        res.has_tomorrow = any(today + 86400 <= d < today + 2 * 86400 for d in data.days)
        self._blocked_until = 0.0

    def import_schedule(self, text: str) -> str:
        """Schedule handed over from the user's browser (bookmarklet or clipboard). Runs on any thread; returns a reply."""
        region = self.settings.outage_region
        if region not in schedule.REGIONS:
            raise ValueError("Choose a region in Settings first.")
        res = schedule.ScheduleResult(at=time.time(), source="browser")
        self._store_schedule(region, schedule.parse_text(text), res)
        self._schedule_busy = False
        self.schedule_done.emit(res)
        return "Sent to EcoFlow Scheduler: " + res.text()

    def _on_schedule_done(self, res):
        self._schedule_busy = False
        self.schedule_result = res
        self.schedule_status.emit(res.text())

    def set_outage_schedule(self, region: str, group: str):
        self.settings = replace(self.settings, outage_region=region, outage_group=group)
        save_settings(self.settings)
        if self.schedule_configured:
            self.fetch_schedule()
        else:
            self.schedule_result = None
            self.schedule_status.emit("Schedule is off")

    def schedule_note(self, day_start: float, today_start: float) -> tuple[str, str]:
        """Why a day has no schedule: (short title, explanation). Tells 'never fetched / fetch failed' from
        'the company has not published it (yet)' and 'it was published while the app was not running'."""
        r = self.schedule_result
        saved = self.history.schedule_count(self.settings.outage_region) if self.settings.outage_region else 0
        if r is not None and r.error and saved == 0:
            return "Fetch failed", r.error
        if r is None and saved == 0:
            return "Not fetched yet", "The schedule has not been downloaded yet (it is checked every 10 minutes)."
        if day_start > today_start:
            if r is not None and r.error:
                return "Fetch failed", f"Could not check for tomorrow's schedule: {r.error}"
            return "Not published yet", "The distribution company has not published this day yet; it is picked up automatically."
        return "Not saved", "No schedule was saved for this day - the app was not running while it was published."

    def expected_segments(self, t0: float, t1: float):
        """Planned outages over [t0, t1] for the chosen region/group, or None when not configured."""
        if not self.schedule_configured:
            return None
        st = self.settings
        return schedule.build_segments(self.history.schedule_days(st.outage_region, st.outage_group, t0, t1), t0, t1)

    # ---- history sharing
    def sync_now(self):
        tr = sync.make_transport(self.settings)
        if tr is None or self._sync_busy:
            return
        self._sync_busy = True
        threading.Thread(target=self._sync_worker, args=(tr,), daemon=True, name="ecoflow-sync").start()

    def _sync_worker(self, tr):
        try:
            res = sync.sync_once(self.history, tr, progress=self.sync_progress.emit)
        except Exception as e:  # noqa: BLE001 - never let the worker die silently
            res = sync.SyncResult(at=time.time(), error=str(e))
        self.sync_done.emit(res)

    def _on_sync_done(self, res):
        self._sync_busy = False
        self.sync_result = res
        self.sync_status.emit(res.text())

    def _apply_sync_timer(self):
        tr = sync.make_transport(self.settings)
        self._sync_timer.start((tr.interval if tr else sync.FOLDER_EVERY) * 1000)

    def _store_sync(self, **changes):
        self.settings = replace(self.settings, **changes)
        save_settings(self.settings)
        self._apply_sync_timer()

    def set_sync_folder(self, path: str):
        """Share history through a folder; "" turns sync off."""
        if not path:
            return self.stop_sync()
        self._store_sync(sync_mode="folder", sync_dir=path)
        self.sync_now()

    set_sync_dir = set_sync_folder          # older name

    def set_sync_github(self, repo: str, token: str = ""):
        """Share history through a private GitHub repository. An empty token keeps the one already stored."""
        if token:
            set_github_token(token)          # OS credential store only
        self._store_sync(sync_mode="github", github_repo=repo.strip())
        if sync.make_transport(self.settings) is None:
            self.sync_status.emit("GitHub sync needs a repository (owner/name) and a token")
            return
        self.sync_now()

    def stop_sync(self):
        try:
            if self.settings.sync_mode == "github":
                set_github_token("")         # forget the token when syncing is switched off
        except OSError:
            pass
        self._store_sync(sync_mode="", sync_dir="")
        self.sync_result = None
        self.sync_status.emit("Sync is off")

    def apply_settings(self, s: Settings):
        for f in ("machine_id", "sync_mode", "sync_dir", "github_repo"):   # not part of the credentials form
            if not getattr(s, f):
                setattr(s, f, getattr(self.settings, f))
        save_settings(s)
        self.settings = s
        self.last = None
        self.start()

    def shutdown(self):
        self._stop_client()
        tr = sync.make_transport(self.settings)
        if tr is not None:              # hand over the latest samples before closing
            try:
                sync.export_new(self.history, tr)
            except Exception:  # noqa: BLE001
                pass

    def _stop_client(self):
        if self.client:
            self.client.stop()
            self.client = None
            self.engine.client = None

    def _on_telemetry(self, t: Telemetry):
        prev = self.power_state
        new = state_of(t.soc, t.in_w, t.out_w, t.grid, prev)
        if new != prev:
            self.power_state, self.state_since_ts = new, t.ts
        elif self.state_since_ts is None:
            self.state_since_ts = t.ts
        self.last = t
        self.is_online = True
        self.history.add(t)
        if not self.live or t.ts - self.live[-1][0] >= 1.0:
            self.live.append((t.ts, t.soc, t.in_w, t.out_w))
        self.engine.on_telemetry(t)
        self.telemetry.emit(t)

    def _on_online(self, ok: bool):
        self.is_online = ok
        self.online.emit(ok)

    def _on_status(self, text: str):
        self.status_text = text
        self.status.emit(text)
