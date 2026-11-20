"""Two app instances with equal rules must agree and must not fight over the limit."""
import random
import time
from datetime import datetime

from PySide6.QtCore import QCoreApplication

from ecoflow_app import engine as engine_mod
from ecoflow_app.api import Telemetry
from ecoflow_app.rules import Dynamic, RulesConfig, effective_watts

NOON = datetime(2026, 11, 21, 12, 0)
RULES = RulesConfig(default_watts=1200, schedule=[], dynamic=Dynamic(True, 85, 1200, 300, hysteresis=2))


def test_band_follows_device_not_local_memory():
    # soc inside the 85..87 band: whatever the device does is kept, regardless of each copy's own state
    for cur, want in ((1200, 1200), (300, 300)):
        for local_below in (True, False):
            w, _, _ = effective_watts(RULES, NOON, 86.0, local_below, cur)
            assert w == want, (cur, local_below, w)


def test_two_controllers_never_flip_flop_in_band():
    random.seed(1)
    for start_limit in (1200, 300):
        limit = start_limit
        memory = [True, False]            # deliberately different local state on the two "PCs"
        changes = 0
        for _ in range(500):
            soc = random.uniform(85.3, 86.6)   # whole time inside the hysteresis band (even with jitter)
            for i in (0, 1):                   # each copy reads the same device value, then maybe sends
                w, _, memory[i] = effective_watts(RULES, NOON, soc + random.uniform(-0.05, 0.05), memory[i], limit)
                if w != limit:
                    limit, changes = w, changes + 1
        assert changes == 0, f"flip-flop: {changes} changes starting from {start_limit} W"


def test_two_controllers_converge_across_threshold():
    random.seed(2)
    limit, memory, changes = 300, [False, False], 0
    socs = [90, 88, 86, 85.5, 84.9, 84, 85.2, 86, 86.9, 87.1, 88, 90]  # dips below 85 then recovers
    for soc in socs:
        for _ in range(3):  # a few polls per level, copies slightly out of step
            for i in (0, 1):
                w, _, memory[i] = effective_watts(RULES, NOON, soc + random.uniform(-0.03, 0.03), memory[i], limit)
                if w != limit:
                    limit, changes = w, changes + 1
    assert limit == 300
    assert changes == 2, changes     # one drop to 1200 when below 85, one return to 300 above 87 - no extra flips


class FakeClient:
    def __init__(self):
        self.sent = []

    def set_ac_limit(self, w):
        self.sent.append(w)
        return True


def telemetry(limit):
    return Telemetry(time.time(), 90.0, 300, 250, 300, 250, limit, 28, 1000, 0)


def test_conflict_guard_pauses_after_repeated_commands(monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(engine_mod, "RESEND_AFTER", 0)
    fake = FakeClient()
    rules = RulesConfig(automation_enabled=True, default_watts=500, schedule=[], dynamic=Dynamic(enabled=False))
    eng = engine_mod.RuleEngine(fake, rules)
    tripped = []
    eng.guard.connect(tripped.append)
    eng.last = telemetry(1200)            # someone else keeps the device at 1200 W
    for _ in range(8):
        eng.evaluate()
    assert len(fake.sent) == engine_mod.GUARD_MAX_SENDS
    assert eng.guard_tripped and len(tripped) == 1
    eng.set_rules(rules, persist=False)   # user presses Save & apply -> resume (evaluates immediately)
    assert not eng.guard_tripped
    assert len(fake.sent) == engine_mod.GUARD_MAX_SENDS + 1


def test_no_command_when_device_already_matches(monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    fake = FakeClient()
    rules = RulesConfig(automation_enabled=True, default_watts=500, schedule=[], dynamic=Dynamic(enabled=False))
    eng = engine_mod.RuleEngine(fake, rules)
    eng.last = telemetry(500)
    for _ in range(5):
        eng.evaluate()
    assert fake.sent == []
