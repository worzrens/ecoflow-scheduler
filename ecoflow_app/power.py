"""Power state (charging / discharging / fully charged) and mains-outage segments. Pure logic, no Qt."""
from __future__ import annotations

from dataclasses import dataclass, field

GRID_MIN_AC_WATTS = 5          # legacy rows without a grid flag: mains present if AC input >= this
MAX_GAP = 180                  # seconds between samples before the time is "no data"
COVER_AFTER_SAMPLE = 60        # a sample alone is trusted for this long


def state_of(soc: float, in_w: float, out_w: float, grid: bool, prev: str | None = None) -> str:
    """'charging' | 'discharging' | 'full' | 'ongrid'. `prev` adds hysteresis so values near a threshold don't flicker."""
    net = in_w - out_w
    if not grid:
        return "charging" if net > 3 else "discharging"     # no mains: only solar can charge
    if soc >= 99.5 or (prev == "full" and soc >= 98):
        return "full" if net >= -3 else "discharging"
    if net > 3 or (prev == "charging" and net > 0):
        return "charging"
    if net < -3:
        return "discharging"
    return "ongrid"


def input_breakdown(in_w: float, out_w: float) -> tuple[float, float, float]:
    """Split the input power while on grid: (charging, usage, total). E.g. 815 W in, 515 W load -> 300 W charging + 515 W usage."""
    usage = min(max(out_w, 0.0), max(in_w, 0.0))
    return max(0.0, in_w - usage), usage, max(in_w, 0.0)


def row_grid(row: tuple) -> bool:
    """grid flag of a history row (ts, soc, in, out, ac_in, ac_out, limit, temp, grid)."""
    g = row[8] if len(row) > 8 else None
    if g is None:
        return (row[4] or 0) >= GRID_MIN_AC_WATTS
    return bool(g)


def state_since(rows: list[tuple]) -> tuple[str | None, float | None]:
    """Walk history rows (ascending) and return (current state, timestamp the current run started)."""
    prev, since = None, None
    for r in rows:
        s = state_of(r[1] or 0, r[2] or 0, r[3] or 0, row_grid(r), prev)
        if s != prev:
            prev, since = s, r[0]
    return prev, since


@dataclass
class Segment:
    start: float
    end: float
    kind: str            # 'grid' | 'outage' | 'nodata'
    out_kwh: float = 0.0
    in_kwh: float = 0.0
    est_spans: list = field(default_factory=list)   # [(start, end)] parts estimated from neighbouring data

    @property
    def guessed(self) -> bool:
        return bool(self.est_spans)

    @property
    def est_seconds(self) -> float:
        return sum(b - a for a, b in self.est_spans)

    @property
    def seconds(self) -> float:
        return self.end - self.start


def grid_segments(rows: list[tuple], t0: float, t1: float, now: float | None = None) -> list[Segment]:
    """Cover [t0, min(t1, now)] with segments: mains present, outage, or no data (app not running / offline)."""
    end_limit = t1 if now is None else min(t1, now)
    if end_limit <= t0:
        return []
    raw: list[Segment] = []
    for i, r in enumerate(rows):
        ts = r[0]
        nxt = rows[i + 1][0] if i + 1 < len(rows) else None
        kind = "grid" if row_grid(r) else "outage"
        if nxt is not None and nxt - ts <= MAX_GAP:
            seg_end = nxt                                   # continuous recording
        elif nxt is None and now is not None and now - ts <= MAX_GAP:
            seg_end = now                                   # latest state, still current
        else:
            seg_end = ts + COVER_AFTER_SAMPLE               # recording stopped: trust the sample briefly, then no data
        a, b = max(ts, t0), min(seg_end, end_limit)
        if b <= a:
            continue
        dt = b - a
        raw.append(Segment(a, b, kind, (r[3] or 0) * dt / 3.6e6, (r[2] or 0) * dt / 3.6e6))
    out: list[Segment] = []
    cursor = t0
    for s in raw:
        if s.start - cursor > 1:
            out.append(Segment(cursor, s.start, "nodata"))
        if out and out[-1].kind == s.kind and abs(out[-1].end - s.start) <= 1:
            last = out[-1]
            last.end = s.end
            last.out_kwh += s.out_kwh
            last.in_kwh += s.in_kwh
        else:
            out.append(s)
        cursor = max(cursor, s.end)
    if end_limit - cursor > 1:
        out.append(Segment(cursor, end_limit, "nodata"))
    return out


