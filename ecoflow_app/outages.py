"""Power-outage views.

7 days  -> one full-height 24 h box per day (columns).
1-3 days -> calendar layout: hour grid, wide day columns, event-like blocks with text.
Green = grid power, blank = outage, grey = no data; estimates from neighbouring data are merged into the zones.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .analytics import fmt_energy
from .charts import CARD, CARD2, GREEN, GRID, MUTED, TEXT
from .controller import Controller
from .power import (MAX_GAP, Segment, fill_gaps, grid_segments, merge_same_kind, outage_count, outage_seconds,
                    slice_segments)

BLANK = CARD                # "no electricity" is drawn as the empty card colour
NODATA = "#2c3038"
OUTAGE_TEXT = "#f87171"
RANGES = {"Today": 1, "3 days": 3, "7 days": 7}


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


def _title(s: Segment) -> str:
    return KIND_TEXT[s.kind][0]


class OutageTimeline(QWidget):
    def __init__(self):
        super().__init__()
        self.days: list[DayInfo] = []
        self.now = time.time()
        self.calendar = False
        self._hover: tuple[int, Segment | None, QPointF] | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(330)

    def set_data(self, days: list[DayInfo], now: float):
        self.days, self.now = days, now
        self.calendar = len(days) <= 3
        self.setMinimumHeight(620 if self.calendar else 330)
        self.update()

    # ------------------------------------------------------------ geometry
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

    @staticmethod
    def _fill_segment(p: QPainter, rect: QRectF, s: Segment):
        p.fillRect(rect, QColor({"grid": GREEN, "outage": BLANK, "nodata": NODATA}[s.kind]))

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
            span = d.end - d.start
            for s in d.segments:
                y0 = col.top() + (s.start - d.start) / span * col.height()
                y1 = col.top() + (s.end - d.start) / span * col.height()
                self._fill_segment(p, QRectF(col.left(), y0, col.width(), max(1.0, y1 - y0)), s)
            if hov_seg is not None and i == hov_i:
                y0 = col.top() + (hov_seg.start - d.start) / span * col.height()
                y1 = col.top() + (hov_seg.end - d.start) / span * col.height()
                p.fillRect(QRectF(col.left(), y0, col.width(), max(2.0, y1 - y0)), QColor(255, 255, 255, 38))
            p.restore()
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
            span = d.end - d.start
            for s in d.segments:
                y0 = col.top() + (s.start - d.start) / span * col.height() + 1
                y1 = col.top() + (s.end - d.start) / span * col.height() - 1
                rect = QRectF(col.left(), y0, col.width(), max(2.0, y1 - y0))
                path = QPainterPath()
                path.addRoundedRect(rect, min(8, rect.height() / 2), min(8, rect.height() / 2))
                p.save()
                p.setClipPath(path)
                self._fill_segment(p, rect, s)
                p.restore()
                if s.kind == "outage":
                    pen = QPen(QColor("#5a606c"), 1.2)
                    pen.setDashPattern([3.0, 3.0])
                    p.setPen(pen)
                    p.setBrush(Qt.NoBrush)
                    p.drawPath(path)
                if hov_seg is s and i == hov_i:
                    p.setPen(QPen(QColor("#ffffff"), 1.6))
                    p.setBrush(Qt.NoBrush)
                    p.drawPath(path)
                self._block_text(p, rect, s)
            if d.start <= self.now < d.end:   # "now" line like a calendar
                y = col.top() + (self.now - d.start) / span * col.height()
                p.setPen(QPen(QColor("#ef4444"), 1.6))
                p.drawLine(QPointF(col.left() - 4, y), QPointF(col.right(), y))
                p.setBrush(QColor("#ef4444"))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(col.left() - 4, y), 4, 4)

    def _block_text(self, p: QPainter, rect: QRectF, s: Segment):
        if rect.height() < 18 or rect.width() < 70:
            return
        f = QFont(self.font())
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        dark = s.kind == "grid"
        p.setPen(QColor("#06260f" if dark else KIND_TEXT[s.kind][1] if s.kind != "nodata" else MUTED))
        when = f"{hhmm(s.start)}–{hhmm(s.end)}"
        extra = f" · {'~' if s.guessed else ''}{fmt_energy(s.out_kwh)}" if s.kind != "nodata" else ""
        inner = rect.adjusted(9, 4, -6, -2)
        if rect.height() >= 42:
            p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, _title(s))
            f.setBold(False)
            f.setPointSize(8)
            p.setFont(f)
            p.drawText(QRectF(inner.left(), inner.top() + 16, inner.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, when + extra)
        else:
            f.setPointSize(8)
            p.setFont(f)
            p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 16), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{_title(s)}  {when}")

    def _paint_bubble(self, p: QPainter):
        if not self._hover or self._hover[1] is None:
            return
        _, s, pos = self._hover
        name, color = KIND_TEXT[s.kind]
        lines = [(_title(s), color), (f"{hhmm(s.start)}\u2013{hhmm(s.end)}", TEXT)]
        if s.est_seconds > 1:
            lines.append((f"{fmt_hm(s.seconds)} total / {fmt_hm(s.est_seconds)} estimated", TEXT))
        else:
            lines.append((fmt_hm(s.seconds), MUTED))
        if s.kind != "nodata":
            lines.append((f"Power used: {'~' if s.guessed else ''}{fmt_energy(s.out_kwh)}", MUTED))
        else:
            lines.append(("Nothing was recorded (app off or unit offline)", MUTED))
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
        seg = None
        if 0 <= i < len(self.days) and r.top() <= pos.y() <= r.bottom():
            col = self._col(i, r, slot)
            if col.left() - 4 <= pos.x() <= col.right() + 4:
                d = self.days[i]
                t = d.start + (pos.y() - r.top()) / r.height() * (d.end - d.start)
                seg = next((s for s in d.segments if s.start <= t <= s.end), None)
        self._hover = (i, seg, pos) if seg is not None else None
        self.update()

    def leaveEvent(self, _):
        self._hover = None
        self.update()


class OutageCard(QFrame):
    def __init__(self, ctrl: Controller):
        super().__init__()
        self.setObjectName("card")
        self.ctrl = ctrl
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        head = QHBoxLayout()
        left = QVBoxLayout()
        self.lbl_caption = QLabel("Time without electricity")
        self.lbl_caption.setObjectName("muted")
        vrow = QHBoxLayout()
        self.lbl_value = QLabel("--")
        self.lbl_value.setObjectName("bigvalue")
        self.lbl_sub = QLabel("")
        self.lbl_sub.setObjectName("muted")
        vrow.addWidget(self.lbl_value)
        vrow.addWidget(self.lbl_sub)
        vrow.addStretch()
        left.addWidget(self.lbl_caption)
        left.addLayout(vrow)
        head.addLayout(left, 1)
        self.cmb = QComboBox()
        self.cmb.setObjectName("pill")
        self.cmb.addItems(list(RANGES))
        self.cmb.setCurrentText("7 days")
        self.cmb.currentTextChanged.connect(lambda *_: self.refresh())
        head.addWidget(self.cmb, 0)
        lay.addLayout(head)
        self.legend = QLabel(
            f'<span style="color:{GREEN}">&#9632;</span> Electricity &nbsp;&nbsp; '
            f'<span style="color:#8b93a1">&#9633; No electricity</span> &nbsp;&nbsp; '
            f'<span style="color:{NODATA}">&#9632;</span> No data')
        self.legend.setObjectName("muted")
        lay.addWidget(self.legend)
        self.chart = OutageTimeline()
        lay.addWidget(self.chart, 1)

    def refresh(self):
        now = time.time()
        ndays = RANGES[self.cmb.currentText()]
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        first = today - timedelta(days=ndays - 1)
        end = today + timedelta(days=1)
        rows = self.ctrl.history.range(first.timestamp() - 300)
        # whole range at once so estimates can use data on either side (also across midnight)
        whole = merge_same_kind(fill_gaps(grid_segments(rows, first.timestamp(), end.timestamp(), now)))
        days = []
        for k in range(ndays):
            d0 = first + timedelta(days=k)
            t0, t1 = d0.timestamp(), (d0 + timedelta(days=1)).timestamp()
            days.append(DayInfo(t0, t1, slice_segments(whole, t0, t1)))
        self.chart.set_data(days, now)
        total = outage_seconds(whole)
        est = outage_seconds(whole, only_guessed=True)
        count = outage_count(whole)
        self.lbl_caption.setText(f"Time without electricity - {self.cmb.currentText()}")
        self.lbl_value.setText(("~" if est > 0 else "") + fmt_hm(total) if total > 0 else "None")
        sub = f"{count} outage{'s' if count != 1 else ''}" if count else "no outages recorded"
        if est > 0:
            sub += f" · {fmt_hm(est)} estimated"
        self.lbl_sub.setText(sub)
