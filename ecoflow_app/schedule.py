"""Planned (scheduled) outages published by the regional distribution company, for the "expected vs real" graphs.

Source (verified): the public page https://www.dtek-oem.com.ua/ua/shutdowns embeds the schedule of all 12 queues
("groups") as JavaScript objects `DisconSchedule.fact` / `DisconSchedule.preset`. No login or key is needed.
  fact.data["<unix midnight Kyiv>"]["GPV4.1"]["1".."24"] = state of that hour (key h = hour h-1 .. h):
     yes (power on) | no (off) | first / second (off the first / second 30 min) | maybe / mfirst / msecond (possible)
The site only serves today (and tomorrow once published) - never yesterday - so the app saves every day it sees.
The other DTEK regional sites answer plain requests with a bot-protection page, so only Odesa is supported for now.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import requests

from .power import Segment, merge_same_kind, slice_segments

REGIONS = {"odesa": ("Odesa - DTEK Odesa electric networks", "https://www.dtek-oem.com.ua/ua/shutdowns")}
GROUPS = [f"{a}.{b}" for a in range(1, 7) for b in (1, 2)]      # 1.1 ... 6.2
FETCH_EVERY = 600             # schedules get revised during the day; one page download every 10 minutes is gentle enough
KEEP_DAYS = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppData/ecoflow-scheduler Chrome/124.0 Safari/537.36",
           "Accept-Language": "uk"}

STATE_CODE = {"yes": "Y", "no": "N", "first": "F", "second": "S", "maybe": "M", "mfirst": "G", "msecond": "H"}
# per half hour slot (first 30 min, second 30 min): grid = power on, outage = planned off, maybe = possible off
SLOTS = {"Y": ("grid", "grid"), "N": ("outage", "outage"), "F": ("outage", "grid"), "S": ("grid", "outage"),
         "M": ("maybe", "maybe"), "G": ("maybe", "grid"), "H": ("grid", "maybe")}


class ScheduleError(OSError):
    pass


class Blocked(ScheduleError):
    """The site answered with its bot-protection page (needs a human) - retrying soon only makes it worse."""


@dataclass
class ScheduleData:
    update: str = ""                                             # "21.11.2026 12:51" as published
    days: dict[int, dict[str, str]] = field(default_factory=dict)   # day (unix midnight) -> {"4.1": 24 state letters}


def _grab(html: str, name: str):
    m = re.search(r"DisconSchedule\." + name + r"\s*=\s*", html)
    if not m:
        raise ScheduleError("The schedule is missing from the page (bot protection, or the site changed).")
    obj, _ = json.JSONDecoder().raw_decode(html, m.end())
    return obj


def parse_page(html: str) -> ScheduleData:
    return parse_fact(_grab(html, "fact"))


def parse_text(text: str) -> ScheduleData:
    """Schedule pasted/sent from the user's own browser: the JSON of DisconSchedule.fact (or the whole page)."""
    text = text.strip()
    if "DisconSchedule." in text:
        return parse_page(text)
    try:
        obj = json.loads(text)
    except ValueError:
        if "<html" in text[:2000].lower() or "<!doctype" in text[:200].lower():
            raise ScheduleError(f"That is a web page ({len(text) // 1024} KB) without the schedule in it "
                                "(no 'DisconSchedule' text). The site may load the schedule only after an address is chosen.") from None
        raise ScheduleError("That is not the schedule JSON.") from None
    if isinstance(obj, dict) and isinstance(obj.get("fact"), dict):
        obj = obj["fact"]
    return parse_fact(obj)


def parse_fact(fact) -> ScheduleData:
    if not isinstance(fact, dict) or not isinstance(fact.get("data"), dict):
        raise ScheduleError("That is not the schedule JSON.")
    out = ScheduleData(update=str(fact.get("update", "")))
    for ts, groups in (fact.get("data") or {}).items():
        day: dict[str, str] = {}
        for gkey, hours in groups.items():
            grp = gkey.removeprefix("GPV")
            day[grp] = "".join(STATE_CODE.get(hours.get(str(h)), "Y") for h in range(1, 25))
        out.days[int(ts)] = day
    if not out.days:
        raise ScheduleError("The page has no schedule data.")
    return out


def fetch(region: str, session=None) -> ScheduleData:
    if region not in REGIONS:
        raise ScheduleError(f"Unknown region {region!r}")
    url = REGIONS[region][1]
    r = (session or requests).get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        raise ScheduleError(f"The site answered HTTP {r.status_code}")
    html = r.content.decode("utf-8", "replace")
    if "DisconSchedule.fact" not in html and ("Incapsula" in html or "_Incap" in html):
        raise Blocked("The site asks for a human check (bot protection) - open the page in your browser (buttons below).")
    return parse_page(html)


BOOKMARKLET = (
    "javascript:(async()=>{let t;const f=typeof DisconSchedule!=='undefined'&&DisconSchedule.fact;"
    "try{t=f?JSON.stringify(f):await(await fetch(location.href,{credentials:'include'})).text()}"
    "catch(e){t=document.documentElement.outerHTML}"
    "try{const r=await fetch('http://127.0.0.1:%d/schedule',{method:'POST',body:t});"
    "alert(await r.text())}catch(e){try{await navigator.clipboard.writeText(t);"
    "alert('The browser blocked sending to the app. Schedule copied instead: in the app press Paste from clipboard.')}"
    "catch(_){prompt('Copy this, then paste it in the app:',t.slice(0,100000))}}})()")
