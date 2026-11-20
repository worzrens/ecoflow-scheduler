"""Small reusable controls for the Control tab: switch, stepper, day chips, schedule row, info icon."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, QTime, Qt, Signal
from PySide6.QtGui import QColor, QPainter
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

    def entry(self) -> ScheduleEntry:
        return ScheduleEntry(start=self.t_from.time().toString("HH:mm"), end=self.t_to.time().toString("HH:mm"),
                             watts=self.watts.value(), days=[i for i, b in enumerate(self.days) if b.isChecked()],
                             enabled=self.on.isChecked())
