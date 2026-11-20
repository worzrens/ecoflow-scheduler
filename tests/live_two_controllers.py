"""LIVE: two independent controllers (two cloud sessions, own rule engines) with EQUAL rules on the real unit.

Changes the real limit during the test and restores it. Temp data dir, no keyring.
Checks: both see the device, both converge, no command storm / flip-flop, divergent dynamic memory is harmless.
"""
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
from ecoflow_app.api import EcoflowClient  # noqa: E402
from ecoflow_app.engine import RuleEngine  # noqa: E402
from ecoflow_app.rules import Dynamic, RulesConfig  # noqa: E402

app = QApplication([])
s = st.load_settings()
T0 = time.time()
HOLD = 40


def log(m):
    print(f"[{time.time() - T0:4.0f}s] {m}", flush=True)


class Node:
    def __init__(self, name):
        self.name = name
        self.client = EcoflowClient(s.api_host, s.email, s.password, s.sn)
        self.sends = []
        orig = self.client.set_ac_limit
        self.client.set_ac_limit = lambda w, _o=orig, _n=self: (_n.sends.append((time.time() - T0, w)), _o(w))[1]
        self.engine = RuleEngine(self.client, RulesConfig(automation_enabled=False))
        self.client.telemetry.connect(self.engine.on_telemetry)

    @property
    def limit(self):
        return self.engine.last.cfg_limit if self.engine.last else None


A, B = Node("A"), Node("B")
A.client.start()
B.client.start()
results = []
ph = {"i": -1, "t": 0.0, "mark": (0, 0), "orig": None, "hold_until": 0.0}


def eq(w, soc_dyn=None):
    return RulesConfig(True, w, [], soc_dyn or Dynamic(enabled=False), None)


def total():
    return len(A.sends) + len(B.sends)


def phases():
    soc = A.engine.last.soc
    o = ph["orig"]
    return [
        # (name, setup, expected limit, hold-check)
        (f"equal rules: default 350 W on both", lambda: (A.engine.set_rules(eq(350), False), B.engine.set_rules(eq(350), False)), 350),
        (f"equal dynamic rules, battery {soc:.0f}% < 100% -> 450 W on both",
         lambda: (A.engine.set_rules(eq(300, Dynamic(True, 100, 450, 380)), False),
                  B.engine.set_rules(eq(300, Dynamic(True, 100, 450, 380)), False)), 450),
        ("divergent local dynamic memory (A below, B above) inside the band: must stay 450 W, no commands",
         lambda: (setattr(A.engine, "_below", True), setattr(B.engine, "_below", False),
                  A.engine.set_rules(eq(300, Dynamic(True, 98, 450, 380, 3)), False),
                  B.engine.set_rules(eq(300, Dynamic(True, 98, 450, 380, 3)), False)), 450),
        (f"restore original {o} W on both", lambda: (A.engine.set_rules(eq(o), False), B.engine.set_rules(eq(o), False)), o),
    ]


plan = []


def start_phase():
    ph["i"] += 1
    if ph["i"] >= len(plan):
        return finish()
    name, setup, want = plan[ph["i"]]
    ph.update(t=time.time(), mark=(len(A.sends), len(B.sends)), want=want, state="wait", name=name)
    setup()
    log(f"PHASE {ph['i'] + 1}/{len(plan)}: {name}  (expect {want} W)")


def tick():
    if ph["orig"] is None:
        if A.engine.last and B.engine.last:
            ph["orig"] = A.limit
            log(f"both connected; battery {A.engine.last.soc:.1f}%; device limit {A.limit} W (A) / {B.limit} W (B)")
            plan.extend(phases())
            start_phase()
        elif time.time() - T0 > 60:
            log("FAIL: a controller got no telemetry")
            app.quit()
        return
    if ph.get("state") == "wait":
        if A.limit == ph["want"] and B.limit == ph["want"]:
            ph.update(state="hold", hold_until=time.time() + HOLD, took=time.time() - ph["t"])
            log(f"  both report {ph['want']} W after {ph['took']:.0f}s; holding {HOLD}s to watch for interference")
        elif time.time() - ph["t"] > 70:
            results.append((ph["name"], False, f"timeout: A={A.limit} B={B.limit}"))
            log(f"  FAIL timeout: A={A.limit} B={B.limit}")
            ph["state"] = "done"
            QTimer.singleShot(300, start_phase if "restore" in ph["name"] else lambda: (ph.update(i=len(plan) - 2), start_phase()))
    elif ph.get("state") == "hold" and time.time() >= ph["hold_until"]:
        sa, sb = len(A.sends) - ph["mark"][0], len(B.sends) - ph["mark"][1]
        stable = A.limit == ph["want"] and B.limit == ph["want"]
        # each node may send at most once (idempotent, same value); more would mean fighting
        ok = stable and sa <= 1 and sb <= 1
        vals = sorted({w for _, w in A.sends[ph["mark"][0]:] + B.sends[ph["mark"][1]:]})
        results.append((ph["name"], ok, f"sends A={sa} B={sb} values={vals}, stable={stable}"))
        log(f"  {'PASS' if ok else 'FAIL'}: sends A={sa} B={sb} values={vals}, still {A.limit}/{B.limit} W")
        ph["state"] = "done"
        QTimer.singleShot(300, start_phase)


def finish():
    log("SUMMARY")
    for n, ok, d in results:
        print(f"   {'PASS' if ok else 'FAIL'}  {n}\n         {d}")
    log(f"total commands sent: A={len(A.sends)} B={len(B.sends)}; guard tripped: A={A.engine.guard_tripped} B={B.engine.guard_tripped}")
    app.quit()


t = QTimer()
t.timeout.connect(tick)
t.start(500)
QTimer.singleShot(570_000, app.quit)
app.exec()
A.client.stop()
B.client.stop()
