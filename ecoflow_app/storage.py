"""Local SQLite history (kept ~8 days) so graphs work offline."""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta

KEEP_SECONDS = 8 * 86400
MIN_INTERVAL = 30  # seconds between stored samples

# Row layout returned by range(): (ts, soc, in_w, out_w, ac_in, ac_out, limit_w, temp, grid)
GRID_IDX = 8


class History:
    def __init__(self, path):
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS samples (ts INTEGER PRIMARY KEY, soc REAL, in_w REAL, "
            "out_w REAL, ac_in REAL, ac_out REAL, limit_w INTEGER, temp REAL)"
        )
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(samples)")}
        if "grid" not in cols:  # added with the power-outage feature: 1 mains present, 0 absent, NULL unknown (old rows)
            self._db.execute("ALTER TABLE samples ADD COLUMN grid INTEGER")
        # drop samples built from partial state by an earlier version (limit is never 0 on a real reading)
        self._db.execute("DELETE FROM samples WHERE limit_w IS NULL OR limit_w = 0")
        self._db.commit()
        self._last_ts = self._scalar("SELECT MAX(ts) FROM samples") or 0
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

    def prune(self):
        with self._lock:
            self._db.execute("DELETE FROM samples WHERE ts < ?", (int(time.time()) - KEEP_SECONDS,))
            self._db.commit()

    def range(self, since: float, until: float | None = None, with_prev: bool = False) -> list[tuple]:
        """Rows in [since, until]. with_prev also returns the newest row BEFORE `since`, so a graph can draw the
        line (or gap bridge) from the left edge instead of starting at the first row inside the range."""
        cols = "ts, soc, in_w, out_w, ac_in, ac_out, limit_w, temp, grid"
        with self._lock:
            rows = self._db.execute(
                f"SELECT {cols} FROM samples WHERE ts >= ? AND ts <= ? ORDER BY ts",
                (int(since), int(until or time.time() + 1))).fetchall()
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
