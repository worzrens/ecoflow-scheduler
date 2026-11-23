"""Applies the rules: compares the desired limit with the device's and sends changes."""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from .api import EcoflowClient, Telemetry
from .rules import RulesConfig, describe_rules, effective_watts
from .settings import save_rules

RESEND_AFTER = 90  # seconds before re-sending the same command
GUARD_MAX_SENDS = 4    # more than this many commands ...
GUARD_WINDOW = 600     # ... within this many seconds => another controller is probably fighting us


class RuleEngine(QObject):
    changed = Signal(int, str)   # effective watts, reason
    guard = Signal(str)          # conflict guard tripped (automation paused until rules are saved again)

    def __init__(self, client: EcoflowClient | None, rules: RulesConfig):
        super().__init__()
        self.client = client
        self.rules = rules
        self.last: Telemetry | None = None
        self._below = 0
        self._sent: tuple[int, float] | None = None
        self._sends: deque[float] = deque()
        self.guard_tripped = False
        self.effective = (rules.default_watts, "Default")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.evaluate)
        self._timer.start(15_000)

    def set_rules(self, rules: RulesConfig, persist: bool = True):
        self.rules = rules
        if persist:
            save_rules(rules)
        self._sent = None
        self._sends.clear()
        self.guard_tripped = False  # the user acted: resume
        self.evaluate()

    def describe(self):
        return describe_rules(self.rules, datetime.now(), self.last.soc if self.last else None, self._below,
                              self.last.cfg_limit if self.last else None)

    def on_telemetry(self, t: Telemetry):
        self.last = t
        self.evaluate()

    def evaluate(self):
        r = self.rules
        if r.temporary and time.time() >= r.temporary.until:
            r.temporary = None
            save_rules(r)
        soc = self.last.soc if self.last else None
        cur = self.last.cfg_limit if self.last else None
        w, reason, self._below = effective_watts(r, datetime.now(), soc, self._below, cur)
        if (w, reason) != self.effective:
            self.effective = (w, reason)
            self.changed.emit(w, reason)
        if not (r.automation_enabled and self.client and self.last):
            return
        if self.last.cfg_limit == w:
            self._sent = None
            return
        if self._sent and self._sent[0] == w and time.time() - self._sent[1] < RESEND_AFTER:
            return
        if self.guard_tripped:
            return
        now = time.time()
        while self._sends and now - self._sends[0] > GUARD_WINDOW:
            self._sends.popleft()
        if len(self._sends) >= GUARD_MAX_SENDS:
            self.guard_tripped = True
            self.guard.emit(f"Sent {len(self._sends)} commands in {GUARD_WINDOW // 60} min - another controller "
                            "(second PC or the phone app) may be changing the limit. Automation paused; "
                            "press Save & apply to resume.")
            return
        if self.client.set_ac_limit(w):
            self._sent = (w, now)
            self._sends.append(now)
