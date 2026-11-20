"""System tray icon with live tooltip."""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtCore import QPointF
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .controller import Controller
from .util import fmt_duration, soc_color

NAME = "EcoFlow DELTA Pro"


def app_pixmap(size: int = 256) -> QPixmap:
    """Generic app icon (window, taskbar, exe): green rounded square with a lightning bolt."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    k = size / 64.0
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#34f09a"))
    g.setColorAt(1, QColor("#119a58"))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(3 * k, 3 * k, 58 * k, 58 * k), 15 * k, 15 * k)
    bolt = QPainterPath()
    pts = [(36, 9), (17, 36), (29, 36), (25, 55), (47, 26), (34, 26)]
    bolt.moveTo(QPointF(pts[0][0] * k, pts[0][1] * k))
    for x, y in pts[1:]:
        bolt.lineTo(QPointF(x * k, y * k))
    bolt.closeSubpath()
    p.setBrush(QColor("#06130c"))
    p.drawPath(bolt)
    p.end()
    return pm


def make_app_icon() -> QIcon:
    return QIcon(app_pixmap(256))


def make_icon(soc: float | None, live: bool) -> QIcon:
    """Tray icon: the battery % in big dark bold digits on a bright, battery-coloured square (readable at 16-24 px).
    Greyed (light digits on grey) when the unit is offline."""
    size = 128
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    on = soc is not None and live
    p.setBrush(QColor(soc_color(soc) if on else "#6b7280"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), 22, 22)
    text = f"{soc:.0f}" if soc is not None else "?"
    f = QFont()
    f.setFamilies(["Segoe UI", "SF Pro Text", "Helvetica Neue", "Arial"])
    f.setBold(True)
    f.setPixelSize({1: 96, 2: 88, 3: 62}.get(len(text), 62))   # fill the square: "100" is the narrowest fit
    f.setStretch(QFont.Condensed if len(text) == 3 else QFont.Unstretched)
    p.setFont(f)
    p.setPen(QColor("#06130c") if on else QColor("#f3f4f6"))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, text)
    p.end()
    return QIcon(pm)


def tooltip_text(c: Controller) -> str:
    t = c.last
    if not t:
        return f"{NAME}\n{c.status_text}"
    if not c.fresh:
        return f"{NAME}\nOffline - last seen {time.strftime('%H:%M', time.localtime(t.ts))}, battery {t.soc:.0f}%"
    line = f"Battery {t.soc:.0f}% | Out {t.out_w:.0f} W"
    if t.charging:
        line += f"\nCharging +{t.in_w:.0f} W | full in {fmt_duration(t.chg_min)}"
    else:
        line += f" | ~{fmt_duration(t.dsg_min)} left"
    status = {"charging": "Charging", "discharging": "Discharging", "full": "Fully charged", "ongrid": "On grid"}.get(
        c.power_state or "")
    if status and c.state_since_ts:
        verb = "since" if c.power_state in ("full", "ongrid") else "since"
        extra = " - power outage" if (c.power_state == "discharging" and not t.grid) else ""
        line += f"\n{status} {verb} {time.strftime('%H:%M', time.localtime(c.state_since_ts))}{extra}"
    return f"{NAME}\n{line}"


class Tray(QSystemTrayIcon):
    def __init__(self, ctrl: Controller, window):
        super().__init__()
        self.ctrl, self.window = ctrl, window
        self.setIcon(make_icon(None, False))
        menu = QMenu()
        open_a = QAction("Open", menu)
        open_a.triggered.connect(self.show_window)
        quit_a = QAction("Quit", menu)
        quit_a.triggered.connect(self.quit)
        self._info: list[QAction] = []
        if sys.platform == "darwin":   # menu-bar icons have no tooltip on macOS -> show the same text at the top of the menu
            for _ in range(4):
                a = QAction("", menu)
                a.setEnabled(False)
                menu.addAction(a)
                self._info.append(a)
            menu.addSeparator()
        menu.addAction(open_a)
        menu.addSeparator()
        menu.addAction(quit_a)
        self.setContextMenu(menu)
        self._menu = menu
        self.activated.connect(self._activated)
        ctrl.telemetry.connect(lambda *_: self.refresh())
        ctrl.online.connect(lambda *_: self.refresh())
        ctrl.status.connect(lambda *_: self.refresh())
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(15_000)
        self.refresh()
        self.show()

    def refresh(self):
        t = self.ctrl.last
        self.setIcon(make_icon(t.soc if t else None, self.ctrl.fresh))
        tip = tooltip_text(self.ctrl)
        self.setToolTip(tip)
        lines = tip.splitlines()
        for i, a in enumerate(self._info):
            a.setText(lines[i] if i < len(lines) else "")
            a.setVisible(i < len(lines))

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()

    def show_window(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def quit(self):
        self.window.allow_close = True
        self.hide()
        QApplication.quit()
