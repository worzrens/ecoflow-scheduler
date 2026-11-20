"""EcoFlow Scheduler - Windows tray app for the EcoFlow DELTA Pro."""
import sys

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from ecoflow_app.controller import Controller
from ecoflow_app.mainwindow import MainWindow
from ecoflow_app.paths import LOCK_PATH
from ecoflow_app.tray import Tray, make_app_icon


def dark_palette(app: QApplication):
    app.setStyle("Fusion")
    p = QPalette()
    for role, color in {
        QPalette.Window: "#16181d", QPalette.WindowText: "#e5e7eb", QPalette.Base: "#1b1d23",
        QPalette.AlternateBase: "#20232a", QPalette.Text: "#e5e7eb", QPalette.Button: "#262a33",
        QPalette.ButtonText: "#e5e7eb", QPalette.Highlight: "#2563eb", QPalette.HighlightedText: "#ffffff",
        QPalette.ToolTipBase: "#262a33", QPalette.ToolTipText: "#e5e7eb",
    }.items():
        p.setColor(role, QColor(color))
    app.setPalette(p)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("EcoFlow Scheduler")
    app.setQuitOnLastWindowClosed(False)  # closing the window only hides it
    dark_palette(app)

    lock = QLockFile(str(LOCK_PATH))
    if not lock.tryLock(200):
        QMessageBox.information(None, "EcoFlow Scheduler", "Already running - look for the tray icon.")
        return 0

    ctrl = Controller()
    win = MainWindow(ctrl)
    app.setWindowIcon(make_app_icon())
    win.setWindowIcon(make_app_icon())
    tray = Tray(ctrl, win)
    app.aboutToQuit.connect(ctrl.shutdown)
    ctrl.start()
    if "--minimized" not in sys.argv or not ctrl.settings.complete:
        win.show()
    rc = app.exec()
    lock.unlock()
    return rc


if __name__ == "__main__":
    sys.exit(main())
