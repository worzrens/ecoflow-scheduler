"""Reference output for the Android widget's Java port of power.py / schedule.py.

    python tools/make_android_golden.py      # rewrites android/app/src/test/resources/golden.json
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ecoflow_app.power import drop_stale_samples, fill_gaps, grid_segments, link_battery, merge_same_kind  # noqa: E402
from ecoflow_app.schedule import day_segments  # noqa: E402

OUT = ROOT / "android" / "app" / "src" / "test" / "resources" / "golden.json"
KIND = {"nodata": 0, "grid": 1, "outage": 2, "maybe": 3}


def random_rows(seed: int) -> list[tuple]:
    """Two installs watching one unit: outages, sleeps, recharges and a replayed old state."""
    rnd = random.Random(seed)
    rows, t, soc, grid = [], 1_000_000, 80.0, 1
    while t < 1_000_000 + 40_000:
        if rnd.random() < 0.03:
            grid = 1 - grid
        step = rnd.choice([30, 30, 40, 60, 90]) if rnd.random() > 0.04 else rnd.randint(200, 9000)
        soc = min(100.0, max(1.0, soc + (rnd.uniform(0, 0.6) if grid else -rnd.uniform(0, 0.5)) * step / 40))
        src = "a" if rnd.random() < 0.7 else "b"
        power = 300 if grid else 0
        rows.append((t, round(soc, 3), power, rnd.randint(20, 400), power, 100, 300, 28, grid, src))
        if rnd.random() < 0.02:         # the same source later reports exactly this state again
            later = t + rnd.randint(700, 3000)
            rows.append((later, round(soc, 3), power, 50, power, 50, 300, 28, grid, src))
        t += step
    unique = {r[0]: r for r in rows}
    return [unique[k] for k in sorted(unique)]


def pack(segs, full=True):
    return [[s.start, s.end, KIND[s.kind]] + ([s.soc_start, s.soc_end, s.out_kwh] if full else []) for s in segs]


def build() -> dict:
    history = []
    for seed in range(1, 7):
        rows = random_rows(seed)
        t0, t1 = 1_000_000 + 500, 1_000_000 + 86_400
        now = rows[-1][0] + (60 if seed % 2 else 5000)
        segs = link_battery(merge_same_kind(fill_gaps(grid_segments(drop_stale_samples(rows), t0, t1, now))))
        history.append({"rows": [list(r) for r in rows], "t0": t0, "t1": t1, "now": now, "segments": pack(segs)})
    hours = "YYNNFSMGHYYNNNYYMMSFYYNY"
    day = 1_795_000_000
    return {"history": history, "schedule": {"day": day, "hours": hours, "segments": pack(day_segments(day, hours), False)}}


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), separators=(",", ":")), "utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
