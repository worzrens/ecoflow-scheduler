"""Small reusable controls for the Control tab: switch, stepper, day chips, schedule row, info icon."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, QTime, QTimer, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
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


class ActionButton(QPushButton):
    """The one button style for actions. Every new button should be this.

    kind "primary" = green chip, "ghost" = outlined. Built-in feedback, so callers never hand-roll it:
      flash(ok)      - drawn check mark (or cross when ok=False) in place of the label for ~1 s
      begin()/finish(ok) - for slow actions: dots while running, then the flash
      set_done(text) - "already done" state: greyed out with `text` until set_done(None)
      set_enabled_look - disabled buttons are greyed (nothing to do)
    `on_click(fn)` wires a function: no exception -> check mark, OSError/ValueError -> cross + tooltip with the message;
    a function returning False means 'started something slow' and the caller ends it with finish()."""

    def __init__(self, text: str, kind: str = "ghost", on_click=None, min_width: int = 0):
        super().__init__()
        self._label = text.replace("&&", "&")
        self.kind = kind
        self._base_tip = ""
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(max(min_width, 180 if kind == "primary" else 0), 40 if kind == "primary" else 34)
        self._mode = ""            # "", "ok", "fail", "busy"
        self._done: str | None = None
        self._progress = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(420)
        self._anim.valueChanged.connect(self._on_progress)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._finish)
        self._dots = QTimer(self)
        self._dots.timeout.connect(self._tick)
        self._tickn = 0
        if on_click is not None:
            self.clicked.connect(lambda *_: self._invoke(on_click))

    # ---- sizing / text
    def setText(self, text: str):
        self._label = text.replace("&&", "&")
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._label

    def sizeHint(self) -> QSize:
        f = QFont(self.font())
        f.setBold(self.kind == "primary")
        w = QFontMetrics(f).horizontalAdvance(self._label) + 36
        return QSize(max(w, self.minimumWidth()), self.minimumHeight())

    # ---- feedback
    def _invoke(self, fn):
        try:
            r = fn()
        except (OSError, ValueError) as e:
            self.flash(False, str(e))
            return
        if r is False:
            self.begin()
        else:
            self.flash(True)

    def is_playing(self) -> bool:
        return self._mode in ("ok", "fail")

    def flash(self, ok: bool = True, message: str = ""):
        self._dots.stop()
        self._mode = "ok" if ok else "fail"
        self._progress = 0.0
        self._anim.stop()
        self._anim.start()
        self._hold.start(1300 if ok else 2200)
        if message:
            self.setToolTip(message)
        self.update()

    play_success = flash

    def begin(self):
        self._mode, self._tickn = "busy", 0
        self._hold.stop()
        self._dots.start(280)
        self.update()

    def finish(self, ok: bool = True, message: str = ""):
        if self._mode == "busy":
            self.flash(ok, message)

    def set_done(self, text: str | None):
        self._done = text
        self.update()

    def _tick(self):
        self._tickn += 1
        self.update()

    def _on_progress(self, v):
        self._progress = float(v)
        self.update()

    def _finish(self):
        self._mode = ""
        self.setToolTip(self._base_tip)
        self.update()

    # ---- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        primary = self.kind == "primary"
        showing = self._mode in ("ok", "fail")
        active = (self.isEnabled() and self._done is None) or showing
        fail = self._mode == "fail"
        hover = active and self.underMouse() and not showing
        if primary:
            bg = QColor("#e5534b" if fail else (GREEN if active else "#20242b"))
            if hover:
                bg = bg.lighter(112)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            fg = QColor("#06130c" if active else "#5b6270")
            if fail:
                fg = QColor("#1a0605")
        else:
            edge = QColor("#e5534b" if fail else (GREEN if self._mode == "ok" else ("#3a3f4a" if active else "#2a2e36")))
            p.setPen(QPen(edge, 1))
            p.setBrush(QColor("#20242b") if hover else Qt.NoBrush)
            fg = QColor("#e5534b" if fail else (GREEN if self._mode == "ok" else ("#d1d5db" if active else "#5b6270")))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if showing:
            self._draw_mark(p, r, fg, fail)
            return
        f = QFont(self.font())
        f.setBold(primary)
        p.setFont(f)
        p.setPen(fg)
        text = self._label
        if self._mode == "busy":
            text = "." * (self._tickn % 3 + 1)
        elif self._done is not None:
            text = self._done
        p.drawText(r, Qt.AlignCenter, text)

    def _draw_mark(self, p: QPainter, r: QRectF, color: QColor, fail: bool):
        pts = ([QPointF(-7, -7), QPointF(7, 7), QPointF(7, -7), QPointF(-7, 7)] if fail else
               [QPointF(-10, 0), QPointF(-3.5, 7), QPointF(10, -7)])
        legs = [(pts[0], pts[1])] + ([(pts[2], pts[3])] if fail else [(pts[1], pts[2])])
        total = sum(math.dist((a.x(), a.y()), (b.x(), b.y())) for a, b in legs)
        left = self._progress * total
        c = r.center()
        p.setPen(QPen(color, 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for a, b in legs:
            ln = math.dist((a.x(), a.y()), (b.x(), b.y()))
            if left <= 0:
                break
            f = min(1.0, left / ln)
            p.drawLine(c + a, c + QPointF(a.x() + (b.x() - a.x()) * f, a.y() + (b.y() - a.y()) * f))
            left -= ln


class SaveButton(ActionButton):
    """Green primary chip; greyed out while there is nothing to save, check mark after a click."""

    def __init__(self, text: str):
        super().__init__(text, "primary")
