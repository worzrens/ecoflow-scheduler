"""Settings and the outage schedule shared between installs through the same store as the history (see sync.py).

Each install publishes up to three files in its own folder:
  settings.json  {"v": 1, "sections": {name: {"at": epoch, "by": device, "value": ...}}}
  schedule.json  {"v": 1, "regions": {region: {day: {"u": published, "g": {group: 24 state letters}}}}}
  marks.json     {"v": 1, "marks": [{"start", "end", "kind": grid|outage|clear, "at", "by"}]}  (made on that install)
Settings are "newest change wins" per section. A section that was never changed has at = 0 and never overrides anyone.
No credentials are ever part of these files.
"""
from __future__ import annotations

import json
import time

from .power import MARK_KINDS
from .rules import RulesConfig
from .schedule import GROUPS, REGIONS

SETTINGS_FILE = "settings.json"
SCHEDULE_FILE = "schedule.json"
MARKS_FILE = "marks.json"
SECTIONS = ("rules", "temporary", "automation", "outage")
SCHEDULE_DAYS = 15            # how far back the shared schedule file reaches
STATE_KEY = "shared:state"
CLOCK_SLACK = 300             # a change stamped further in the future than this is treated as "now"


def current_values(rules: RulesConfig, region: str, group: str) -> dict:
    d = rules.to_dict()
    return {"rules": {k: d[k] for k in ("default_watts", "schedule", "dynamic")},
            "temporary": d["temporary"], "automation": d["automation_enabled"],
            "outage": {"region": region, "group": group}}


def _norm(name: str, value, now: float):
    """An expired temporary rule equals no temporary rule, so expiring is not a "change" that overrides others."""
    if name == "temporary" and value and value.get("until", 0) <= now:
        return None
    return value


def load_state(history) -> dict:
    try:
        return json.loads(history.meta_get(STATE_KEY) or "{}")
    except ValueError:
        return {}


def save_state(history, state: dict) -> None:
    history.meta_set(STATE_KEY, json.dumps(state))


def note_changes(history, values: dict, by: str, now: float | None = None, first_seen: dict | None = None) -> dict:
    """Stamp the sections that differ from what was last known. `first_seen[name]` is the change time to assume when a
    section is seen for the first time (the settings file's time, so that the most recently saved install wins);
    0 / missing = never changed here."""
    now = now or time.time()
    state = load_state(history)
    changed = False
    for name in SECTIONS:
        value = values[name]
        old = state.get(name)
        if old is None:
            state[name] = {"at": float((first_seen or {}).get(name, 0)), "by": by, "value": value}
            changed = True
        elif _norm(name, old["value"], now) != _norm(name, value, now):
            state[name] = {"at": now, "by": by, "value": value}
            changed = True
    if changed:
        save_state(history, state)
    return state


def valid_value(name: str, value) -> bool:
    try:
        if name == "automation":
            return isinstance(value, bool)
        if name == "outage":
            return value["region"] in ("", *REGIONS) and value["group"] in ("", *GROUPS)
        if name == "temporary":
            return value is None or (isinstance(value["watts"], int) and float(value["until"]) > 0)
        if name == "rules":
            r = RulesConfig.from_dict(value)
            for e in r.schedule:
                e.active_at(__import__("datetime").datetime.now())      # raises on malformed times
            r.dynamic.levels()
            return isinstance(value["default_watts"], int)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    return False


def newer_sections(state: dict, docs: list[dict], now: float | None = None) -> dict:
    """{section: entry} that some other install changed more recently than what we have (newest wins)."""
    now = now or time.time()
    out: dict = {}
    for doc in docs:
        sections = doc.get("sections") if isinstance(doc, dict) else None
        if not isinstance(sections, dict):
            continue
        for name in SECTIONS:
            e = sections.get(name)
            if not isinstance(e, dict) or not isinstance(e.get("at"), (int, float)) or e["at"] <= 0:
                continue
            at = min(float(e["at"]), now + CLOCK_SLACK)
            best = out.get(name) or state.get(name) or {"at": 0}
            if at > best["at"] and valid_value(name, e.get("value")):
                out[name] = {"at": at, "by": str(e.get("by", "another device")), "value": e.get("value")}
    return out


def apply_to_rules(rules: RulesConfig, sections: dict) -> RulesConfig:
    d = rules.to_dict()
    if "rules" in sections:
        d.update(sections["rules"]["value"])
    if "temporary" in sections:
        t = sections["temporary"]["value"]
        d["temporary"] = t if t and t["until"] > time.time() else None
    if "automation" in sections:
        d["automation_enabled"] = sections["automation"]["value"]
    return RulesConfig.from_dict(d)


def settings_doc(state: dict) -> bytes:
    return json.dumps({"v": 1, "sections": state}, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------- outage schedule
def _published(u: str) -> tuple:
    """Sort key of DTEK's "dd.mm.yyyy HH:MM" publication stamp (unknown format = oldest)."""
    try:
        return tuple(time.strptime(u.strip(), "%d.%m.%Y %H:%M"))[:5]
    except (ValueError, AttributeError):
        return (0,)


def schedule_doc(history, now: float | None = None) -> bytes:
    regions: dict = {}
    for region, day, grp, hours, updated in history.schedule_rows((now or time.time()) - SCHEDULE_DAYS * 86400):
        entry = regions.setdefault(region, {}).setdefault(str(day), {"u": updated, "g": {}})
        entry["g"][grp] = hours
        if _published(updated) > _published(entry["u"]):
            entry["u"] = updated
    return json.dumps({"v": 1, "regions": regions}, sort_keys=True, separators=(",", ":")).encode("utf-8")


def apply_schedule(history, data: bytes) -> int:
    """Take over another install's schedule days that we lack or that were published more recently."""
    doc = json.loads(data)
    have = {(r, d, g): u for r, d, g, _h, u in history.schedule_rows(0)}
    new: list[tuple] = []
    for region, days in (doc.get("regions") or {}).items():
        if region not in REGIONS:
            continue
        for day, entry in days.items():
            u = str(entry.get("u", ""))
            for grp, hours in (entry.get("g") or {}).items():
                if grp not in GROUPS or not isinstance(hours, str) or len(hours) != 24:
                    continue
                old = have.get((region, int(day), grp))
                if old is None or _published(u) > _published(old):
                    new.append((region, int(day), grp, hours, u))
    history.schedule_put_rows(new)
    return len(new)


# ---------------------------------------------------------------- manual marks of stretches without data
def marks_doc(history) -> bytes | None:
    """The marks made on this install, or None when there are none (nothing to publish)."""
    marks = [{"start": a, "end": b, "kind": k, "at": at, "by": by} for a, b, k, at, by in history.marks(own_only=True)]
    if not marks:
        return None
    return json.dumps({"v": 1, "marks": marks}, sort_keys=True, separators=(",", ":")).encode("utf-8")


def apply_marks_doc(history, data: bytes, now: float | None = None) -> int:
    """Take over another install's marks. Returns how many were new."""
    now = now or time.time()
    rows = []
    for m in json.loads(data).get("marks") or []:
        try:
            a, b, kind, at = int(m["start"]), int(m["end"]), m["kind"], float(m["at"])
            if kind in MARK_KINDS and 0 < a < b and b - a <= 31 * 86400 and at > 0:
                rows.append((a, b, kind, min(at, now + CLOCK_SLACK), str(m.get("by", "another device"))))
        except (KeyError, TypeError, ValueError):
            continue
    return history.add_marks(rows, own=False)