def outage_seconds(segments: list[Segment], only_guessed: bool = False) -> float:
    return sum((s.est_seconds if only_guessed else s.seconds) for s in segments if s.kind == "outage")


def outage_count(segments: list[Segment]) -> int:
    """Number of separate outages (a real part and an estimated part touching each other count once)."""
    n, inside = 0, False
    for s in segments:
        if s.kind == "outage":
            n += 0 if inside else 1
            inside = True
        else:
            inside = False
    return n


def _avg_watts(seg: Segment) -> tuple[float, float]:
    if seg.seconds <= 0:
        return 0.0, 0.0
    return seg.out_kwh * 3.6e6 / seg.seconds, seg.in_kwh * 3.6e6 / seg.seconds


def fill_gaps(segs: list[Segment], trailing_max: float = 7200) -> list[Segment]:
    """Replace 'nodata' stretches by an estimate from the neighbouring parts that have data:
    same kind on both sides -> that kind; mains vs outage -> the outage fills the gap; a short trailing gap
    (unit offline for a moment) -> last known kind. Leading gaps stay unknown. Estimated parts carry guessed=True
    and the neighbour's average power, so energy figures are estimates too."""
    out: list[Segment] = []
    for i, s in enumerate(segs):
        if s.kind != "nodata":
            out.append(s)
            continue
        prev = next((x for x in reversed(segs[:i]) if x.kind != "nodata"), None)
        nxt = next((x for x in segs[i + 1:] if x.kind != "nodata"), None)
        parts: list[tuple[float, float, Segment]] = []
        if prev and nxt:
            # same kind on both sides -> that kind. Mains on one side and an outage on the other: the outage
            # fills the whole gap (power drops at once when mains fail; it only ends when data resumes).
            src = prev if (prev.kind == nxt.kind or prev.kind == "outage") else nxt
            parts = [(s.start, s.end, src)]
        elif prev and s.seconds <= trailing_max:
            parts = [(s.start, s.end, prev)]
        if not parts:
            out.append(s)
            continue
        for a, b, src in parts:
            ow, iw = _avg_watts(src)
            out.append(Segment(a, b, src.kind, ow * (b - a) / 3.6e6, iw * (b - a) / 3.6e6, [(a, b)]))
    return out


def slice_segments(segs: list[Segment], t0: float, t1: float) -> list[Segment]:
    """Clip segments to [t0, t1] (energy scaled by the kept fraction)."""
    out = []
    for s in segs:
        a, b = max(s.start, t0), min(s.end, t1)
        if b <= a:
            continue
        f = (b - a) / s.seconds if s.seconds > 0 else 0.0
        spans = [(max(x, t0), min(y, t1)) for x, y in s.est_spans if min(y, t1) > max(x, t0)]
        out.append(Segment(a, b, s.kind, s.out_kwh * f, s.in_kwh * f, spans))
    return out


def merge_same_kind(segs: list[Segment]) -> list[Segment]:
    """Join touching segments of the same kind into one zone (real + estimated parts together)."""
    out: list[Segment] = []
    for s in segs:
        if out and out[-1].kind == s.kind and abs(out[-1].end - s.start) <= 1:
            last = out[-1]
            last.end = s.end
            last.out_kwh += s.out_kwh
            last.in_kwh += s.in_kwh
            last.est_spans = last.est_spans + list(s.est_spans)
        else:
            out.append(Segment(s.start, s.end, s.kind, s.out_kwh, s.in_kwh, list(s.est_spans)))
    return out
