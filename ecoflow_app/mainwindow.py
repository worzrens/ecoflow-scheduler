"""Main window: Dashboard, Statistics, Control, Settings (dark, rounded cards, Android-like)."""
from __future__ import annotations

import sys
import time
from copy import deepcopy
from datetime import datetime

from PySide6.QtCore import QEvent, QTime, QTimer, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from . import autostart
from .analytics import AnalyticsCard
from .api import Telemetry
from .charts import GREEN, ORANGE, BatteryBar
from .layouts import FlowLayout, ReflowScroll, SplitPage
from .outages import OutageCard
from .controller import Controller
from .rules import MAX_W, MIN_W, Dynamic, RulesConfig, ScheduleEntry, Temporary, short_reason
from .settings import Settings
from .util import fmt_duration
from .widgets import InfoIcon, ScheduleRow, Stepper, Switch, watts_stepper

DASH_RANGES = {"5 min": 300, "30 min": 1800, "1 hour": 3600, "6 hours": 6 * 3600, "24 hours": 86400,
               "7 days": 7 * 86400}
STAT_RANGES = {"24 hours": 86400, "3 days": 3 * 86400, "7 days": 7 * 86400}

STYLE = """
QWidget { background: #0e1013; color: #f3f4f6; font-size: 10pt; }
QFrame#card, QGroupBox { background: #171a1f; border: none; border-radius: 20px; }
QGroupBox { margin-top: 26px; padding: 18px 14px 12px 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 6px; top: 0px;
                   color: #8b93a1; background: transparent; }
QFrame#card QWidget, QGroupBox QWidget { background: transparent; }
QLabel { background: transparent; }
QLabel#muted { color: #8b93a1; }
QLabel#bigvalue { font-size: 24pt; font-weight: 600; }
QLabel#hero { font-size: 30pt; font-weight: 600; }
QLabel#statvalue { font-size: 26pt; font-weight: 600; }
QLabel#status { border-radius: 6px; padding: 1px 9px; font-size: 8pt; font-weight: 600; background: #20242b; color: #8b93a1; }
QLabel#statuspaused { border-radius: 6px; padding: 1px 9px; font-size: 8pt; font-weight: 600; background: #3b2a10; color: #ffa629; }
QLabel#statusok { border-radius: 6px; padding: 1px 9px; font-size: 8pt; font-weight: 600; background: #14351f; color: #2ee68a; }
QFrame#vline { background: #262a33; border: none; max-width: 1px; min-width: 1px; }
QLabel#title { font-size: 15pt; font-weight: 600; }
QTabWidget::pane { border: 0; top: 6px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: #8b93a1; padding: 7px 18px; margin-right: 6px; border-radius: 8px;
               font-weight: 600; }
QTabBar::tab:selected { background: #2ee68a; color: #06130c; }
QTabBar::tab:hover:!selected { background: #20242b; color: #d1d5db; }
QComboBox, QSpinBox, QTimeEdit, QLineEdit,
QFrame#card QComboBox, QFrame#card QSpinBox, QFrame#card QLineEdit,
QGroupBox QComboBox, QGroupBox QSpinBox, QGroupBox QTimeEdit { background: #20242b; border: none; border-radius: 8px;
                                                             padding: 6px 12px; min-height: 20px; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url(ARROW_URL); width: 10px; height: 6px; margin-right: 10px; }
QComboBox QAbstractItemView { background: #20242b; border: none; border-radius: 10px; selection-background-color: #2563eb;
                              outline: 0; padding: 4px; }
QPushButton, QFrame#card QPushButton, QGroupBox QPushButton { background: #20242b; border: none; border-radius: 8px; padding: 7px 16px; font-weight: 600; }
QPushButton:hover { background: #2a2f38; }
QPushButton#primary, QFrame#card QPushButton#primary { background: #2ee68a; color: #06130c; padding: 9px 18px; }
QPushButton#accent, QFrame#card QPushButton#accent { background: transparent; border: 1px solid #2ee68a; color: #2ee68a; padding: 6px 15px; }
QPushButton#accent:hover { background: #14351f; }
QPushButton#ghost, QFrame#card QPushButton#ghost { background: transparent; border: 1px solid #3a3f4a; color: #d1d5db; padding: 6px 15px; }
QPushButton#ghost:hover { background: #20242b; }
QPushButton#primary:hover { background: #4cf0a0; }
QPushButton#segment, QFrame#card QPushButton#segment { padding: 5px 16px; border-radius: 8px; background: #20242b; color: #8b93a1; }
QPushButton#segment:checked, QFrame#card QPushButton#segment:checked { background: #2ee68a; color: #06130c; }
QTableWidget { background: transparent; border: none; gridline-color: transparent; }
QHeaderView::section { background: transparent; color: #8b93a1; border: none; padding: 6px; font-weight: 600; }
QTableWidget::item:selected { background: #20242b; }
QCheckBox { spacing: 8px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #2c3038; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #20242b; color: #f3f4f6; border: none; padding: 6px; }

QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button { width: 0; height: 0; border: none; }
QSpinBox QLineEdit, QTimeEdit QLineEdit, QComboBox QLineEdit { padding: 0; margin: 0; background: transparent; border: none;
                                                              border-radius: 0; min-height: 0; }
QFrame#row { background: #1d2025; border-radius: 14px; }
QFrame#row QWidget { background: transparent; }
QFrame#row QTimeEdit { background: #262a33; }
QWidget#stepper, QFrame#card QWidget#stepper, QFrame#row QWidget#stepper { background: #20242b; border-radius: 10px; }
QWidget#stepper QPushButton#round { background: #2c3038; }
QPushButton#round, QFrame#card QPushButton#round, QFrame#row QPushButton#round { background: #2c3038; border-radius: 8px;
                                                                              padding: 0; min-width: 28px; font-size: 11pt; }
QPushButton#round:hover { background: #3a3f4a; }
QSpinBox#bare, QFrame#card QSpinBox#bare { background: transparent; border-radius: 0; padding: 0; font-weight: 600; }
QPushButton#day, QFrame#row QPushButton#day { background: #262a33; color: #8b93a1; border-radius: 8px; padding: 0;
                                              font-size: 8pt; min-width: 34px; }
QPushButton#day:checked, QFrame#row QPushButton#day:checked { background: #2ee68a; color: #06130c; }
QLabel#info { color: #8b93a1; border: 1.5px solid #5b6270; border-radius: 9px; font-size: 7pt; font-weight: 700; }
QLabel#info:hover { color: #f3f4f6; border-color: #f3f4f6; }
QLabel#cardtitle { font-size: 11.5pt; font-weight: 600; }
QLabel#chip { background: #20242b; border-radius: 8px; padding: 4px 12px; color: #8b93a1; }
QLabel#chipon { background: #14351f; border-radius: 8px; padding: 4px 12px; color: #2ee68a; font-weight: 600; }
QSlider::groove:horizontal { height: 6px; background: #2c3038; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #2ee68a; border-radius: 3px; }
QSlider::handle:horizontal { background: #ffffff; width: 18px; height: 18px; margin: -6px 0; border-radius: 9px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 6px; background: #2c3038; }
QCheckBox::indicator:checked { background: #2ee68a; image: url(CHECK_URL); }
"""


