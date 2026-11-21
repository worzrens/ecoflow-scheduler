"""Small reusable controls for the Control tab: switch, stepper, day chips, schedule row, info icon."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, QTime, QTimer, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QTimeEdit, QWidget)

from .charts import GREEN
from .layouts import FlowLayout
from .rules import DAY_NAMES, MAX_W, MIN_W, ScheduleEntry


class Switch(QAbstractButton):
    """iOS/Android style toggle."""

    def __init__(self, checked: bool = False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)

    def sizeHint(self):
        return QSize(46, 26)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(GREEN if on else "#3a3f4a"))
        p.drawRoundedRect(QRectF(0, 0, 46, 26), 13, 13)
        p.setBrush(QColor("#06130c" if on else "#9ca3af"))
        p.drawEllipse(QRectF(24 if on else 3, 3, 20, 20))


class Stepper(QWidget):
    """[-]  600 W  [+] pill."""
    valueChanged = Signal(int)

    def __init__(self, value: int, lo: int, hi: int, step: int = 50, suffix: str = " W"):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self.setObjectName("stepper")
        self.minus, self.plus = QPushButton("-"), QPushButton("+")
        for b in (self.minus, self.plus):
            b.setObjectName("round")
            b.setAutoRepeat(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(28, 28)
        self.spin = QSpinBox()
        self.spin.setObjectName("bare")
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setAlignment(Qt.AlignCenter)
        self.spin.setMinimumWidth(78)
        self.spin.setValue(max(lo, min(hi, value)))
        self.minus.clicked.connect(lambda: self.spin.stepBy(-1))
        self.plus.clicked.connect(lambda: self.spin.stepBy(1))
        self.spin.valueChanged.connect(self.valueChanged)
        lay.addWidget(self.minus)
        lay.addWidget(self.spin)
        lay.addWidget(self.plus)

    def value(self) -> int:
        return self.spin.value()

    def setValue(self, v: int):
        self.spin.setValue(v)


def watts_stepper(value: int = 1000) -> Stepper:
    return Stepper(value, MIN_W, MAX_W, 50, " W")


class InfoIcon(QLabel):
    """Round '?' badge; hover shows a rich-text tooltip."""

    def __init__(self):
        super().__init__("?")
        self.setObjectName("info")
        self.setFixedSize(18, 18)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.WhatsThisCursor)


class ScheduleRow(QFrame):
    """Switch + times | day chips | power + remove; groups wrap onto new lines in narrow windows."""
    removed = Signal(object)
    changed = Signal()

    def __init__(self, e: ScheduleEntry):
        super().__init__()
        self.setObjectName("row")
        flow = FlowLayout(self, hspacing=18, vspacing=10)
        flow.setContentsMargins(14, 10, 10, 10)

        def group(*widgets, spacing=10):
            g = QWidget()
            h = QHBoxLayout(g)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(spacing)
            for w in widgets:
                h.addWidget(w)
            return g

        self.on = Switch(e.enabled)
        self.t_from, self.t_to = QTimeEdit(QTime.fromString(e.start, "HH:mm")), QTimeEdit(QTime.fromString(e.end, "HH:mm"))
        for te in (self.t_from, self.t_to):
            te.setDisplayFormat("HH:mm")
            te.setAlignment(Qt.AlignCenter)
            te.setFixedWidth(74)
            te.setToolTip("Type the time or use the mouse wheel / arrow keys")
        arrow = QLabel("\u2192")
        arrow.setObjectName("muted")
        flow.addWidget(group(self.on, self.t_from, arrow, self.t_to))

        self.days: list[QPushButton] = []
        for i, name in enumerate(DAY_NAMES):
            b = QPushButton(name[:2])
            b.setObjectName("day")
            b.setCheckable(True)
            b.setChecked(i in e.days)
            b.setToolTip(name)
            b.setFixedSize(34, 34)
            b.setCursor(Qt.PointingHandCursor)
            self.days.append(b)
        flow.addWidget(group(*self.days, spacing=6))

        self.watts = watts_stepper(e.watts)
        rm = QPushButton("\u2715")
        rm.setObjectName("round")
        rm.setFixedSize(28, 28)
        rm.setToolTip("Remove this window")
        rm.setCursor(Qt.PointingHandCursor)
        rm.clicked.connect(lambda: self.removed.emit(self))
        flow.addWidget(group(self.watts, rm))

        for sig in (self.on.toggled, self.t_from.timeChanged, self.t_to.timeChanged, self.watts.valueChanged,
                    *[b.toggled for b in self.days]):
            sig.connect(lambda *_: self.changed.emit())

    def entry(self) -> ScheduleEntry:
        return ScheduleEntry(start=self.t_from.time().toString("HH:mm"), end=self.t_to.time().toString("HH:mm"),
                             watts=self.watts.value(), days=[i for i, b in enumerate(self.days) if b.isChecked()],
                             enabled=self.on.isChecked())


class SaveButton(QPushButton):
    """Green primary chip. Greyed out while there is nothing to save; after a click it shows an animated check mark."""

    def __init__(self, text: str):
        super().__init__()
        self._label = text.replace("&&", "&")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(180, 40)
        self._showing = False
        self._progress = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(420)
        self._anim.valueChanged.connect(self._on_progress)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._finish)

    def is_playing(self) -> bool:
        return self._showing

    def play_success(self):
        """Replace the label with a drawn check mark for about a second."""
        self._showing = True
        self._progress = 0.0
        self._anim.stop()
        self._anim.start()
        self._hold.start(1300)
        self.update()

    def _on_progress(self, v):
        self._progress = float(v)
        self.update()

    def _finish(self):
        self._showing = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        active = self.isEnabled() or self._showing
        bg = QColor(GREEN if active else "#20242b")
        if active and self.underMouse() and not self._showing:
            bg = bg.lighter(112)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        r = QRectF(self.rect())
        p.drawRoundedRect(r, 8, 8)
        if self._showing:
            pts = [QPointF(-10, 0), QPointF(-3.5, 7), QPointF(10, -7)]
            seg = [math.dist((a.x(), a.y()), (b.x(), b.y())) for a, b in zip(pts, pts[1:])]
            left = self._progress * sum(seg)
            c = r.center()
            pen = QPen(QColor("#06130c"), 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            for (a, b), ln in zip(zip(pts, pts[1:]), seg):
                if left <= 0:
                    break
                f = min(1.0, left / ln)
                p.drawLine(c + a, c + QPointF(a.x() + (b.x() - a.x()) * f, a.y() + (b.y() - a.y()) * f))
                left -= ln
            return
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#06130c" if active else "#5b6270"))
        p.drawText(r, Qt.AlignCenter, self._label)
