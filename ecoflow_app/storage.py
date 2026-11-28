"""Local SQLite history (kept ~8 days) so graphs work offline."""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta

from .power import drop_stale_samples

KEEP_SECONDS = 8 * 86400
STALE_CONTEXT = 6 * 3600  # extra history read before a range so a replayed sample can be compared with what came before
MIN_INTERVAL = 30  # seconds between stored samples
MARKS_KEEP = 15 * 86400  # manual marks outlive the history they annotate

# Row layout returned by range(): (ts, soc, in_w, out_w, ac_in, ac_out, limit_w, temp, grid, src)
# src is NULL for samples recorded by this install, otherwise the id of the other device that shared them.
GRID_IDX = 8
SRC_IDX = 9


class History:
    def __init__(self, path):
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS samples (ts INTEGER PRIMARY KEY, soc REAL, in_w REAL, "
            "out_w REAL, ac_in REAL, ac_out REAL, limit_w INTEGER, temp REAL)"
        )
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(samples)")}
        if "src" not in cols:  # sync: which install recorded the row (NULL = this one)
            self._db.execute("ALTER TABLE samples ADD COLUMN src TEXT")
        self._db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self._db.execute("CREATE TABLE IF NOT EXISTS schedule (region TEXT, day INTEGER, grp TEXT, hours TEXT, "
                         "updated TEXT, PRIMARY KEY (region, day, grp))")
        # manual marks of stretches without data (see power.resolve_marks); own = made on this install
        self._db.execute("CREATE TABLE IF NOT EXISTS marks (start INTEGER, end INTEGER, kind TEXT, at REAL, by TEXT, "
                         "own INTEGER, PRIMARY KEY (at, by, start))")
        if "grid" not in cols:  # added with the power-outage feature: 1 mains present, 0 absent, NULL unknown (old rows)
            self._db.execute("ALTER TABLE samples ADD COLUMN grid INTEGER")
        # drop samples built from partial state by an earlier version (limit is never 0 on a real reading)
        self._db.execute("DELETE FROM samples WHERE limit_w IS NULL OR limit_w = 0")
        self._db.commit()
        self._last_ts = self._scalar("SELECT MAX(ts) FROM samples WHERE src IS NULL") or 0
        self.prune()

    def _scalar(self, sql, *a):
        with self._lock:
            r = self._db.execute(sql, a).fetchone()
        return r[0] if r else None

    def add(self, t, ts: float | None = None) -> bool:
        ts = int(ts or time.time())
        if ts - self._last_ts < MIN_INTERVAL:
            return False
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO samples (ts, soc, in_w, out_w, ac_in, ac_out, limit_w, temp, grid) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (ts, t.soc, t.in_w, t.out_w, t.ac_in_w, t.ac_out_w, t.cfg_limit, t.temp,
                 None if getattr(t, "grid", None) is None else int(bool(t.grid))),
            )
            self._db.commit()
        self._last_ts = ts
        return True

    # ---- planned outages published by the distribution company (see schedule.py); the site never serves past days,
    # so every day it shows is kept here to compare with the real outages later
    def schedule_put(self, region: str, days: dict, updated: str) -> int:
        rows = [(region, int(day), grp, hours, updated) for day, groups in days.items() for grp, hours in groups.items()]
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO schedule (region, day, grp, hours, updated) VALUES (?,?,?,?,?)", rows)
            self._db.execute("DELETE FROM schedule WHERE day < ?", (int(time.time()) - 60 * 86400,))
            self._db.commit()
        return len(rows)

    def schedule_rows(self, since: float) -> list[tuple]:
        """(region, day, group, hours, published) for days after `since` (what gets shared)."""
        with self._lock:
            return self._db.execute("SELECT region, day, grp, hours, updated FROM schedule WHERE day >= ? "
                                    "ORDER BY region, day, grp", (int(since),)).fetchall()

    def schedule_put_rows(self, rows: list[tuple]) -> None:
        if not rows:
            return
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO schedule (region, day, grp, hours, updated) VALUES (?,?,?,?,?)", rows)
            self._db.commit()

    def schedule_count(self, region: str) -> int:
        """How many day/group rows were ever saved for the region (0 = the schedule was never fetched)."""
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM schedule WHERE region = ?", (region,)).fetchone()[0]

    def schedule_days(self, region: str, grp: str, t0: float, t1: float) -> dict[int, str]:
        """{day (unix midnight): 24 state letters} for the days overlapping [t0, t1]."""
        with self._lock:
            rows = self._db.execute("SELECT day, hours FROM schedule WHERE region = ? AND grp = ? AND day > ? AND day < ?",
                                    (region, grp, int(t0) - 86400, int(t1))).fetchall()
        return {d: h for d, h in rows}

    # ---- manual marks
    def add_marks(self, rows: list[tuple], own: bool) -> int:
        """Rows (start, end, kind, made at, made by). Known ones are skipped; returns how many are new."""
        with self._lock:
            before = self._db.total_changes
            self._db.executemany("INSERT OR IGNORE INTO marks (start, end, kind, at, by, own) VALUES (?,?,?,?,?,?)",
                                 [(*r, int(own)) for r in rows])
            added = self._db.total_changes - before
            self._db.execute("DELETE FROM marks WHERE end < ?", (int(time.time()) - MARKS_KEEP,))
            self._db.commit()
        return added

    def marks(self, own_only: bool = False) -> list[tuple]:
        with self._lock:
            return self._db.execute("SELECT start, end, kind, at, by FROM marks " +
                                    ("WHERE own = 1 " if own_only else "") + "ORDER BY at, by, start").fetchall()

    # ---- sync helpers (see sync.py)
    def meta_get(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            r = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r[0] if r else default

    def meta_set(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
            self._db.commit()

    def local_since(self, ts: float) -> list[tuple]:
        """Samples recorded by THIS install after `ts` (what gets shared; imported rows are never re-shared)."""
        with self._lock:
            return self._db.execute(
                "SELECT ts, soc, in_w, out_w, ac_in, ac_out, limit_w, temp, grid FROM samples "
                "WHERE src IS NULL AND ts > ? ORDER BY ts", (int(ts),)).fetchall()

    def local_between(self, t0: float, t1: float) -> list[tuple]:
        """All samples recorded by THIS install in [t0, t1) - the content of one shared chunk file."""
        with self._lock:
            return self._db.execute(
                "SELECT ts, soc, in_w, out_w, ac_in, ac_out, limit_w, temp, grid FROM samples "
                "WHERE src IS NULL AND ts >= ? AND ts < ? ORDER BY ts", (int(t0), int(t1))).fetchall()

    def add_peer_rows(self, rows: list[tuple], src: str) -> int:
        """Store rows shared by another install; existing timestamps and rows older than the retention are skipped."""
        cutoff = int(time.time()) - KEEP_SECONDS
        data = [(int(r[0]), *r[1:9], src) for r in rows if int(r[0]) >= cutoff]
        if not data:
            return 0
        with self._lock:
            before = self._db.total_changes
            self._db.executemany(
                "INSERT OR IGNORE INTO samples (ts, soc, in_w, out_w, ac_in, ac_out, limit_w, temp, grid, src) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", data)
            self._db.commit()
            return self._db.total_changes - before

    def prune(self):
        with self._lock:
            self._db.execute("DELETE FROM samples WHERE ts < ?", (int(time.time()) - KEEP_SECONDS,))
            self._db.commit()

    def range(self, since: float, until: float | None = None, with_prev: bool = False) -> list[tuple]:
        """Rows in [since, until]. with_prev also returns the newest row BEFORE `since`, so a graph can draw the
        line (or gap bridge) from the left edge instead of starting at the first row inside the range."""
        cols = "ts, soc, in_w, out_w, ac_in, ac_out, limit_w, temp, grid, src"
        with self._lock:
            rows = self._db.execute(
                f"SELECT {cols} FROM samples WHERE ts >= ? AND ts <= ? ORDER BY ts",
                (int(since) - STALE_CONTEXT, int(until or time.time() + 1))).fetchall()
        rows = [r for r in drop_stale_samples(rows) if r[0] >= int(since)]      # context before `since` only feeds the filter
        with self._lock:
            if with_prev:
                prev = self._db.execute(f"SELECT {cols} FROM samples WHERE ts < ? ORDER BY ts DESC LIMIT 1",
                                        (int(since),)).fetchone()
                if prev:
                    rows.insert(0, prev)
        return rows

    def daily_energy_kwh(self, days: int = 7) -> list[tuple[str, float, float, bool]]:
        """[(YYYY-MM-DD, in_kWh, out_kWh, has_data)] for the last `days` days, oldest first.
        Integrates power over time; gaps longer than 5 min are not counted."""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=days - 1)
        rows = self.range(start.timestamp())
        acc: dict[str, list[float]] = {(start + timedelta(days=i)).strftime("%Y-%m-%d"): [0.0, 0.0] for i in range(days)}
        for a, b in zip(rows, rows[1:]):
            dt = b[0] - a[0]
            if dt <= 0 or dt > 300:
                continue
            key = datetime.fromtimestamp(a[0]).strftime("%Y-%m-%d")
            if key in acc:
                acc[key][0] += (a[2] or 0) * dt / 3.6e6
                acc[key][1] += (a[3] or 0) * dt / 3.6e6
        have = {datetime.fromtimestamp(r[0]).strftime("%Y-%m-%d") for r in rows}
        return [(k, v[0], v[1], k in have) for k, v in acc.items()]
