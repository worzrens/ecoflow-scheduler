"""Render assets/app.icns from the app icon (macOS only: uses `iconutil`). Run from anywhere."""
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from ecoflow_app.tray import app_pixmap  # noqa: E402

app = QApplication([])
iconset = ROOT / "assets" / "app.iconset"
iconset.mkdir(parents=True, exist_ok=True)
for base in (16, 32, 128, 256, 512):
    app_pixmap(base).save(str(iconset / f"icon_{base}x{base}.png"))
    app_pixmap(base * 2).save(str(iconset / f"icon_{base}x{base}@2x.png"))
subprocess.check_call(["iconutil", "-c", "icns", str(iconset), "-o", str(ROOT / "assets" / "app.icns")])
print("wrote assets/app.icns")