def _arrow_url() -> str:
    """Draw the dropdown chevron once into the app data dir (QSS can only reference files)."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
    from .paths import APPDIR
    path = APPDIR / "arrow.png"
    pm = QPixmap(10, 6)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#8b93a1"), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline([QPointF(1, 1), QPointF(5, 5), QPointF(9, 1)])
    p.end()
    pm.save(str(path), "PNG")
    return path.as_posix()


def _check_url() -> str:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
    from .paths import APPDIR
    path = APPDIR / "check.png"
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#06130c"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline([QPointF(4.5, 9.5), QPointF(7.8, 12.8), QPointF(13.5, 5.5)])
    p.end()
    pm.save(str(path), "PNG")
    return path.as_posix()


def watts_spin(value=1000) -> QSpinBox:
    s = QSpinBox()
    s.setRange(MIN_W, MAX_W)
    s.setSingleStep(50)
    s.setSuffix(" W")
    s.setValue(max(MIN_W, min(MAX_W, value)))
    return s


def card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


class MainWindow(QMainWindow):
    compact = False        # dashboard cells collapsed into compact single-line cells
    _compact_key = None

    def __init__(self, ctrl: Controller):
        super().__init__()
        self.ctrl = ctrl
        self.allow_close = False
        self.setWindowTitle("EcoFlow Scheduler - DELTA Pro")
        self.resize(1060, 820)
        self.setMinimumSize(420, 520)
        self.setStyleSheet(STYLE.replace("ARROW_URL", _arrow_url()).replace("CHECK_URL", _check_url()))

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 14)
        head = QHBoxLayout()
        title = QLabel("DELTA Pro")
        title.setObjectName("title")
        self.lbl_status = QLabel()
        self.lbl_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.lbl_status)
        outer.addLayout(head)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        outer.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

        self._build_dashboard()
        self._build_stats()
        self._build_control()
        self._build_settings()

        ctrl.telemetry.connect(self._on_telemetry)
        ctrl.online.connect(lambda *_: self._refresh_dashboard())
        ctrl.status.connect(lambda *_: self._refresh_dashboard())
        ctrl.engine.changed.connect(lambda *_: self._refresh_dashboard())
        ctrl.engine.guard.connect(lambda *_: self._refresh_dashboard())
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(1000)
        self._dash_tick = QTimer(self)
        self._dash_tick.timeout.connect(self._refresh_dash_card)
        self._stats_tick = QTimer(self)
        self._stats_tick.timeout.connect(self._refresh_stats)
        self._stats_tick.start(30_000)
        self._refresh_dashboard()
        self.dash_card.cmb_range.currentTextChanged.connect(lambda *_: self._sync_dash_timer())
        self._sync_dash_timer()
        if not ctrl.settings.complete:
            self.tabs.setCurrentWidget(self.settings_tab)

    # ---------------------------------------------------------------- dashboard
    def _build_dashboard(self):
        self.battery_cell = self._build_battery_cell()
        self.card_in = self._build_input_card()
        self.card_out = self._build_output_card()
        self.dash_card = AnalyticsCard(self.ctrl, "power", "Energy used", DASH_RANGES, "30 min")
        self.dash_card.setMinimumHeight(340)

        def plan(width, height):
            b, i, o, d = self.battery_cell, self.card_in, self.card_out, self.dash_card
            tiny = width < 560
            if height >= 740 and width >= 620:        # tall: big cards, battery on top, input | output, graph below
                mode, compact = "stack", False
                res = [(b, 0, 0, 1, 2), (i, 1, 0, 1, 1), (o, 1, 1, 1, 1), (d, 2, 0, 1, 2)], {0: 1, 1: 1}, {2: 1}
            elif height >= 900 and width < 620:       # tall and narrow: one big column
                mode, compact = "column", False
                res = [(b, 0, 0, 1, 1), (i, 1, 0, 1, 1), (o, 2, 0, 1, 1), (d, 3, 0, 1, 1)], {0: 1}, {3: 1}
            elif width >= 880 and height >= 560:      # wide: rich cells on one row
                mode, compact = "row", False
                res = [(b, 0, 0, 1, 1), (i, 0, 1, 1, 1), (o, 0, 2, 1, 1), (d, 1, 0, 1, 3)], {0: 5, 1: 5, 2: 3}, {1: 1}
            else:                                     # low on space: collapse the three cells into one compact line
                mode, compact = "compact", True
                res = [(b, 0, 0, 1, 1), (i, 0, 1, 1, 1), (o, 0, 2, 1, 1), (d, 1, 0, 1, 3)], {0: 4, 1: 3, 2: 3}, {1: 1}
            self._set_compact(compact, tiny)
            return res + (mode, tiny)

        sc = ReflowScroll(plan)
        self.dash_page = sc.page
        self.tabs.addTab(sc, "Dashboard")

    def _set_compact(self, compact: bool, tiny: bool):
        """Collapse the battery / input / output cells into small single-line cells when space is low."""
        key = (compact, tiny)
        if key == self._compact_key:
            return
        self._compact_key = key
        self.compact = compact
        m = (14, 10, 14, 10) if compact else None
        self.battery_cell.layout().setContentsMargins(*(m or (22, 16, 22, 12)))
        self.card_in.layout().setContentsMargins(*(m or (22, 14, 22, 14)))
        self.card_out.layout().setContentsMargins(*(m or (22, 14, 22, 14)))
        self.lbl_cap.setVisible(not compact)
        self.lbl_temp.setVisible(not compact)
        self.lbl_since.setVisible(not tiny)
        self.lbl_acout.setVisible(not compact)
        self._in_spacer.setVisible(not compact)
        small_font = "font-size: 15pt; font-weight: 600;"
        for lab in (self.lbl_remain, self.lbl_in, self.lbl_out):
            lab.setStyleSheet(small_font if compact else "")
        self.battery.set_compact(compact)
        self._refresh_dashboard()

    def _build_battery_cell(self) -> QFrame:
        c = card()
        h = QVBoxLayout(c)
        h.setContentsMargins(22, 16, 22, 12)
        h.setSpacing(4)
        row = QHBoxLayout()
        cap = QLabel("Battery time remaining")
        cap.setObjectName("muted")
        self.lbl_cap = cap
        self.lbl_temp = QLabel()
        self.lbl_temp.setObjectName("muted")
        row.addWidget(cap)
        row.addStretch()
        row.addWidget(self.lbl_temp)
        h.addLayout(row)
        self.lbl_remain = QLabel("--")
        self.lbl_remain.setObjectName("hero")
        h.addWidget(self.lbl_remain)
        srow = QHBoxLayout()
        srow.setSpacing(8)
        self.lbl_state = QLabel("")
        self.lbl_state.setObjectName("status")
        self.lbl_since = QLabel("")
        self.lbl_since.setObjectName("muted")
        srow.addWidget(self.lbl_state)
        srow.addWidget(self.lbl_since)
        srow.addStretch()
        h.addLayout(srow)
        self.battery = BatteryBar()
        h.addWidget(self.battery, 1)
        return c

    def _build_input_card(self) -> QFrame:
        """Grid: row0 title | caption, row1 big number | big limit + '?', row2 spacer | status (bigs share a row).
        The limit side is hidden while there is no input."""
        c = card()
        g = QGridLayout(c)
        g.setContentsMargins(22, 14, 22, 14)
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(2)
        t = QLabel(f'<span style="color:{GREEN}">&#9679;</span>  Input')
        t.setObjectName("muted")
        self.lbl_in = QLabel("-- W")
        self.lbl_in.setObjectName("statvalue")
        g.addWidget(t, 0, 0)
        g.addWidget(self.lbl_in, 1, 0)
        self._in_spacer = QLabel(" ")
        g.addWidget(self._in_spacer, 2, 0)

        line = QFrame()
        line.setObjectName("vline")
        g.addWidget(line, 0, 1, 3, 1)

        self.lbl_limit_caption = QLabel("Limit")
        self.lbl_limit_caption.setObjectName("muted")
        self.lbl_limit_caption.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        vrow = QHBoxLayout()
        vrow.setSpacing(8)
        vrow.addStretch()
        self.lbl_limit_val = QLabel("-- W")
        self.lbl_limit_val.setObjectName("statvalue")
        self.info = InfoIcon()
        vrow.addWidget(self.lbl_limit_val)
        vrow.addWidget(self.info, 0, Qt.AlignVCenter)
        srow = QHBoxLayout()
        srow.addStretch()
        self.lbl_limit_status = QLabel("")
        self.lbl_limit_status.setObjectName("status")
        srow.addWidget(self.lbl_limit_status)
        g.addWidget(self.lbl_limit_caption, 0, 2)
        g.addLayout(vrow, 1, 2)
        g.addLayout(srow, 2, 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(2, 1)
        g.setRowStretch(1, 1)
        self.limit_widgets = [line, self.lbl_limit_caption, self.lbl_limit_val, self.info, self.lbl_limit_status]
        return c

    def _build_output_card(self) -> QFrame:
        c = card()
        g = QGridLayout(c)
        g.setContentsMargins(22, 14, 22, 14)
        g.setVerticalSpacing(2)
        t = QLabel(f'<span style="color:{ORANGE}">&#9679;</span>  Output')
        t.setObjectName("muted")
        self.lbl_out = QLabel("-- W")
        self.lbl_out.setObjectName("statvalue")
        self.lbl_acout = QLabel(" ")
        self.lbl_acout.setObjectName("muted")
        self.lbl_acout.setStyleSheet("font-size: 9pt;")
        g.addWidget(t, 0, 0)
        g.addWidget(self.lbl_out, 1, 0)
        g.addWidget(self.lbl_acout, 2, 0)
        g.setRowStretch(1, 1)
        return c

    def _sync_dash_timer(self):
        self._dash_tick.start(self.dash_card.interval_ms())
        self._refresh_dash_card()

    def _refresh_dash_card(self):
        if self.isVisible() and self.tabs.currentIndex() == 0:
            self.dash_card.refresh()

    def _on_telemetry(self, _t: Telemetry):
        self._refresh_dashboard()

    def _refresh_dashboard(self):
        c = self.ctrl
        t = c.last
        fresh = c.fresh
        dot = "#2ee68a" if fresh else "#ef4444"
        self.lbl_status.setText(f'<span style="color:{dot}">&#9679;</span>  {c.status_text}')
        w, reason = c.engine.effective
        auto_on = c.engine.rules.automation_enabled
        dev = f"{t.cfg_limit} W" if t else "--"
        self.lbl_limit_caption.setText(f"Limit · {short_reason(reason)}")
        self.lbl_limit_val.setText(dev)
        if c.engine.guard_tripped:
            status, name = "conflict - paused", "statuspaused"
        elif not auto_on:
            status, name = "paused", "statuspaused"
        elif t and t.cfg_limit != w:
            status, name = f"applying {w} W", "status"
        else:
            status, name = "on target", "statusok"
        self.lbl_limit_status.setText(status)
        if self.lbl_limit_status.objectName() != name:
            self.lbl_limit_status.setObjectName(name)
            self.lbl_limit_status.style().unpolish(self.lbl_limit_status)
            self.lbl_limit_status.style().polish(self.lbl_limit_status)
        self.info.setToolTip(self._rules_tooltip(dev, w, reason, auto_on))
        show_limit = bool(t and t.in_w >= 1) and not self.compact   # no input -> the limit is irrelevant
        for wdg in self.limit_widgets:
            wdg.setVisible(show_limit)
        self._refresh_power_state()
        if t:
            self.battery.set_soc(t.soc, fresh, c.power_state if fresh else "idle")
            self.lbl_remain.setText(fmt_duration(t.chg_min) + " to full" if (t.charging and fresh)
                                    else fmt_duration(t.dsg_min))
            self.lbl_temp.setText(f"{t.temp:.0f} C")
            self.lbl_in.setText(f"{t.in_w:.0f} W")
            self.lbl_out.setText(f"{t.out_w:.0f} W")
            self.lbl_acout.setText(f"AC output {t.ac_out_w:.0f} W")
        else:
            rows = c.history.range(time.time() - 7 * 86400)
            self.battery.set_soc(rows[-1][1] if rows else None, False)

    def _rules_tooltip(self, dev: str, w: int, reason: str, auto_on: bool) -> str:
        rows = self.ctrl.engine.describe()
        out = [f"<b>Max AC charging power now: {dev}</b>",
               f"Rule result: <b>{w} W</b> · {short_reason(reason)}", "<hr>", "Rules, highest priority first:"]
        for title, detail, applied in rows:
            mark = " &nbsp;<b style='color:#2ee68a'>&larr; applied</b>" if applied else ""
            out.append(f"<b>{title}</b>: {detail}{mark}")
        if self.ctrl.engine.guard_tripped:
            out.append("<hr><b style='color:#ffa629'>Automation paused by the conflict guard</b>: too many commands "
                       "in 10 min - another controller may be changing the limit. Press Save &amp; apply to resume.")
        elif not auto_on:
            out.append("<hr><b style='color:#ffa629'>Automation is off</b>: rules are shown but not sent to the device.")
        return "<br>".join(out)

    STATE_TEXT = {"charging": "\u26a1 Charging", "discharging": "Discharging", "full": "\u2713 Fully charged",
                  "ongrid": "On grid"}
    STATE_VERB = {"charging": "started", "discharging": "started", "full": "since", "ongrid": "since"}

    @staticmethod
    def _when(ts: float) -> str:
        d = datetime.fromtimestamp(ts)
        return d.strftime("%H:%M") if d.date() == datetime.now().date() else d.strftime("%a %H:%M")

    def _refresh_power_state(self):
        c = self.ctrl
        t = c.last
        tip = ""
        if not t:
            text, name, since = "No data", "status", ""
        elif not c.fresh:
            text, name = "Offline", "status"
            since = f"\u2022  last data {self._when(t.ts)}"
        else:
            st = c.power_state or "ongrid"
            text = self.STATE_TEXT[st]
            name = {"charging": "statusok", "full": "statusok", "ongrid": "status"}.get(st) or (
                "statuspaused" if not t.grid else "status")
            since = f"\u2022  {self.STATE_VERB[st]} {self._when(c.state_since_ts)}" if c.state_since_ts else ""
            tip = "Power outage: no electricity from the grid" if not t.grid else ""
        self.lbl_state.setText(text)
        self.lbl_state.setToolTip(tip)
        if self.lbl_state.objectName() != name:
            self.lbl_state.setObjectName(name)
            self.lbl_state.style().unpolish(self.lbl_state)
            self.lbl_state.style().polish(self.lbl_state)
        self.lbl_since.setText(since)

    def _on_tick(self):
        self._refresh_temp_label()
        if self.ctrl.last and not self.ctrl.fresh:
            self._refresh_dashboard()

    # --------------------------------------------------------------- statistics
    def _build_stats(self):
        self.stats_power = AnalyticsCard(self.ctrl, "power", "Statistic", STAT_RANGES, "7 days")
        self.stats_soc = AnalyticsCard(self.ctrl, "soc", "Battery", STAT_RANGES, "7 days")
        self.stats_outage = OutageCard(self.ctrl)
        self.stats_power.setMinimumHeight(300)
        self.stats_soc.setMinimumHeight(250)
        self.stats_summary = QLabel()
        self.stats_summary.setObjectName("muted")
        self.stats_summary.setWordWrap(True)
        sc = SplitPage((self.stats_power, self.stats_outage, self.stats_soc), self.stats_summary)
        self.stats_page = sc
        self.tabs.addTab(sc, "Statistics")
        self.tabs.currentChanged.connect(lambda *_: (self._refresh_stats(), self._refresh_dash_card()))

    def _refresh_stats(self):
        if not self.isVisible() or self.tabs.currentIndex() != 1:
            return
        self.stats_power.refresh()
        self.stats_outage.refresh()
        self.stats_soc.refresh()
        rows7 = self.ctrl.history.range(time.time() - 7 * 86400)
        if rows7:
            outs = [r[3] for r in rows7]
            span_h = (rows7[-1][0] - rows7[0][0]) / 3600
            self.stats_summary.setText(
                f"Stored locally: {len(rows7)} samples over {span_h:.0f} h. "
                f"Average output {sum(outs) / len(outs):.0f} W, peak {max(outs):.0f} W, "
                f"lowest battery {min(r[1] for r in rows7):.0f}%. Works without a connection to EcoFlow.")
        else:
            self.stats_summary.setText("No history yet - data is stored locally while the app is running.")

    # ------------------------------------------------------------------ control
    def _section(self, title: str, subtitle: str, right: QWidget | None = None):
        c = card()
        v = QVBoxLayout(c)
        v.setContentsMargins(20, 16, 20, 18)
        v.setSpacing(10)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("cardtitle")
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(sub)
        head.addLayout(col, 1)
        if right is not None:
            head.addWidget(right, 0, Qt.AlignTop)
        v.addLayout(head)
        return c, v

    def _build_control(self):
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        rules = self.ctrl.engine.rules

        self.cb_auto = Switch(rules.automation_enabled)
        c_auto, _ = self._section("Automation", "Send the rules below to the device. Off = the app only monitors.",
                                  self.cb_auto)

        c_def, v = self._section("Default max charging power", "Used whenever no other rule applies.")
        row = QHBoxLayout()
        self.sp_default = watts_stepper(rules.default_watts)
        self.sl_default = QSlider(Qt.Horizontal)
        self.sl_default.setRange(MIN_W, MAX_W)
        self.sl_default.setSingleStep(50)
        self.sl_default.setPageStep(100)
        self.sl_default.setValue(self.sp_default.value())
        self.sl_default.valueChanged.connect(lambda x: self.sp_default.setValue(round(x / 50) * 50))
        self.sp_default.valueChanged.connect(self.sl_default.setValue)
        row.addWidget(self.sp_default)
        row.addSpacing(10)
        row.addWidget(self.sl_default, 1)
        v.addLayout(row)

        add = QPushButton("+  Add window")
        add.setObjectName("accent")
        add.clicked.connect(lambda: self._add_row(ScheduleEntry()))
        c_sched, v = self._section("Schedule", "Cap the charging power during time windows (they may cross midnight, "
                                               "e.g. 23:00 \u2192 09:00). The first matching window wins.", add)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(8)
        v.addLayout(self.rows_box)
        self.lbl_empty = QLabel("No windows yet - add one, for example 23:00 \u2192 09:00 at 300 W for quiet nights.")
        self.lbl_empty.setObjectName("muted")
        self.lbl_empty.setWordWrap(True)
        v.addWidget(self.lbl_empty)
        self.sched_rows: list[ScheduleRow] = []
        for e in rules.schedule:
            self._add_row(e)

        c_tmp, v = self._section("Temporary rule", "Override everything for a while, then go back to the normal rules.")
        flow = FlowLayout(hspacing=10, vspacing=8)
        self.sp_tmp_w = watts_stepper(300)
        self.sp_tmp_d = Stepper(1, 1, 999, 1, "")
        self.cmb_tmp_u = QComboBox()
        self.cmb_tmp_u.addItems(["hours", "minutes"])
        bs = QPushButton("Start")
        bs.setObjectName("primary")
        bs.clicked.connect(self._start_temp)
        bc = QPushButton("Cancel")
        bc.setObjectName("ghost")
        bc.clicked.connect(self._cancel_temp)
        for x in (self.sp_tmp_w, QLabel("for"), self.sp_tmp_d, self.cmb_tmp_u, bs, bc):
            flow.addWidget(x)
        v.addLayout(flow)
        self.lbl_tmp = QLabel()
        self.lbl_tmp.setObjectName("chip")
        v.addWidget(self.lbl_tmp, 0, Qt.AlignLeft)

        d = rules.dynamic
        self.cb_dyn = Switch(d.enabled)
        c_dyn, v = self._section("Dynamic charging", "Charge faster while the battery is low, slower once it is fuller.",
                                 self.cb_dyn)
        flow = FlowLayout(hspacing=10, vspacing=8)
        self.sp_dyn_w1 = watts_stepper(d.watts_below)
        self.sp_dyn_thr = Stepper(d.soc_threshold, 1, 100, 1, " %")
        self.sp_dyn_w2 = watts_stepper(d.watts_above)
        for x in (QLabel("Charge at"), self.sp_dyn_w1, QLabel("while battery is below"), self.sp_dyn_thr,
                  QLabel("then at"), self.sp_dyn_w2):
            flow.addWidget(x)
        v.addLayout(flow)

        def plan(width, height=None):
            if width >= 900:
                return [(c_auto, 0, 0, 1, 1), (c_def, 0, 1, 1, 1), (c_sched, 1, 0, 1, 2), (c_tmp, 2, 0, 1, 2),
                        (c_dyn, 3, 0, 1, 2)], {0: 1, 1: 1}, {4: 1}
            return [(c_auto, 0, 0, 1, 1), (c_def, 1, 0, 1, 1), (c_sched, 2, 0, 1, 1), (c_tmp, 3, 0, 1, 1),
                    (c_dyn, 4, 0, 1, 1)], {0: 1}, {5: 1}

        sc = ReflowScroll(plan)
        self.ctl_page = sc.page
        pl.addWidget(sc, 1)

        bottom = QHBoxLayout()
        note = QLabel("Priority: Temporary rule > Schedule > Dynamic > Default")
        note.setObjectName("muted")
        save = QPushButton("Save && apply")
        save.setObjectName("primary")
        save.setMinimumWidth(180)
        save.clicked.connect(self._save_rules)
        bottom.addWidget(note, 1)
        bottom.addWidget(save)
        pl.addLayout(bottom)
        self.tabs.addTab(page, "Control")

    def _add_row(self, e: ScheduleEntry):
        row = ScheduleRow(e)
        row.removed.connect(self._remove_row)
        self.sched_rows.append(row)
        self.rows_box.addWidget(row)
        self.lbl_empty.setVisible(False)

    def _remove_row(self, row: ScheduleRow):
        self.sched_rows.remove(row)
        self.rows_box.removeWidget(row)
        row.deleteLater()
        self.lbl_empty.setVisible(not self.sched_rows)

    def _collect_rules(self) -> RulesConfig:
        cur = self.ctrl.engine.rules
        return RulesConfig(
            automation_enabled=self.cb_auto.isChecked(),
            default_watts=self.sp_default.value(),
            schedule=[r.entry() for r in self.sched_rows],
            dynamic=Dynamic(enabled=self.cb_dyn.isChecked(), soc_threshold=self.sp_dyn_thr.value(),
                            watts_below=self.sp_dyn_w1.value(), watts_above=self.sp_dyn_w2.value()),
            temporary=deepcopy(cur.temporary))

    def _save_rules(self):
        self.ctrl.engine.set_rules(self._collect_rules())
        self._refresh_dashboard()

    def _start_temp(self):
        mins = self.sp_tmp_d.value() * (60 if self.cmb_tmp_u.currentText() == "hours" else 1)
        r = self._collect_rules()
        r.temporary = Temporary(self.sp_tmp_w.value(), time.time() + mins * 60)
        self.ctrl.engine.set_rules(r)
        self._refresh_dashboard()

    def _cancel_temp(self):
        r = self._collect_rules()
        r.temporary = None
        self.ctrl.engine.set_rules(r)
        self._refresh_dashboard()

    def _refresh_temp_label(self):
        t = self.ctrl.engine.rules.temporary
        if t and t.until > time.time():
            left = int(t.until - time.time())
            self.lbl_tmp.setObjectName("chipon")
            self.lbl_tmp.setText(f"Active: {t.watts} W - {left // 3600}h {left % 3600 // 60:02d}m {left % 60:02d}s left")
        else:
            self.lbl_tmp.setObjectName("chip")
            self.lbl_tmp.setText("Not active")
        self.lbl_tmp.style().unpolish(self.lbl_tmp)
        self.lbl_tmp.style().polish(self.lbl_tmp)

    # ----------------------------------------------------------------- settings
    def _build_settings(self):
        w = QWidget()
        self.settings_tab = w
        lay = QVBoxLayout(w)
        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(20, 18, 20, 18)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        s = self.ctrl.settings
        self.ed_email = QLineEdit(s.email)
        self.ed_pass = QLineEdit(s.password)
        self.ed_pass.setEchoMode(QLineEdit.Password)
        self.ed_sn = QLineEdit(s.sn)
        self.cmb_host = QComboBox()
        self.cmb_host.setEditable(True)
        self.cmb_host.addItems(["api-e.ecoflow.com", "api.ecoflow.com"])
        self.cmb_host.setCurrentText(s.api_host)
        form.addRow("EcoFlow account e-mail", self.ed_email)
        form.addRow("Password (kept in Windows Credential Manager)", self.ed_pass)
        form.addRow("Device serial number", self.ed_sn)
        form.addRow("API host (EU / global)", self.cmb_host)
        cl.addLayout(form)
        self.cb_autostart = QCheckBox("Start with Windows (minimized to tray)")
        self.cb_autostart.setChecked(autostart.is_enabled())
        cl.addWidget(self.cb_autostart)
        btn = QPushButton("Save && reconnect")
        btn.setObjectName("primary")
        btn.clicked.connect(self._save_settings)
        cl.addWidget(btn)
        lay.addWidget(c)
        lay.addStretch()
        self.tabs.addTab(w, "Settings")

    def _save_settings(self):
        s = Settings(email=self.ed_email.text().strip(), sn=self.ed_sn.text().strip(),
                     api_host=self.cmb_host.currentText().strip(), password=self.ed_pass.text())
        try:
            autostart.set_enabled(self.cb_autostart.isChecked())
        except OSError as e:
            QMessageBox.warning(self, "Autostart", f"Could not change autostart: {e}")
        if s.complete:
            self.ctrl.apply_settings(s)
        else:
            QMessageBox.information(self, "Settings", "E-mail, password and serial number are required.")

    # -------------------------------------------------- visibility -> poll rate
    def _update_active(self):
        self.ctrl.set_window_active(self.isVisible() and not self.isMinimized())

    def showEvent(self, e):
        super().showEvent(e)
        self._update_active()
        self._refresh_dash_card()
        self._refresh_stats()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._update_active()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange:
            self._update_active()

    # ------------------------------------------------------------------- close
    def closeEvent(self, e):
        if self.allow_close:
            e.accept()
        elif sys.platform == "darwin" and not e.spontaneous():
            # Cmd+Q: Qt closes the windows programmatically (the X button is a *spontaneous* close) -> really quit
            self.allow_close = True
            e.accept()
            QTimer.singleShot(0, QApplication.quit)
        else:
            e.ignore()
            self.hide()  # minimize to tray; quit via tray menu
