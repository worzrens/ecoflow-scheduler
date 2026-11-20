"""Live read-only poll-rate check: 1 s (window active) then 10 s (tray). Temp data dir, automation off."""
import os
import sys
import tempfile
import time

os.environ["APPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ecoflow_app.settings as st  # noqa: E402
st.keyring = None
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ecoflow_app.controller import Controller  # noqa: E402

app = QApplication([])
c = Controller()
c.window_active = True
stamps, statuses = [], []
c.telemetry.connect(lambda t: stamps.append(time.time()))
c.status.connect(statuses.append)
c.start()
T0 = time.time()
QTimer.singleShot(45_000, lambda: (c.set_window_active(False), print("-> switched to tray mode")))
QTimer.singleShot(90_000, app.quit)
app.exec()


def stats(a, b):
    xs = [s for s in stamps if a <= s - T0 < b]
    gaps = [y - x for x, y in zip(xs, xs[1:])]
    return f"{len(xs)} replies, avg gap {sum(gaps) / len(gaps):.2f}s, max gap {max(gaps):.2f}s" if gaps else f"{len(xs)} replies"


print("fast phase (5-45 s):", stats(5, 45))
print("tray phase (55-90 s):", stats(55, 90))
print("statuses seen:", sorted(set(statuses)))
c.shutdown()
