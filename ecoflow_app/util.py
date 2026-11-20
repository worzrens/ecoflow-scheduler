from __future__ import annotations


def fmt_duration(minutes: int | float | None) -> str:
    """16d 11h / 3h 20m / 45m."""
    if minutes is None or minutes <= 0:
        return "--"
    m = int(minutes)
    d, rem = divmod(m, 1440)
    h, mi = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {mi:02d}m"
    return f"{mi}m"


_STOPS = [(0, (239, 68, 68)), (10, (239, 68, 68)), (25, (251, 146, 60)), (45, (250, 204, 21)),
          (70, (46, 230, 138)), (100, (46, 230, 138))]


def soc_color(soc: float) -> str:
    """Battery colour: green (>=70%) -> yellow (45%) -> orange (25%) -> red (<=10%), blended in between."""
    soc = max(0.0, min(100.0, soc))
    for (a, ca), (b, cb) in zip(_STOPS, _STOPS[1:]):
        if a <= soc <= b:
            f = 0 if b == a else (soc - a) / (b - a)
            r, g, bl = (round(x + (y - x) * f) for x, y in zip(ca, cb))
            return f"#{r:02x}{g:02x}{bl:02x}"
    return "#2ee68a"
