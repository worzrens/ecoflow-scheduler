"""Power-outage views: what really happened, and what the distribution company's schedule said would happen.

7 days   -> one full-height 24 h box per day (columns).
1-3 days -> calendar layout: hour grid, wide day columns, event-like blocks with text.
Real chart:     green = grid power, blank = outage, grey = no data (estimates are merged into the zones).
Expected chart: green = power on, ORANGE DASHED OUTLINE without fill = planned outage, dotted = possible outage.
The real chart can overlay the planned outages (orange dashed outlines) to compare how the day really went.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .analytics import fmt_energy
from .charts import CARD, CARD2, GREEN, GRID, MUTED, ORANGE, TEXT
from .controller import Controller
from .power import (MAX_GAP, Segment, fill_gaps, grid_segments, link_battery, merge_same_kind, outage_count, outage_seconds,
                    slice_segments)
from .schedule import count_of, seconds_of

BLANK = CARD                # "no electricity" is drawn as the empty card colour
NODATA = "#2c3038"
OUTAGE_TEXT = "#f87171"
RANGES = {"Today": 1, "3 days": 3, "7 days": 7}
EXPECTED_RANGES = {"Today": (0, 1), "Today + tomorrow": (0, 2), "3 days": (2, 3), "7 days": (6, 7)}   # (days back, days shown)


def fmt_hm(seconds: float) -> str:
    m = int(round(seconds / 60))
    if m <= 0:
        return "0m"
    h, mi = divmod(m, 60)
    return f"{h}h {mi:02d}m" if h else f"{mi}m"


def hhmm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


@dataclass
class DayInfo:
    start: float                 # local midnight
    end: float                   # next midnight
    segments: list[Segment]


KIND_TEXT = {"grid": ("Electricity", GREEN), "outage": ("No electricity", OUTAGE_TEXT), "nodata": ("No data", MUTED)}
PLAN_TEXT = {"grid": ("Power on", GREEN), "outage": ("Planned outage", ORANGE), "maybe": ("Possible outage", ORANGE),
             "nodata": ("No schedule", MUTED)}


def _outline(kind: str, alpha: int = 255) -> QPen | None:
    """Orange dashed outline for a planned outage, dotted for a possible one."""
    c = QColor(ORANGE)
    if kind == "outage":
        pen = QPen(c, 1.8)
        pen.setDashPattern([4.0, 3.0])
        return pen
    if kind == "maybe":
        c.setAlpha(150 if alpha == 255 else alpha)
        pen = QPen(c, 1.5)
        pen.setDashPattern([1.2, 3.0])
        return pen
    return None


class OutageTimeline(QWidget):
    def __init__(self, mode: str = "real"):
        super().__init__()
        self.mode = mode                                    # "real" | "plan"
        self.days: list[DayInfo] = []
        self.overlay: list[DayInfo] | None = None           # planned outages drawn over the real ones
        self.now = time.time()
        self.calendar = False
        self._hover: tuple[int, Segment | None, QPointF, Segment | None] | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(330)

    def set_data(self, days: list[DayInfo], now: float, overlay: list[DayInfo] | None = None):
        self.days, self.now, self.overlay = days, now, overlay
        self.calendar = len(days) <= 3
        self.setMinimumHeight(620 if self.calendar else 330)
        self.update()

    # ------------------------------------------------------------ helpers
    @property
    def _texts(self):
        return PLAN_TEXT if self.mode == "plan" else KIND_TEXT

    def _title(self, s: Segment) -> str:
        return s.note or self._texts[s.kind][0]

    @staticmethod
    def _range(s: Segment, d: DayInfo) -> str:
        end = "24:00" if s.end >= d.end - 1 else hhmm(s.end)
        return f"{hhmm(s.start)}–{end}"

    def _geom(self):
        if self.calendar:
            r = QRectF(58, 70, max(10, self.width() - 58 - 10), max(10, self.height() - 70 - 10))
        else:
            r = QRectF(58, 12, max(10, self.width() - 58 - 12), max(10, self.height() - 12 - 44))
        return r, r.width() / max(1, len(self.days))

    def _col(self, i: int, r: QRectF, slot: float) -> QRectF:
        if self.calendar:
            return QRectF(r.left() + slot * i + 5, r.top(), slot - 10, r.height())
        w = min(58.0, slot * 0.62)
        cx = r.left() + slot * (i + 0.5)
        return QRectF(cx - w / 2, r.top(), w, r.height())

    def _fill_segment(self, p: QPainter, rect: QRectF, s: Segment):
        color = {"grid": GREEN, "outage": BLANK, "maybe": GREEN, "nodata": NODATA}[s.kind]
        p.fillRect(rect, QColor(color))

    def _seg_rect(self, d: DayInfo, col: QRectF, s: Segment, inset: float = 0.0) -> QRectF:
        span = d.end - d.start
        y0 = col.top() + (s.start - d.start) / span * col.height()
        y1 = col.top() + (s.end - d.start) / span * col.height()
        return QRectF(col.left() + inset, y0 + inset, col.width() - 2 * inset, max(2.0, y1 - y0 - 2 * inset))

    def _draw_outline(self, p: QPainter, rect: QRectF, pen: QPen, radius: float = 6):
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, min(radius, rect.height() / 2), min(radius, rect.height() / 2))

    def _draw_overlay(self, p: QPainter, i: int, col: QRectF):
        """Scheduled outages as orange dashed outlines on top of what really happened."""
        if not self.overlay or i >= len(self.overlay):
            return
        d = self.overlay[i]
        for s in d.segments:
            pen = _outline(s.kind)
            if pen is not None:
                self._draw_outline(p, self._seg_rect(d, col, s, 2.0), pen)

    # ------------------------------------------------------------ painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        (self._paint_calendar if self.calendar else self._paint_columns)(p)
        self._paint_bubble(p)

    def _paint_columns(self, p: QPainter):
        r, slot = self._geom()
        small = QFont(self.font())
        small.setPointSize(8)
        p.setFont(small)
        for label, frac in (("00:00", 0), ("06:00", .25), ("12:00", .5), ("18:00", .75), ("23:59", 1)):
            y = r.top() + frac * r.height()
            p.setPen(QPen(QColor(GRID), 1, Qt.DashLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, y - 9, r.left() - 8, 18), Qt.AlignRight | Qt.AlignVCenter, label)
        hov_i = self._hover[0] if self._hover else -1
        hov_seg = self._hover[1] if self._hover else None
        for i, d in enumerate(self.days):
            col = self._col(i, r, slot)
            path = QPainterPath()
            path.addRoundedRect(col, 8, 8)
            p.save()
            p.setClipPath(path)
            for s in d.segments:
                self._fill_segment(p, self._seg_rect(d, col, s), s)
            if hov_seg is not None and i == hov_i:
                p.fillRect(self._seg_rect(d, col, hov_seg), QColor(255, 255, 255, 38))
            p.restore()
            if self.mode == "plan":                              # planned outages: orange dashed outline, no fill
                for s in d.segments:
                    pen = _outline(s.kind)
                    if pen is not None:
                        self._draw_outline(p, self._seg_rect(d, col, s, 1.5), pen, 5)
            self._draw_overlay(p, i, col)
            p.setPen(QPen(QColor("#4a505c" if i == hov_i else "#2f343d"), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(col, 8, 8)
            dt = datetime.fromtimestamp(d.start)
            f = QFont(self.font())
            f.setPointSize(9)
            f.setBold(i == hov_i)
            p.setFont(f)
            p.setPen(QColor(TEXT if i == hov_i else MUTED))
            p.drawText(QRectF(col.center().x() - slot / 2, r.bottom() + 8, slot, 16), Qt.AlignCenter, dt.strftime("%a"))
            p.setFont(small)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(col.center().x() - slot / 2, r.bottom() + 24, slot, 14), Qt.AlignCenter, dt.strftime("%d.%m"))

    def _paint_calendar(self, p: QPainter):
        r, slot = self._geom()
        hour_h = r.height() / 24
        step = 1 if hour_h >= 26 else (2 if hour_h >= 15 else 3)
        small = QFont(self.font())
        small.setPointSize(8)
        p.setFont(small)
        for h in range(0, 25):
            y = r.top() + h * hour_h
            p.setPen(QPen(QColor("#262a31"), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            if h < 24 and h % step == 0:
                p.setPen(QColor(MUTED))
                p.drawText(QRectF(0, y - 8, r.left() - 8, 16), Qt.AlignRight | Qt.AlignVCenter, f"{h:02d}:00")
        for i in range(len(self.days) + 1):
            x = r.left() + slot * i
            p.setPen(QPen(QColor("#262a31"), 1))
            p.drawLine(QPointF(x, r.top() - 8), QPointF(x, r.bottom()))
        hov_i = self._hover[0] if self._hover else -1
        hov_seg = self._hover[1] if self._hover else None
        today = datetime.now().date()
        for i, d in enumerate(self.days):
            col = self._col(i, r, slot)
            dt = datetime.fromtimestamp(d.start)
            p.setFont(small)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(col.left(), 4, col.width(), 16), Qt.AlignCenter, dt.strftime("%a").upper())
            big = QFont(self.font())
            big.setPointSize(15)
            circle = QRectF(col.center().x() - 20, 22, 40, 40)
            if dt.date() == today:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(GREEN))
                p.drawEllipse(circle)
            p.setFont(big)
            p.setPen(QColor("#06130c" if dt.date() == today else TEXT))
            p.drawText(circle, Qt.AlignCenter, str(dt.day))
            for s in d.segments:
                rect = self._seg_rect(d, col, s, 0.0)
                rect.adjust(0, 1, 0, -1)
                path = QPainterPath()
                path.addRoundedRect(rect, min(8, rect.height() / 2), min(8, rect.height() / 2))
                p.save()
                p.setClipPath(path)
                self._fill_segment(p, rect, s)
                p.restore()
                pen = None
                if self.mode == "plan":
                    pen = _outline(s.kind)
                elif s.kind == "outage":                       # real outage: blank block with a quiet dashed border
                    pen = QPen(QColor("#5a606c"), 1.2)
                    pen.setDashPattern([3.0, 3.0])
                if pen is not None:
                    self._draw_outline(p, rect.adjusted(0.8, 0.8, -0.8, -0.8), pen, 8)
                if hov_seg is s and i == hov_i:
                    p.setPen(QPen(QColor("#ffffff"), 1.6))
                    p.setBrush(Qt.NoBrush)
                    p.drawPath(path)
                self._block_text(p, rect, s, d)
            self._draw_overlay(p, i, col)
            if d.start <= self.now < d.end:   # "now" line like a calendar
                span = d.end - d.start
                y = col.top() + (self.now - d.start) / span * col.height()
                p.setPen(QPen(QColor("#ef4444"), 1.6))
                p.drawLine(QPointF(col.left() - 4, y), QPointF(col.right(), y))
                p.setBrush(QColor("#ef4444"))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(col.left() - 4, y), 4, 4)

    def _block_text(self, p: QPainter, rect: QRectF, s: Segment, d: DayInfo):
        if rect.height() < 18 or rect.width() < 70:
            return
        f = QFont(self.font())
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        color = self._texts[s.kind][1]
        p.setPen(QColor("#06260f" if s.kind in ("grid", "maybe") and (self.mode == "real" or s.kind == "grid") else
                        (color if s.kind != "nodata" else MUTED)))
        when = self._range(s, d)
        extra = ""
        if self.mode == "real" and s.kind != "nodata":
            extra = f" · {'~' if s.guessed else ''}{fmt_energy(s.out_kwh)}"
            if s.battery(True):
                extra += f" · {s.battery(True)}"
        inner = rect.adjusted(9, 4, -6, -2)
        if rect.height() >= 42:
            p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, self._title(s))
            f.setBold(False)
            f.setPointSize(8)
            p.setFont(f)
            p.drawText(QRectF(inner.left(), inner.top() + 16, inner.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, when + extra)
        else:
            f.setPointSize(8)
            p.setFont(f)
            p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 16), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{self._title(s)}  {when}")

    def _paint_bubble(self, p: QPainter):
        if not self._hover or self._hover[1] is None:
            return
        hi, s, pos, sched = self._hover
        d = self.days[hi]
        name, color = self._texts[s.kind]
        lines = [(s.note or name, color), (self._range(s, d), TEXT)]
        if self.mode == "real" and s.est_seconds > 1:
            lines.append((f"{fmt_hm(s.seconds)} total / {fmt_hm(s.est_seconds)} estimated", TEXT))
        else:
            lines.append((fmt_hm(s.seconds), MUTED))
        if self.mode == "real":
            if s.kind != "nodata":
                lines.append((f"Power used: {'~' if s.guessed else ''}{fmt_energy(s.out_kwh)}", MUTED))
                if s.battery():
                    lines.append((s.battery(), MUTED))
                if s.gap_from is not None:
                    lines.append((f"Was {round(s.gap_from)}% before; recharged while not recorded", MUTED))
            else:
                lines.append(("Nothing was recorded (app off or unit offline)", MUTED))
        elif s.detail:
            lines.append((s.detail, MUTED))
        if sched is not None and sched.kind in ("outage", "maybe"):
            lines.append((f"Schedule: {PLAN_TEXT[sched.kind][0].lower()} {hhmm(sched.start)}–{hhmm(sched.end)}", ORANGE))
        elif self.overlay is not None and self.mode == "real" and s.kind == "outage":
            lines.append(("Schedule: no outage planned", MUTED))
        f = QFont(self.font())
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = max(fm.horizontalAdvance(t) for t, _ in lines) + 26
        h = len(lines) * 19 + 14
        bx = pos.x() + 16 if pos.x() + 16 + w < self.width() else pos.x() - 16 - w
        by = max(2, min(pos.y() - h / 2, self.height() - h - 2))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(CARD2))
        p.drawRoundedRect(QRectF(bx, by, w, h), 12, 12)
        for k, (txt, col) in enumerate(lines):
            p.setPen(QColor(col))
            p.drawText(QRectF(bx + 13, by + 7 + k * 19, w - 16, 19), Qt.AlignLeft | Qt.AlignVCenter, txt)

    # ------------------------------------------------------------ interaction
    def mouseMoveEvent(self, e):
        r, slot = self._geom()
        pos = e.position()
        i = int((pos.x() - r.left()) // slot) if slot else -1
        seg = sched = None
        if 0 <= i < len(self.days) and r.top() <= pos.y() <= r.bottom():
            col = self._col(i, r, slot)
            if col.left() - 4 <= pos.x() <= col.right() + 4:
                d = self.days[i]
                t = d.start + (pos.y() - r.top()) / r.height() * (d.end - d.start)
                seg = next((s for s in d.segments if s.start <= t <= s.end), None)
                if self.overlay and i < len(self.overlay):
                    sched = next((s for s in self.overlay[i].segments if s.start <= t <= s.end), None)
        self._hover = (i, seg, pos, sched) if seg is not None else None
        self.update()

    def leaveEvent(self, _):
        self._hover = None
        self.update()


# ====================================================================== cards
def _header(card: QFrame, caption: str):
    """Common card header: caption, big value + sub text on the left, controls on the right. Returns the widgets."""
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(8)
    head = QHBoxLayout()
    left = QVBoxLayout()
    lbl_caption = QLabel(caption)
    lbl_caption.setObjectName("muted")
    vrow = QHBoxLayout()
    lbl_value = QLabel("--")
    lbl_value.setObjectName("bigvalue")
    lbl_sub = QLabel("")
    lbl_sub.setObjectName("muted")
    vrow.addWidget(lbl_value)
    vrow.addWidget(lbl_sub)
    vrow.addStretch()
    left.addWidget(lbl_caption)
    left.addLayout(vrow)
    head.addLayout(left, 1)
    return lay, head, lbl_caption, lbl_value, lbl_sub


def _day_infos(first: datetime, n: int, segs: list[Segment]) -> list[DayInfo]:
    out = []
    for k in range(n):
        d0 = first + timedelta(days=k)
        t0, t1 = d0.timestamp(), (d0 + timedelta(days=1)).timestamp()
        out.append(DayInfo(t0, t1, slice_segments(segs, t0, t1)))
    return out


class OutageCard(QFrame):
    """What really happened. Optionally overlays the planned outages (orange dashed outlines) for comparison."""

    def __init__(self, ctrl: Controller):
        super().__init__()
        self.setObjectName("card")
        self.ctrl = ctrl
        lay, head, self.lbl_caption, self.lbl_value, self.lbl_sub = _header(self, "Time without electricity")
        self.cb_overlay = QCheckBox("Compare with schedule")
        self.cb_overlay.setToolTip("Draw the planned outages (orange dashed outlines) over the real ones")
        self.cb_overlay.toggled.connect(lambda *_: self.refresh())
        self.cmb = QComboBox()
        self.cmb.setObjectName("pill")
        self.cmb.addItems(list(RANGES))
        self.cmb.setCurrentText("7 days")
        self.cmb.currentTextChanged.connect(lambda *_: self.refresh())
        controls = QHBoxLayout()                    # checkbox + range share one row and one centre line
        controls.setSpacing(14)
        controls.addWidget(self.cb_overlay, 0, Qt.AlignVCenter)
        controls.addWidget(self.cmb, 0, Qt.AlignVCenter)
        head.addLayout(controls, 0)
        lay.addLayout(head)
        self.legend = QLabel("")
        self.legend.setObjectName("muted")
        lay.addWidget(self.legend)
        self.chart = OutageTimeline("real")
        lay.addWidget(self.chart, 1)

    def _legend(self, overlay: bool) -> str:
        s = (f'<span style="color:{GREEN}">&#9632;</span> Electricity &nbsp;&nbsp; '
             f'<span style="color:#8b93a1">&#9633; No electricity</span> &nbsp;&nbsp; '
             f'<span style="color:{NODATA}">&#9632;</span> No data')
        if overlay:
            s += f' &nbsp;&nbsp; <span style="color:{ORANGE}">&#9633; Planned outage (schedule)</span>'
        return s

    def refresh(self):
        now = time.time()
        ndays = RANGES[self.cmb.currentText()]
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        first = today - timedelta(days=ndays - 1)
        end = today + timedelta(days=1)
        rows = self.ctrl.history.range(first.timestamp() - 300)
        # whole range at once so estimates can use data on either side (also across midnight)
        whole = link_battery(merge_same_kind(fill_gaps(grid_segments(rows, first.timestamp(), end.timestamp(), now))))
        days = _day_infos(first, ndays, whole)
        configured = self.ctrl.schedule_configured
        self.cb_overlay.setEnabled(configured)
        if not configured:
            self.cb_overlay.setToolTip("Choose your region and group in Settings > Outage schedule first")
        overlay = None
        planned = None
        if self.cb_overlay.isChecked() and configured:
            exp = self.ctrl.expected_segments(first.timestamp(), end.timestamp())
            overlay = _day_infos(first, ndays, exp)
            planned = seconds_of(exp, "outage")
        self.chart.set_data(days, now, overlay)
        self.legend.setText(self._legend(overlay is not None))
        total = outage_seconds(whole)
        est = outage_seconds(whole, only_guessed=True)
        count = outage_count(whole)
        self.lbl_caption.setText(f"Time without electricity - {self.cmb.currentText()}")
        self.lbl_value.setText(("~" if est > 0 else "") + fmt_hm(total) if total > 0 else "None")
        sub = f"{count} outage{'s' if count != 1 else ''}" if count else "no outages recorded"
        if est > 0:
            sub += f" · {fmt_hm(est)} estimated"
        if planned is not None:
            sub += f" · schedule said {fmt_hm(planned)}"
        self.lbl_sub.setText(sub)


class ExpectedOutageCard(QFrame):
    """What the schedule says: planned outages for the chosen region and group (orange dashed outlines, no fill)."""

    def __init__(self, ctrl: Controller):
        super().__init__()
        self.setObjectName("card")
        self.ctrl = ctrl
        lay, head, self.lbl_caption, self.lbl_value, self.lbl_sub = _header(self, "Expected outages (schedule)")
        self.cmb = QComboBox()
        self.cmb.setObjectName("pill")
        self.cmb.addItems(list(EXPECTED_RANGES))
        self.cmb.setCurrentText("Today + tomorrow")
        self.cmb.currentTextChanged.connect(lambda *_: self.refresh())
        head.addWidget(self.cmb, 0)
        lay.addLayout(head)
        self.legend = QLabel(
            f'<span style="color:{GREEN}">&#9632;</span> Power on &nbsp;&nbsp; '
            f'<span style="color:{ORANGE}">&#9633; Planned outage</span> &nbsp;&nbsp; '
            f'<span style="color:{ORANGE}">&#9676; Possible outage</span> &nbsp;&nbsp; '
            f'<span style="color:{NODATA}">&#9632;</span> No schedule (not fetched / not published / not saved)')
        self.legend.setObjectName("muted")
        lay.addWidget(self.legend)
        self.hint = QLabel("Choose your region and queue (group) in Settings > Outage schedule.")
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.chart = OutageTimeline("plan")
        lay.addWidget(self.chart, 1)

    def refresh(self):
        c = self.ctrl
        configured = c.schedule_configured
        self.hint.setVisible(not configured)
        self.chart.setVisible(configured)
        self.legend.setVisible(configured)
        if not configured:
            self.lbl_value.setText("--")
            self.lbl_sub.setText("not configured")
            return
        back, total_days = EXPECTED_RANGES[self.cmb.currentText()]
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        first = today - timedelta(days=back)
        end = first + timedelta(days=total_days)
        segs = c.expected_segments(first.timestamp(), end.timestamp())
        days = _day_infos(first, total_days, segs)
        for d in days:           # not fetched yet / fetch failed / not published yet / not saved while the app was off
            for s in d.segments:
                if s.kind == "nodata":
                    s.note, s.detail = c.schedule_note(d.start, today.timestamp())
        self.chart.set_data(days, time.time())
        planned, maybe, count = seconds_of(segs, "outage"), seconds_of(segs, "maybe"), count_of(segs, "outage")
        saved = seconds_of(segs, "nodata") < (end - first).total_seconds()
        self.lbl_caption.setText(f"Expected without electricity - {self.cmb.currentText()} · group {c.settings.outage_group}")
        self.lbl_value.setText(fmt_hm(planned) if planned > 0 else "None")
        if not saved:
            note = next((s.note for d in days for s in d.segments if s.kind == "nodata" and s.note), "no schedule")
            self.lbl_sub.setText(note.lower())
            return
        sub = f"{count} planned outage{'s' if count != 1 else ''}" if count else "no outages planned"
        if maybe > 0:
            sub += f" · +{fmt_hm(maybe)} possible"
        missing = sorted({s.note for d in days for s in d.segments if s.kind == "nodata" and s.note})
        if missing:
            sub += f" · " + ", ".join(m.lower() for m in missing)        # e.g. "not published yet"
        self.lbl_sub.setText(sub)
