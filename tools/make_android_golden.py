"""Reference output for the Android widget's Java port of power.py / schedule.py.

    python tools/make_android_golden.py      # rewrites android/app/src/test/resources/golden.json
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ecoflow_app.power import (apply_marks, drop_stale_samples, fill_gaps, grid_segments, link_battery,  # noqa: E402
                               merge_same_kind, resolve_marks, state_since)
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


def random_marks(seed: int, raw: list) -> list[tuple]:
    """Marks over some stretches without data: whole, partial, overlapping, removed again."""
    rnd = random.Random(seed * 1000)
    marks, at = [], 1.0
    for s in raw:
        if s.kind != "nodata" or rnd.random() < 0.3:
            continue
        for _ in range(rnd.randint(1, 3)):
            a = int(s.start if rnd.random() < 0.5 else rnd.uniform(s.start, s.end))
            b = int(s.end if rnd.random() < 0.5 else rnd.uniform(a, s.end)) + 1
            at += 1
            marks.append((a - 50, b + 50, rnd.choice(["grid", "outage", "outage", "clear"]), at, "pc"))
    rnd.shuffle(marks)
    return marks


def pack(segs, full=True):
    return [[s.start, s.end, KIND[s.kind]]
            + ([s.soc_start, s.soc_end, s.out_kwh, s.manual_seconds] if full else []) for s in segs]


def build() -> dict:
    history = []
    for seed in range(1, 7):
        rows = random_rows(seed)
        t0, t1 = 1_000_000 + 500, 1_000_000 + 86_400
        now = rows[-1][0] + (60 if seed % 2 else 5000)
        raw = grid_segments(drop_stale_samples(rows), t0, t1, now)
        marks = random_marks(seed, raw) if seed > 2 else []
        segs = link_battery(merge_same_kind(fill_gaps(apply_marks(raw, resolve_marks(marks)))))
        part = rows[:len(rows) * seed // 6]                      # different end points -> different current states
        history.append({"rows": [list(r) for r in rows], "marks": [list(m) for m in marks], "t0": t0, "t1": t1, "now": now, "segments": pack(segs),
                        "state_rows": len(part), "state": list(state_since(part))})
    hours = "YYNNFSMGHYYNNNYYMMSFYYNY"
    day = 1_795_000_000
    return {"history": history, "schedule": {"day": day, "hours": hours, "segments": pack(day_segments(day, hours), False)}}


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), separators=(",", ":")), "utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
