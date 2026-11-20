"""LIVE automation test: changes the real unit's AC charging limit step by step, then restores it.

Uses a temp data dir (no keyring, no real rules.json). Run: python tests/live_automation.py
Steps: default -> schedule beats default -> temporary beats schedule and expires -> dynamic (below/above) -> restore.
"""
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

os.environ["APPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ecoflow_app.settings as st  # noqa: E402
st.keyring = None
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ecoflow_app.controller import Controller  # noqa: E402
from ecoflow_app.rules import Dynamic, RulesConfig, ScheduleEntry, Temporary  # noqa: E402

app = QApplication([])
c = Controller()
T0 = time.time()
results = []
state = {"orig": None, "i": -1, "t_step": 0.0, "pending": None}


def log(msg):
    print(f"[{time.time() - T0:5.0f}s] {msg}", flush=True)


def window_now():
    n = datetime.now()
    return ScheduleEntry((n - timedelta(minutes=1)).strftime("%H:%M"), (n + timedelta(minutes=30)).strftime("%H:%M"), 350)


def no_dyn():
    return Dynamic(enabled=False)


def steps(orig):
    soc = c.last.soc
    return [
        ("default 400 W", lambda: RulesConfig(True, 400, [], no_dyn(), None), 400),
        ("schedule window (now) 350 W beats default", lambda: RulesConfig(True, 400, [window_now()], no_dyn(), None), 350),
        ("temporary 500 W (20 s) beats schedule", lambda: RulesConfig(True, 400, [window_now()], no_dyn(),
                                                                      Temporary(500, time.time() + 20)), 500),
        ("temporary expired -> back to schedule 350 W", None, 350),
        (f"dynamic: battery {soc:.0f}% is BELOW 100% -> 450 W",
         lambda: RulesConfig(True, 300, [], Dynamic(True, 100, 450, 380), None), 450),
        (f"dynamic: battery {soc:.0f}% is ABOVE 50% -> 380 W",
         lambda: RulesConfig(True, 300, [], Dynamic(True, 50, 450, 380), None), 380),
        (f"restore original {orig} W", lambda: RulesConfig(True, orig, [], no_dyn(), None), orig),
    ]


plan = []


def advance():
    state["i"] += 1
    if state["i"] >= len(plan):
        finish()
        return
    name, make, want = plan[state["i"]]
    state["t_step"] = time.time()
    state["pending"] = (name, want)
    if make:
        c.engine.set_rules(make(), persist=False)
    log(f"STEP {state['i'] + 1}/{len(plan)}: {name}  (expect device limit {want} W)")


def poll():
    t = c.last
    if state["orig"] is None:
        if t and c.fresh:
            state["orig"] = t.cfg_limit
            plan.extend(steps(state["orig"]))
            log(f"connected; battery {t.soc:.1f}%, original limit {state['orig']} W")
            advance()
        elif time.time() - T0 > 60:
            print("FAIL: no telemetry within 60 s")
            app.quit()
        return
    if state["pending"] is None:
        return
    name, want = state["pending"]
    if t and t.cfg_limit == want:
        took = time.time() - state["t_step"]
        results.append((name, True, took))
        log(f"  PASS ({took:.0f}s) device reports {t.cfg_limit} W")
        state["pending"] = None
        QTimer.singleShot(1500, advance)
    elif time.time() - state["t_step"] > 60:
        results.append((name, False, 60))
        log(f"  FAIL: device still reports {t.cfg_limit if t else None} W, wanted {want} W")
        state["pending"] = None
        if "restore" not in name:  # always try to restore
            state["i"] = len(plan) - 2
        QTimer.singleShot(500, advance)


def finish():
    log("SUMMARY")
    for n, ok, took in results:
        print(f"   {'PASS' if ok else 'FAIL'}  {n}  ({took:.0f}s)")
    app.quit()


timer = QTimer()
timer.timeout.connect(poll)
timer.start(500)
c.start()
QTimer.singleShot(540_000, app.quit)
app.exec()
c.shutdown()
