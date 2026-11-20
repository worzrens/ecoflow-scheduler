"""Custom-painted widgets: smooth area chart (pic 'Statistic'), pill bar chart (pic 'energy usages'), battery bar."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .util import soc_color

BG = "#0e1013"
CARD = "#171a1f"
CARD2 = "#20242b"
GRID = "#2a2e36"
TEXT = "#f3f4f6"
MUTED = "#8b93a1"
GREEN = "#2ee68a"
ORANGE = "#ffa629"
BAR = "#2c3038"


def downsample(points: list[tuple[float, float]], n: int = 500) -> list[tuple[float, float]]:
    """Average into at most n time buckets (keeps graphs fast for 7 days of data)."""
    if len(points) <= n:
        return points
    t0, t1 = points[0][0], points[-1][0]
    span = (t1 - t0) / n or 1
    out, bucket, idx = [], [], 0
    for t, v in points:
        i = min(int((t - t0) / span), n - 1)
        if i != idx and bucket:
            out.append((sum(b[0] for b in bucket) / len(bucket), sum(b[1] for b in bucket) / len(bucket)))
            bucket = []
        idx = i
        bucket.append((t, v))
    if bucket:
        out.append((sum(b[0] for b in bucket) / len(bucket), sum(b[1] for b in bucket) / len(bucket)))
    return out


def monotone_path(pts: list[QPointF]) -> QPainterPath:
    """Smooth curve through points without overshoot (Fritsch-Carlson monotone cubic)."""
    path = QPainterPath()
    clean: list[QPointF] = []
    for p in pts:
        if not clean or p.x() - clean[-1].x() > 0.01:
            clean.append(p)
    n = len(clean)
    if n == 0:
        return path
    path.moveTo(clean[0])
    if n == 1:
        return path
    if n == 2:
        path.lineTo(clean[1])
        return path
    dx = [clean[i + 1].x() - clean[i].x() for i in range(n - 1)]
    m = [(clean[i + 1].y() - clean[i].y()) / dx[i] for i in range(n - 1)]
    t = [m[0]] + [0.0 if m[i - 1] * m[i] <= 0 else (m[i - 1] + m[i]) / 2 for i in range(1, n - 1)] + [m[-1]]
    for i in range(n - 1):
        if m[i] == 0:
            t[i] = t[i + 1] = 0.0
        else:
            a, b = t[i] / m[i], t[i + 1] / m[i]
            s = a * a + b * b
            if s > 9:
                tau = 3 / math.sqrt(s)
                t[i], t[i + 1] = tau * a * m[i], tau * b * m[i]
    for i in range(n - 1):
        h = dx[i] / 3
        path.cubicTo(clean[i].x() + h, clean[i].y() + t[i] * h,
                     clean[i + 1].x() - h, clean[i + 1].y() - t[i + 1] * h, clean[i + 1].x(), clean[i + 1].y())
    return path


def nice_step(top: float, max_ticks: int = 5) -> float:
    for s in (50, 100, 200, 250, 500, 1000, 2000, 5000):
        if top / s <= max_ticks:
            return s
    return 5000


def kwh_step(peak: float) -> float:
    for s in (0.25, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500):
        if peak / s <= 4:
            return s
    return 1000


def auto_top(peak: float) -> float:
    """Default 0-500 W; grows in 100 W increments when values exceed 500 W."""
    return max(500.0, math.ceil(peak / 100.0) * 100.0)


@dataclass
class Series:
    name: str
    color: str
    pts: list[tuple[float, float]] = field(default_factory=list)  # (epoch seconds, value)
    step_zero: bool = False   # input power: a drop to ~0 across a data gap is an outage -> drops at once


class AreaChart(QWidget):
    """Smooth gradient-filled line chart with dashed grid, hover crosshair, glow dot and value bubble."""

    def __init__(self, unit: str = "W"):
        super().__init__()
        self.unit = unit
        self.series: list[Series] = []
        self.t0 = 0.0
        self.t1 = 1.0
        self.y_lo: float | None = None   # None -> 0
        self.y_hi: float | None = None   # None -> auto
        self.fixed_hi: float | None = None
        self._hover_x: float | None = None
        self._screen: dict[str, list[tuple[float, float, float, float]]] = {}  # name -> (px, py, t, v)
        self.setMouseTracking(True)
        self.setMinimumHeight(150)

    # ---- data / scale
    def set_data(self, series: list[Series], t0: float, t1: float):
        self.series, self.t0, self.t1 = series, t0, max(t1, t0 + 1)
        self.update()

    def set_y_range(self, lo: float | None, hi: float | None):
        self.y_lo, self.y_hi = lo, hi
        self.update()

    def _scale(self) -> tuple[float, float]:
        lo = self.y_lo or 0.0
        if self.y_hi is not None:
            return lo, max(self.y_hi, lo + 10)
        if self.fixed_hi is not None:
            return lo, self.fixed_hi
        peak = max([v for s in self.series for _, v in s.pts] + [0.0])
        return lo, auto_top(peak)

    def _plot(self) -> QRectF:
        return QRectF(52, 26, max(10, self.width() - 52 - 14), max(10, self.height() - 26 - 30))

    # ---- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        lo, hi = self._scale()
        small = QFont(self.font())
        small.setPointSize(8)
        p.setFont(small)

        step = nice_step(hi - lo)
        v = math.ceil(lo / step) * step
        while v <= hi + 1e-6:
            y = r.bottom() - (v - lo) / (hi - lo) * r.height()
            p.setPen(QPen(QColor(GRID), 1, Qt.DashLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, y - 9, r.left() - 8, 18), Qt.AlignRight | Qt.AlignVCenter, f"{v:g}")
            v += step
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(0, 2, r.left() - 8, 14), Qt.AlignRight, self.unit)

        span = self.t1 - self.t0
        fmt = "%H:%M:%S" if span <= 1800 else ("%H:%M" if span <= 86400 else "%a %H:%M")
        for i in range(5):
            frac = i / 4
            x = r.left() + frac * r.width()
            label = datetime.fromtimestamp(self.t0 + frac * span).strftime(fmt)
            w = 70
            bx = min(max(x - w / 2, 0), self.width() - w)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(bx, r.bottom() + 8, w, 16), Qt.AlignCenter, label)

        self._screen = {}
        items = []  # (series index, color, run paths, connector segments, fill path)
        for si, s in enumerate(self.series):
            inside = [(t, val) for t, val in s.pts if self.t0 <= t <= self.t1]
            before = [(t, val) for t, val in s.pts if t < self.t0]
            after = [(t, val) for t, val in s.pts if t > self.t1]
            # one neighbour on each side so lines / gap bridges reach the plot edges (clipped when drawing)
            raw = ([before[-1]] if before else []) + inside + ([after[0]] if after else [])
            pts = downsample(raw, max(40, int(r.width() / 9)))
            if not pts:
                continue
            ys = [r.bottom() - (min(max(val, lo), hi) - lo) / (hi - lo) * r.height() for _, val in pts]
            xs = [r.left() + (t - self.t0) / span * r.width() for t, _ in pts]
            dts = sorted(pts[i + 1][0] - pts[i][0] for i in range(len(pts) - 1))
            thresh = max(90.0, span / 150, 3 * (dts[len(dts) // 2] if dts else 0))
            is_gap = [pts[i][0] - pts[i - 1][0] > thresh for i in range(1, len(pts))]   # gap before point i+1
            sm = ys[:]                                   # light smoothing for drawing only, never across a gap
            for i in range(1, len(ys) - 1):
                if not is_gap[i - 1] and not is_gap[i]:
                    sm[i] = 0.25 * ys[i - 1] + 0.5 * ys[i] + 0.25 * ys[i + 1]
            sp = [QPointF(x, y) for x, y in zip(xs, sm)]
            # hover points sit ON the drawn curve (smoothed y) but report the real averaged value
            self._screen[s.name] = [(x, y, t, val) for x, y, (t, val) in zip(xs, sm, pts) if self.t0 <= t <= self.t1]
            zero_y = r.bottom() - (min(max(0.0, lo), hi) - lo) / (hi - lo) * r.height()
            runs, gaps = [[sp[0]]], []
            for i in range(1, len(pts)):
                if is_gap[i - 1]:     # missing data: bridge with a dashed line
                    a_, b_ = sp[i - 1], sp[i]
                    va, vb = pts[i - 1][1], pts[i][1]
                    poly = [a_, b_]
                    if s.step_zero and va > 5 >= vb:       # input vanished: outage started right after the last point
                        poly = [a_, QPointF(a_.x(), zero_y), QPointF(b_.x(), zero_y), b_]
                    elif s.step_zero and vb > 5 >= va:     # input back: it stays 0 until data resumes
                        poly = [a_, QPointF(b_.x(), a_.y()), b_]
                    gaps.append(poly)
                    runs.append([sp[i]])
                else:
                    runs[-1].append(sp[i])
            run_paths = [monotone_path(run) for run in runs]
            # fill polygon built explicitly (a QPainterPath holding only a moveTo counts as "empty" and swallows connectPath)
            fill = QPainterPath()
            fill.moveTo(sp[0].x(), r.bottom())
            fill.lineTo(sp[0])
            for k, run in enumerate(runs):
                if k > 0:
                    for corner in gaps[k - 1][1:-1]:
                        fill.lineTo(corner)
                    fill.lineTo(run[0])
                fill.connectPath(run_paths[k])
            fill.lineTo(sp[-1].x(), r.bottom())
            fill.closeSubpath()
            items.append((si, s.color, run_paths, gaps, fill))

        p.save()
        p.setClipRect(QRectF(r.left() - 1, r.top() - 6, r.width() + 2, r.height() + 12))
        # fills: later series first so the FIRST series (green input) sits on top at the bottom of the graph
        for si, color, _, _, fill in reversed(items):
            c = QColor(color)
            g = QLinearGradient(0, r.top(), 0, r.bottom())
            top_c, bot_c = QColor(c), QColor(c)
            top_c.setAlpha(120 if si == 0 else 55)
            bot_c.setAlpha(8)
            g.setColorAt(0, top_c)
            g.setColorAt(1, bot_c)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawPath(fill)
        p.setBrush(Qt.NoBrush)
        for si, color, run_paths, gaps, _ in reversed(items):
            c = QColor(color)
            pen = QPen(c, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            for seg in run_paths:
                p.drawPath(seg)
            dash = QPen(c, 2.5)
            dash.setDashPattern([2.0, 2.5])
            dash.setCapStyle(Qt.FlatCap)
            p.setPen(dash)
            for poly in gaps:
                p.drawPolyline(QPolygonF(poly))
        p.restore()

        if not self._screen:
            p.setPen(QColor(MUTED))
            p.drawText(r, Qt.AlignCenter, "No data in this range yet")
        self._paint_hover(p, r)

    def _nearest(self, name: str, x: float):
        pts = self._screen.get(name)
        if not pts:
            return None
        best = min(pts, key=lambda q: abs(q[0] - x))
        return best if abs(best[0] - x) <= 40 else None

    def _paint_hover(self, p: QPainter, r: QRectF):
        if self._hover_x is None or not self._screen:
            return
        hits = [(s, self._nearest(s.name, self._hover_x)) for s in self.series]
        hits = [(s, h) for s, h in hits if h]
        if not hits:
            return
        gx = hits[0][1][0]
        p.setPen(QPen(QColor("#4b5160"), 1, Qt.DashLine))
        p.drawLine(QPointF(gx, r.top()), QPointF(gx, r.bottom()))
        for s, (x, y, _, _) in hits:
            halo = QColor(s.color)
            halo.setAlpha(70)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QPointF(x, y), 10, 10)      # soft glow
            p.setBrush(QColor(s.color))
            p.setPen(QPen(QColor(BG), 2))
            p.drawEllipse(QPointF(x, y), 5, 5)         # dot a bit larger than the 2.5 px line
        t = hits[0][1][2]
        span = self.t1 - self.t0
        when = datetime.fromtimestamp(t).strftime("%H:%M:%S" if span <= 1800 else "%d.%m %H:%M")
        lines = [(when, MUTED)] + [(f"{s.name}  {h[3]:.0f} {self.unit}", s.color) for s, h in hits]
        f = QFont(self.font())
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = max(fm.horizontalAdvance(t_) for t_, _ in lines) + 24
        h = len(lines) * 18 + 14
        bx = gx + 14 if gx + 14 + w < self.width() else gx - 14 - w
        by = max(2, min(hits[0][1][1] - h - 12, self.height() - h - 2))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(CARD2))
        p.drawRoundedRect(QRectF(bx, by, w, h), 12, 12)
        for i, (txt, col) in enumerate(lines):
            p.setPen(QColor(col))
            p.drawText(QRectF(bx + 12, by + 7 + i * 18, w - 16, 18), Qt.AlignLeft | Qt.AlignVCenter, txt)

    def mouseMoveEvent(self, e):
        self._hover_x = e.position().x()
        self.update()

    def leaveEvent(self, _):
        self._hover_x = None
        self.update()


class PillBars(QWidget):
    """One pill bar per day; hovered/selected bar turns green (like the energy-usage screenshot)."""

    def __init__(self):
        super().__init__()
        self.rows: list[tuple] = []   # (iso date, in_kwh, out_kwh, has_data)
        self.which = "out"
        self.sel = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(180)

    def set_data(self, rows, which: str):
        self.rows, self.which = rows, which
        if not (0 <= self.sel < len(rows)):
            self.sel = len(rows) - 1
        self.update()

    def _vals(self) -> list[float]:
        i = 2 if self.which == "out" else 1
        return [r[i] for r in self.rows]

    def _geom(self):
        r = QRectF(78, 14, max(10, self.width() - 78 - 12), max(10, self.height() - 14 - 34))
        n = max(1, len(self.rows))
        slot = r.width() / n
        return r, slot

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r, slot = self._geom()
        vals = self._vals()
        peak = max(vals + [0.5])
        step = kwh_step(peak)
        top = math.ceil(peak / step) * step
        small = QFont(self.font())
        small.setPointSize(8)
        p.setFont(small)
        v = 0.0
        while v <= top + 1e-6:
            y = r.bottom() - v / top * r.height()
            p.setPen(QPen(QColor(GRID), 1, Qt.DashLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, y - 9, r.left() - 10, 18), Qt.AlignRight | Qt.AlignVCenter, f"{v:g} kWh")
            v += step
        bw = min(34.0, slot * 0.6)
        rad = min(9.0, bw / 2)
        for i, (row, val) in enumerate(zip(self.rows, vals)):
            has = row[3] if len(row) > 3 else True
            cx = r.left() + slot * (i + 0.5)
            sel = i == self.sel
            if has:
                h = max(rad * 2, val / top * r.height())
                rect = QRectF(cx - bw / 2, r.bottom() - h, bw, h)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(GREEN if sel else BAR))
                p.drawRoundedRect(rect, rad, rad)
            else:   # no data for this day: dashed placeholder box
                rect = QRectF(cx - bw / 2, r.bottom() - r.height() * 0.38, bw, r.height() * 0.38)
                pen = QPen(QColor(GREEN if sel else "#4a505c"), 1.5)
                pen.setDashPattern([3.0, 3.0])
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect, rad, rad)
            f = QFont(self.font())
            f.setPointSize(9)
            f.setBold(sel)
            p.setFont(f)
            p.setPen(QColor(TEXT if sel else MUTED))
            day = datetime.strptime(row[0], "%Y-%m-%d").strftime("%a")
            p.drawText(QRectF(cx - slot / 2, r.bottom() + 10, slot, 18), Qt.AlignCenter, day)
            if sel:
                txt = f"{val:.2f} kWh" if has else "No data"
                fm = p.fontMetrics()
                w = fm.horizontalAdvance(txt) + 22
                bx = min(max(cx - w / 2, 2), self.width() - w - 2)
                by = max(2, rect.top() - 34)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(CARD2))
                p.drawRoundedRect(QRectF(bx, by, w, 26), 10, 10)
                p.setPen(QColor(TEXT))
                p.drawText(QRectF(bx, by, w, 26), Qt.AlignCenter, txt)
            p.setFont(small)

    def mouseMoveEvent(self, e):
        if not self.rows:
            return
        r, slot = self._geom()
        i = int((e.position().x() - r.left()) // slot)
        if 0 <= i < len(self.rows) and i != self.sel:
            self.sel = i
            self.update()


class BatteryBar(QWidget):
    """Rounded battery slab. Colour follows the charge level; the fill is animated by state:
    charging = light sweeping towards the full end, discharging = slower sweep the other way,
    full = gentle breathing glow."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(96)
        self.soc: float | None = None
        self.active = False
        self.mode = "idle"          # charging | discharging | full | ongrid | idle
        self.compact = False
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.update)

    def set_compact(self, on: bool):
        self.compact = on
        self.setMinimumHeight(30 if on else 96)
        self.updateGeometry()
        self.update()

    def set_soc(self, soc: float | None, active: bool, mode: str = "idle"):
        self.soc, self.active, self.mode = soc, active, (mode if active else "idle")
        self._sync_timer()
        self.update()

    def _animated(self) -> bool:
        return self.isVisible() and self.soc is not None and self.mode in ("charging", "discharging", "full")

    def _sync_timer(self):
        if self._animated() and not self._timer.isActive():
            self._timer.start()
        elif not self._animated() and self._timer.isActive():
            self._timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_timer()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._sync_timer()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        comp = self.compact
        r = QRectF(2, 2, self.width() - 4, self.height() - 4) if comp else QRectF(2, 8, self.width() - 4, self.height() - 38)
        rad, frad = (8, 6) if comp else (18, 14)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1d2025"))
        p.drawRoundedRect(r, rad, rad)
        if self.soc is not None:
            color = QColor(soc_color(self.soc) if self.active else "#6b7280")
            inset = 3 if comp else 4
            w = max(r.height(), (r.width() - 2 * inset) * max(0.0, min(100.0, self.soc)) / 100)
            fill = QRectF(r.x() + inset, r.y() + inset, w, r.height() - 2 * inset)
            g = QLinearGradient(fill.topLeft(), fill.topRight())
            g.setColorAt(0, color.darker(190))
            g.setColorAt(0.75, color)
            g.setColorAt(1, color.lighter(125))
            p.setBrush(g)
            p.drawRoundedRect(fill, frad, frad)
            self._paint_animation(p, fill, frad)
        f = QFont(self.font())
        f.setPointSize(10 if comp else 15)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(r, Qt.AlignCenter, f"{self.soc:.0f}%" if self.soc is not None else "--")
        if not comp:
            f.setPointSize(8)
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(6, r.bottom() + 6, 200, 18), Qt.AlignLeft, "Discharge limit  0%")
            p.drawText(QRectF(self.width() - 206, r.bottom() + 6, 200, 18), Qt.AlignRight, "Charge limit  100%")

    def _paint_animation(self, p: QPainter, fill: QRectF, radius: float = 14):
        if self.mode not in ("charging", "discharging", "full"):
            return
        t = time.monotonic()
        clip = QPainterPath()
        clip.addRoundedRect(fill, radius, radius)
        p.save()
        p.setClipPath(clip)
        p.setPen(Qt.NoPen)
        if self.mode == "full":
            a = int(30 + 55 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / 2.4)))
            p.setBrush(QColor(255, 255, 255, a))
            p.drawRect(fill)
        else:
            charging = self.mode == "charging"
            period = 1.3 if charging else 2.6
            phase = (t % period) / period
            # 1) scrolling diagonal stripes (barber-pole): forward while charging, backward while discharging
            stripe, gap, slope = 16.0, 22.0, 14.0
            pitch = stripe + gap
            off = (phase if charging else -phase) * pitch
            x = fill.left() - pitch * 2 + off
            p.setBrush(QColor(255, 255, 255, 60 if charging else 38))
            while x < fill.right() + pitch:
                p.drawPolygon(QPolygonF([QPointF(x, fill.bottom()), QPointF(x + stripe, fill.bottom()),
                                         QPointF(x + stripe + slope, fill.top()), QPointF(x + slope, fill.top())]))
                x += pitch
            # 2) a bright sweep on top
            bw = max(110.0, fill.width() * 0.34)
            span = fill.width() + bw
            sx = fill.left() - bw + phase * span if charging else fill.right() - phase * span
            band = QLinearGradient(sx, 0, sx + bw, 0)
            peak = 170 if charging else 110
            band.setColorAt(0, QColor(255, 255, 255, 0))
            band.setColorAt(0.5, QColor(255, 255, 255, peak))
            band.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(band)
            p.drawRect(QRectF(sx, fill.top(), bw, fill.height()))
        p.restore()
