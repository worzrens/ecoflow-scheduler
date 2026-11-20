"""Pure rule logic: decides the AC charging limit. No Qt, no network."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time

MIN_W, MAX_W = 200, 2900
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def clamp(w: int) -> int:
    return max(MIN_W, min(MAX_W, int(w)))


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass
class ScheduleEntry:
    start: str = "23:00"
    end: str = "09:00"
    watts: int = 300
    days: list[int] = field(default_factory=lambda: list(range(7)))  # 0=Mon
    enabled: bool = True

    def active_at(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        s, e, t = parse_hhmm(self.start), parse_hhmm(self.end), now.time()
        wd = now.weekday()
        if s == e:
            return False
        if s < e:  # same-day window
            return wd in self.days and s <= t < e
        # window crosses midnight; "days" is the day the window starts on
        if t >= s:
            return wd in self.days
        if t < e:
            return (wd - 1) % 7 in self.days
        return False


@dataclass
class Temporary:
    watts: int
    until: float  # epoch seconds


@dataclass
class Dynamic:
    enabled: bool = True
    soc_threshold: int = 85
    watts_below: int = 1200  # used while SOC < threshold
    watts_above: int = 300  # used once SOC >= threshold
    hysteresis: int = 2


@dataclass
class RulesConfig:
    automation_enabled: bool = True
    default_watts: int = 1200
    schedule: list[ScheduleEntry] = field(default_factory=lambda: [ScheduleEntry()])  # 23:00-09:00 @ 300 W
    dynamic: Dynamic = field(default_factory=Dynamic)
    temporary: Temporary | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "RulesConfig":
        t = d.get("temporary")
        return RulesConfig(
            automation_enabled=d.get("automation_enabled", True),
            default_watts=d.get("default_watts", 1200),
            schedule=[ScheduleEntry(**e) for e in d.get("schedule", [])],
            dynamic=Dynamic(**d.get("dynamic", {})),
            temporary=Temporary(**t) if t else None,
        )


def effective_watts(cfg: RulesConfig, now: datetime, soc: float | None,
                    below_state: bool = False, cur_limit: int | None = None) -> tuple[int, str, bool]:
    """Priority: temporary > schedule (first match) > dynamic > default.

    Returns (watts, reason, new_below_state). Inside the hysteresis band the dynamic rule keeps
    whatever the DEVICE is currently doing (cur_limit), so several controllers with equal rules
    agree without sharing any state; below_state is only the fallback when the device value is
    neither of the two dynamic watts.
    """
    d = cfg.dynamic
    if d.enabled and soc is not None:
        if soc < d.soc_threshold:
            below_state = True
        elif soc >= d.soc_threshold + d.hysteresis:
            below_state = False
        elif cur_limit is not None:  # inside the band: follow the device, not local memory
            lo_w, hi_w = clamp(d.watts_below), clamp(d.watts_above)
            if cur_limit == lo_w and cur_limit != hi_w:
                below_state = True
            elif cur_limit == hi_w and cur_limit != lo_w:
                below_state = False

    if cfg.temporary and now.timestamp() < cfg.temporary.until:
        return clamp(cfg.temporary.watts), "Temporary rule", below_state
    for e in cfg.schedule:
        if e.active_at(now):
            return clamp(e.watts), f"Schedule {e.start}-{e.end}", below_state
    if d.enabled and soc is not None:
        w = d.watts_below if below_state else d.watts_above
        return clamp(w), f"Dynamic (SOC {'<' if below_state else '>='} {d.soc_threshold}%)", below_state
    return clamp(cfg.default_watts), "Default", below_state


def short_reason(reason: str) -> str:
    """Compact label with an icon for the rule that is applied (used in the Input card and tooltip)."""
    if reason.startswith("Temporary"):
        return "\u23f1 Temporary"
    if reason.startswith("Schedule"):
        return "\U0001F552 " + reason.replace("Schedule ", "").replace("-", "\u2013")
    if reason.startswith("Dynamic"):
        import re
        m = re.search(r"SOC (<|>=) (\d+)%", reason)
        if m:
            return f"\U0001F50B {'<' if m.group(1) == '<' else chr(0x2265)}{m.group(2)}%"
        return "\U0001F50B Dynamic"
    return "\u2699 Default"


def describe_rules(cfg: RulesConfig, now: datetime, soc: float | None, below_state: bool = False,
                   cur_limit: int | None = None) -> list[tuple[str, str, bool]]:
    """Explain every rule level as compact HTML: [(title, detail, is_applied)] in priority order."""
    applied_w, applied_reason, below_state = effective_watts(cfg, now, soc, below_state, cur_limit)
    rows: list[tuple[str, str, bool]] = []
    t = cfg.temporary
    if t and now.timestamp() < t.until:
        until = datetime.fromtimestamp(t.until).strftime("%H:%M")
        rows.append(("\u23f1 Temporary", f"{clamp(t.watts)} W until {until}", applied_reason == "Temporary rule"))
    else:
        rows.append(("\u23f1 Temporary", "not set", False))
    if cfg.schedule:
        parts = []
        for e in cfg.schedule:
            state = "off" if not e.enabled else ("<b>active</b>" if e.active_at(now) else "not now")
            days = "daily" if len(e.days) == 7 else ",".join(DAY_NAMES[i][:2] for i in sorted(e.days)) or "no days"
            parts.append(f"{e.start}\u2013{e.end} {days} \u2192 {clamp(e.watts)} W &middot; {state}")
        rows.append(("\U0001F552 Schedule", "<br>".join(parts), applied_reason.startswith("Schedule")))
    else:
        rows.append(("\U0001F552 Schedule", "no windows", False))
    d = cfg.dynamic
    if d.enabled:
        now_txt = "no reading yet" if soc is None else (
            f"now {soc:.0f}% \u2192 {d.watts_below if below_state else d.watts_above} W")
        rows.append(("\U0001F50B Dynamic",
                     f"&lt;{d.soc_threshold}% \u2192 {d.watts_below} W &middot; "
                     f"&ge;{d.soc_threshold}% \u2192 {d.watts_above} W<br>{now_txt}",
                     applied_reason.startswith("Dynamic")))
    else:
        rows.append(("\U0001F50B Dynamic", "off", False))
    rows.append(("\u2699 Default", f"{clamp(cfg.default_watts)} W", applied_reason == "Default"))
    return rows