IMPORT_PORT = 47321
USERSCRIPT_PATH = "/ecoflow-dtek.user.js"

# Installed once in Tampermonkey / Violentmonkey: runs on every visit of the DTEK page and hands the schedule to the app.
# GM_xmlhttpRequest is sent by the extension, so the browser's cross-site / local-network blocking does not apply.
USERSCRIPT = r"""// ==UserScript==
// @name         EcoFlow Scheduler - send the DTEK outage schedule
// @namespace    ecoflow-scheduler
// @version      1.0
// @description  Sends the schedule shown on this page to the EcoFlow Scheduler app on this computer.
// @match        https://www.dtek-oem.com.ua/*
// @match        https://dtek-oem.com.ua/*
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @connect      127.0.0.1
// @run-at       document-idle
// @noframes
// ==/UserScript==
(function () {
  'use strict';
  if (!location.pathname.includes('shutdowns')) return;

  function find() {
    // 1) the inline script that carries the data
    for (const s of document.scripts) {
      if (/DisconSchedule\.fact\s*=/.test(s.textContent)) return s.textContent;
    }
    // 2) the live page variable
    try {
      const t = unsafeWindow.eval("typeof DisconSchedule !== 'undefined' && DisconSchedule.fact ? JSON.stringify(DisconSchedule.fact) : ''");
      if (t) return t;
    } catch (e) { /* the page forbids eval */ }
    return '';
  }

  function toast(text, ok) {
    const d = document.createElement('div');
    d.textContent = text;
    d.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:420px;padding:12px 16px;' +
      'border-radius:10px;font:14px sans-serif;box-shadow:0 4px 18px rgba(0,0,0,.35);background:#17191e;color:' +
      (ok ? '#2ee68a' : '#ff8a80');
    document.body.appendChild(d);
    setTimeout(() => d.remove(), 8000);
  }

  let tries = 0;
  (function attempt() {
    const body = find();
    if (!body) {
      // a security check page never has data: stay quiet there, the script runs again once the real page loads
      if (++tries < 20) setTimeout(attempt, 1000);
      else if (document.getElementById('discon_form')) toast('EcoFlow Scheduler: no schedule found on this page', false);
      return;
    }
    GM_xmlhttpRequest({
      method: 'POST',
      url: 'http://127.0.0.1:__PORT__/schedule',
      data: body,
      timeout: 10000,
      onload: r => toast('EcoFlow Scheduler: ' + r.responseText, r.status === 200),
      onerror: () => toast('EcoFlow Scheduler is not running on this computer', false),
      ontimeout: () => toast('EcoFlow Scheduler did not answer', false)
    });
  })();
})();
""".replace("__PORT__", str(IMPORT_PORT))


# ---------------------------------------------------------------- hours -> segments
def day_segments(day_ts: int, hours: str) -> list[Segment]:
    slots = [k for c in hours for k in SLOTS.get(c, SLOTS["Y"])]
    return merge_same_kind([Segment(day_ts + i * 1800, day_ts + (i + 1) * 1800, k) for i, k in enumerate(slots)])


def build_segments(days: dict[int, str], t0: float, t1: float) -> list[Segment]:
    """Expected timeline over [t0, t1]: planned outages / possible outages / power on, 'nodata' where no schedule was saved."""
    segs: list[Segment] = []
    for day_ts in sorted(days):
        segs += day_segments(day_ts, days[day_ts])
    known = slice_segments(merge_same_kind(segs), t0, t1)
    out: list[Segment] = []
    cursor = t0
    for s in known:
        if s.start - cursor > 1:
            out.append(Segment(cursor, s.start, "nodata"))
        out.append(s)
        cursor = s.end
    if t1 - cursor > 1:
        out.append(Segment(cursor, t1, "nodata"))
    return merge_same_kind(out)


def seconds_of(segs: list[Segment], kind: str) -> float:
    return sum(s.seconds for s in segs if s.kind == kind)


def count_of(segs: list[Segment], kind: str) -> int:
    return sum(1 for s in segs if s.kind == kind)


@dataclass
class ScheduleResult:
    at: float = 0.0
    update: str = ""
    days: int = 0
    has_today: bool = False
    has_tomorrow: bool = False
    error: str = ""
    source: str = "site"

    def text(self) -> str:
        when = time.strftime("%H:%M", time.localtime(self.at))
        if self.error:
            return f"Schedule fetch failed at {when}: {self.error}"
        have = ("today and tomorrow" if self.has_tomorrow else "today") if self.has_today else \
            ("tomorrow only" if self.has_tomorrow else "no days")
        tail = "" if self.has_tomorrow else " (tomorrow is not published yet)"
        return f"Schedule {'imported from browser' if self.source == 'browser' else 'fetched'} {when} \u00b7 published {self.update} \u00b7 page has {have}{tail}"
