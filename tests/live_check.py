"""Live read-only check against the real unit (temp data dir, no keyring, automation off)."""
import os
import sys
import tempfile

os.environ["APPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ecoflow_app.settings as st  # noqa: E402
st.keyring = None
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ecoflow_app.controller import Controller  # noqa: E402
from ecoflow_app.tray import tooltip_text  # noqa: E402

app = QApplication([])
c = Controller()
assert not c.engine.rules.automation_enabled, "automation must start disabled"
c.status.connect(lambda s: print("status:", s))
c.telemetry.connect(lambda t: print(f"telemetry: soc={t.soc:.1f}% in={t.in_w}W out={t.out_w}W limit={t.cfg_limit}W "
                                    f"dsg={t.dsg_min}min chg={t.chg_min}min temp={t.temp}"))
c.start()
QTimer.singleShot(28000, app.quit)
app.exec()
print("tooltip:", tooltip_text(c).replace("\n", " // "))
print("samples stored:", len(c.history.range(0)))
c.shutdown()
