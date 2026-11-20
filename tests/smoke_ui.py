"""UI smoke test with fake data (temp data dir): python tests/smoke_ui.py <out_dir>"""
import math
import os
import sys
import tempfile
import time

out = sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir()
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ.update(EF_EMAIL="t@example.com", EF_PASSWORD="x", EF_SN="TESTSN")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ecoflow_app.settings as st  # noqa: E402
st.keyring = None  # never touch the real credential store in tests

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ecoflow_app.api import Telemetry  # noqa: E402
from ecoflow_app.controller import Controller  # noqa: E402
from ecoflow_app.mainwindow import MainWindow  # noqa: E402
from ecoflow_app.rules import ScheduleEntry  # noqa: E402
from ecoflow_app.tray import Tray, tooltip_text  # noqa: E402

app = QApplication([])
ctrl = Controller()
now = time.time()
N = 7 * 24 * 30
for i in range(N):  # 7 days, every 2 min, with gaps
    ts = now - (N - i) * 120
    if now - 30 * 3600 < ts < now - 27 * 3600 or now - 5.5 * 86400 < ts < now - 3.2 * 86400:
        continue  # gaps: 3 h yesterday + ~2 whole days
    h = (ts % 86400) / 3600
    out_w = 150 + 120 * math.sin(h / 24 * 6.28) ** 2
    ctrl.history._last_ts = 0
    from datetime import datetime as _dt
    hh = _dt.fromtimestamp(ts)
    hod = hh.hour + hh.minute / 60
    day_age = (_dt.now().date() - hh.date()).days
    outage = (12.58 <= hod <= 17.83 and day_age >= 1 and day_age != 3) or (3.17 <= hod <= 4.33 and day_age == 0)         or (21 <= hod <= 21.5 and day_age == 2)
    t = Telemetry(ts, 60 + 35 * math.sin(i / 225), 0 if outage else out_w + 600 * (i % 375 < 100), out_w, 0, out_w, 300, 28,
                  900, 120, grid=not outage)
    ctrl.history.add(t, ts)

ctrl.engine.rules.schedule = [ScheduleEntry("23:00", "09:00", 300)]
win = MainWindow(ctrl)
tray = Tray(ctrl, win)
win.resize(940, 900)
win.show()

live = Telemetry(time.time(), 85.0, 520.0, 244.0, 520.0, 244.0, 300, 28, 23714, 95)
ctrl._on_telemetry(live)
ctrl._on_status("Connected")
app.processEvents()
print("TOOLTIP charging:", tooltip_text(ctrl).replace("\n", " // "))
ctrl._on_telemetry(Telemetry(time.time(), 100.0, 258.0, 244.0, 258.0, 244.0, 300, 28, 23714, 0))
print("TOOLTIP idle    :", tooltip_text(ctrl).replace("\n", " // "))

ctrl.live.clear()
for i in range(400):  # 400 s of 1 Hz live samples (gap in the middle), peak above 500 W to test auto-range
    if 130 < i < 290:
        continue
    ts = time.time() - (400 - i)
    ctrl.live.append((ts, 90.0, 300 + 800 * (i > 330) + 50 * math.sin(i / 20), 240 + 30 * math.cos(i / 15)))


def hover(widget, fx):
    r = widget._plot()
    pos = QPointF(r.left() + fx * r.width(), r.center().y())
    widget.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, pos, widget.mapToGlobal(pos), Qt.NoButton, Qt.NoButton,
                                      Qt.NoModifier))
    app.processEvents()


card = win.dash_card
for rng in ("5 min", "30 min", "24 hours", "7 days"):
    card.cmb_range.setCurrentText(rng)
    win.tabs.setCurrentIndex(0)
    app.processEvents()
    if rng != "7 days":
        hover(card.area, 0.6)
        print(f"[{rng}] scale={card.area._scale()} hover hits={ {k: len(v) for k, v in card.area._screen.items()} }")
    win.grab().save(os.path.join(out, f"ui_dash_{rng.replace(' ', '')}.png"))

card.cmb_range.setCurrentText("5 min")
card.cmb_y.setCurrentText("Custom...")
card.sp_lo.setValue(200)
card.sp_hi.setValue(600)
app.processEvents()
print("custom y-range ->", card.area._scale())
card.cmb_y.setCurrentText("Auto (0-500 W)")

