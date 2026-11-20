"""Analytics card: <=1 day -> smooth area chart ('Statistic' look); >1 day -> pill bars ('energy usages' look)."""
from __future__ import annotations

import time

from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget)

from .charts import GREEN, ORANGE, AreaChart, PillBars, Series
from .controller import Controller

GAP_SECONDS = 300  # do not integrate energy across gaps longer than this

Y_PRESETS = {"Auto (0-500 W)": (None, None), "0-1000 W": (0, 1000), "0-2000 W": (0, 2000), "0-3000 W": (0, 3000),
             "Custom...": "custom"}


def energy_kwh(rows: list[tuple], idx: int) -> float:
    total = 0.0
    for a, b in zip(rows, rows[1:]):
        dt = b[0] - a[0]
        if 0 < dt <= GAP_SECONDS:
            total += (a[idx] or 0) * dt / 3.6e6
    return total


def fmt_energy(kwh: float) -> str:
    return f"{kwh * 1000:.0f} Wh" if kwh < 1 else f"{kwh:,.2f} kWh"


class AnalyticsCard(QFrame):
    def __init__(self, ctrl: Controller, kind: str, caption: str, ranges: dict[str, int], default: str):
        super().__init__()
        self.setObjectName("card")
        self.ctrl, self.kind, self.caption, self.ranges = ctrl, kind, caption, ranges
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        head = QHBoxLayout()
        left = QVBoxLayout()
        self.lbl_caption = QLabel(caption)
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
        self.cmb_range = QComboBox()
        self.cmb_range.setObjectName("pill")
        self.cmb_range.addItems(list(ranges))
        self.cmb_range.setCurrentText(default)
        self.cmb_range.currentTextChanged.connect(self._on_range)
        head.addWidget(self.cmb_range, 0)
        lay.addLayout(head)

        # options row: y-axis control (area/power) or Output|Input toggle (bars)
        self.opts = QHBoxLayout()
        self.chips = QLabel()
        self.chips.setObjectName("muted")
        self.opts.addWidget(self.chips)
        self.opts.addStretch()
        self.cmb_y = QComboBox()
        self.cmb_y.setObjectName("pill")
        self.cmb_y.addItems(list(Y_PRESETS))
        self.cmb_y.currentTextChanged.connect(self._on_y)
        self.sp_lo, self.sp_hi = QSpinBox(), QSpinBox()
        for sp, v in ((self.sp_lo, 0), (self.sp_hi, 1000)):
            sp.setRange(0, 10000)
            sp.setSingleStep(100)
            sp.setSuffix(" W")
            sp.setValue(v)
            sp.valueChanged.connect(self._on_y)
        self.lbl_y = QLabel("Y axis")
        self.lbl_y.setObjectName("muted")
        self.btn_out, self.btn_in = QPushButton("Output"), QPushButton("Input")
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for b in (self.btn_out, self.btn_in):
            b.setCheckable(True)
            b.setObjectName("segment")
            grp.addButton(b)
            b.clicked.connect(self.refresh)
        self.btn_out.setChecked(True)
        for w in (self.btn_out, self.btn_in, self.lbl_y, self.cmb_y, self.sp_lo, self.sp_hi):
            self.opts.addWidget(w)
        lay.addLayout(self.opts)

        self.area = AreaChart("%" if kind == "soc" else "W")
        if kind == "soc":
            self.area.fixed_hi = 100
        self.bars = PillBars()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.area)
        self.stack.addWidget(self.bars)
        lay.addWidget(self.stack, 1)
        self._on_range()

    # ---- helpers
    @property
    def secs(self) -> int:
        return self.ranges[self.cmb_range.currentText()]

    @property
    def bar_mode(self) -> bool:
        return self.kind == "power" and self.secs > 86400

    def interval_ms(self) -> int:
        return 1000 if self.secs <= 1800 else 30_000

    def _on_range(self, *_):
        bars = self.bar_mode
        self.stack.setCurrentWidget(self.bars if bars else self.area)
        for w in (self.btn_out, self.btn_in):
            w.setVisible(bars)
        power_area = self.kind == "power" and not bars
        for w in (self.lbl_y, self.cmb_y):
            w.setVisible(power_area)
        self._on_y()
        self.refresh()

    def _on_y(self, *_):
        preset = Y_PRESETS[self.cmb_y.currentText()]
        custom = preset == "custom"
        power_area = self.kind == "power" and not self.bar_mode
        self.sp_lo.setVisible(custom and power_area)
        self.sp_hi.setVisible(custom and power_area)
        if custom:
            self.area.set_y_range(self.sp_lo.value(), max(self.sp_hi.value(), self.sp_lo.value() + 100))
        else:
            self.area.set_y_range(*preset)

    # ---- data
    def refresh(self):
        c = self.ctrl
        now = time.time()
        secs = self.secs
        if self.bar_mode:
            days = max(2, round(secs / 86400))
            rows = c.history.daily_energy_kwh(days)
            metric = "in" if self.btn_in.isChecked() else "out"
            self.bars.set_data(rows, metric)
            total = sum(r[1] if metric == "in" else r[2] for r in rows)
            self.lbl_caption.setText(f"Total energy {'input' if metric == 'in' else 'usage'} - {self.cmb_range.currentText()}")
            self.lbl_value.setText(f"{total:,.2f} kWh")
            self.lbl_sub.setText("")
            self.chips.setText("")
            return
        rows = c.recent(now - secs) if secs <= 3600 else c.history.range(now - secs, with_prev=True)
        rows_in = [r for r in rows if r[0] >= now - secs]      # `rows` may hold one earlier row for the line edge
        if self.kind == "soc":
            self.area.set_data([Series("Battery", GREEN, [(r[0], r[1]) for r in rows])], now - secs, now)
            socs = [r[1] for r in rows_in]
            self.lbl_caption.setText(f"Battery level - {self.cmb_range.currentText()}")
            self.lbl_value.setText(f"{socs[-1]:.0f}%" if socs else "--")
            self.lbl_sub.setText(f"min {min(socs):.0f}% - max {max(socs):.0f}%" if socs else "")
            return
        self.area.set_data([Series("Input", GREEN, [(r[0], r[2]) for r in rows], step_zero=True),
                            Series("Output", ORANGE, [(r[0], r[3]) for r in rows])], now - secs, now)
        e_out, e_in = energy_kwh(rows_in, 3), energy_kwh(rows_in, 2)
        self.lbl_caption.setText(f"{self.caption} - {self.cmb_range.currentText()}")
        self.lbl_value.setText(fmt_energy(e_out))
        self.lbl_sub.setText(f"used   |   {fmt_energy(e_in)} in")
        self.chips.setText(f'<span style="color:{GREEN}">&#9679;</span> Input &nbsp;&nbsp; '
                           f'<span style="color:{ORANGE}">&#9679;</span> Output')