for i, name in enumerate(["dashboard", "stats", "control", "settings"]):
    win.tabs.setCurrentIndex(i)
    app.processEvents()
    win.grab().save(os.path.join(out, f"ui_{name}.png"))
# outage timeline: hover a black part and a green part, render the whole card
win.tabs.setCurrentIndex(1)
win.resize(940, 1500)
app.processEvents()
oc = win.stats_outage
oc.refresh()
app.processEvents()
tl = oc.chart
r, slot = tl._geom()
for label, di, hour in (("outage block", 0, 14.5), ("electricity", 0, 6), ("no-data day", 2, 12)):
    pos = QPointF(r.left() + slot * (di + 0.5), r.top() + hour / 24 * r.height())
    tl.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, pos, tl.mapToGlobal(pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    seg = tl._hover[1] if tl._hover else None
    if seg:
        from ecoflow_app.outages import fmt_hm, hhmm
        print(f"hover {label}: {seg.kind} {hhmm(seg.start)}-{hhmm(seg.end)} ({fmt_hm(seg.seconds)}) used {seg.out_kwh:.2f} kWh")
    else:
        print(f"hover {label}: none")
pos = QPointF(r.left() + slot * 0.5, r.top() + 14.5 / 24 * r.height())
tl.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, pos, tl.mapToGlobal(pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
app.processEvents()
oc.grab().save(os.path.join(out, "outage_card.png"))
win.resize(940, 900)
# responsive layouts at several window sizes
ctrl._on_telemetry(Telemetry(time.time(), 62.0, 900, 300, 900, 300, 300, 28, 900, 85, grid=True))
for w_, h_ in ((1354, 1377), (1300, 780), (705, 726), (560, 560), (440, 540)):
    win.resize(w_, h_)
    for i, name in enumerate(["dashboard", "stats", "control"]):
        win.tabs.setCurrentIndex(i)
        app.processEvents()
        time.sleep(0.15)
        app.processEvents()
        win.grab().save(os.path.join(out, f"resp_{w_}_{name}.png"))
# calendar-style outage view (Today / 3 days)
win.resize(1060, 900)
win.tabs.setCurrentIndex(1)
for rng in ("3 days", "Today"):
    oc.cmb.setCurrentText(rng)
    app.processEvents()
    tl = oc.chart
    r, slot = tl._geom()
    pos = QPointF(r.left() + slot * (len(tl.days) - 0.5), r.top() + 14.5 / 24 * r.height())
    tl.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, pos, tl.mapToGlobal(pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    seg = tl._hover[1] if tl._hover else None
    print(f"calendar[{rng}] hover at 14:30 last column ->", (seg.kind, seg.guessed) if seg else None, "| calendar mode:", tl.calendar)
    app.processEvents()
    oc.grab().save(os.path.join(out, f"outage_{rng.replace(' ', '')}.png"))
oc.cmb.setCurrentText("7 days")
for name, tel in (("charging", Telemetry(time.time(), 62.0, 900, 300, 900, 300, 300, 28, 900, 85, grid=True)),
                  ("outage_low", Telemetry(time.time(), 18.0, 0, 320, 0, 320, 300, 28, 150, 0, grid=False)),
                  ("outage_mid", Telemetry(time.time(), 38.0, 0, 320, 0, 320, 300, 28, 300, 0, grid=False))):
    ctrl.power_state = None
    ctrl._on_telemetry(tel)
    win.tabs.setCurrentIndex(0)
    app.processEvents()
    time.sleep(0.4)
    app.processEvents()
    win.grab().save(os.path.join(out, f"ui_state_{name}.png"))
print("state after outage telemetry:", ctrl.power_state, "| tooltip:", tooltip_text(ctrl).replace(chr(10), " // "))
win.close()
print("close hides, not quits:", not win.isVisible(), "| allow_close =", win.allow_close)
ctrl.shutdown()

# tooltip preview (QToolTip itself cannot be grabbed): render its HTML in a styled label
if len(sys.argv) > 2 and sys.argv[2] == "tooltip":
    from PySide6.QtWidgets import QLabel
    win.show()
    app.processEvents()
    lab = QLabel(win.info.toolTip())
    lab.setStyleSheet("background:#20242b;color:#f3f4f6;padding:10px;border-radius:8px;")
    lab.setTextFormat(Qt.RichText)
    lab.adjustSize()
    lab.grab().save(os.path.join(out, "tooltip.png"))
