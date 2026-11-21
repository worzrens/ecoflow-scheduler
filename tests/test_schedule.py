"""Planned-outage schedule: parsing the page, hours -> segments, local storage, fetch errors."""
import json
import time

import pytest

from ecoflow_app import schedule
from ecoflow_app.power import outage_count
from ecoflow_app.storage import History

DAY = 1795212000          # unix midnight (Kyiv) of 2026-11-21, like the real page


def page(hours_41: dict, extra_days: dict | None = None) -> str:
    data = {str(DAY): {"GPV4.1": hours_41, "GPV1.1": {str(h): "yes" for h in range(1, 25)}}}
    data.update(extra_days or {})
    fact = {"data": data, "update": "21.11.2026 12:51", "today": DAY}
    return ("<html><script>var DisconSchedule = {}; DisconSchedule.fact = " + json.dumps(fact) +
            "; DisconSchedule.preset = {\"time_type\": {}};</script>Тест</html>")


HOURS = {str(h): "yes" for h in range(1, 25)}
HOURS.update({"1": "no", "2": "first", "11": "no", "12": "no", "13": "first", "20": "second", "21": "no", "22": "no",
              "23": "no", "24": "no"})        # the real group 4.1 data of 21.11.2026 12:51


def span(segs, kind):
    return [((s.start - DAY) / 3600, (s.end - DAY) / 3600) for s in segs if s.kind == kind]


def test_parse_page_extracts_groups_and_letters():
    d = schedule.parse_page(page(HOURS))
    assert d.update == "21.11.2026 12:51" and list(d.days) == [DAY]
    assert d.days[DAY]["4.1"] == "NFYYYYYYYYNNFYYYYYYSNNNN" and d.days[DAY]["1.1"] == "Y" * 24


def test_hours_become_half_hour_accurate_outages():
    letters = schedule.parse_page(page(HOURS)).days[DAY]["4.1"]
    segs = schedule.day_segments(DAY, letters)
    assert span(segs, "outage") == [(0, 1.5), (10, 12.5), (19.5, 24)]
    assert [s.kind for s in segs] == ["outage", "grid", "outage", "grid", "outage"]
    assert abs(schedule.seconds_of(segs, "outage") - 8.5 * 3600) < 1 and outage_count(segs) == 3


def test_possible_outages_are_their_own_kind():
    segs = schedule.day_segments(DAY, "Y" * 3 + "M" + "G" + "H" + "Y" * 18)       # maybe / maybe-first / maybe-second
    # hour 4 "maybe" (03:00-04:00) + hour 5 "mfirst" (04:00-04:30) merge; hour 6 "msecond" is 05:30-06:00
    assert span(segs, "maybe") == [(3, 4.5), (5.5, 6)]
    assert schedule.seconds_of(segs, "outage") == 0


def test_build_segments_fills_missing_days_with_nodata_and_merges_across_midnight():
    nxt = DAY + 86400
    days = {DAY: schedule.parse_page(page(HOURS)).days[DAY]["4.1"], nxt: "N" * 2 + "Y" * 22}
    segs = schedule.build_segments(days, DAY - 86400, nxt + 2 * 86400)
    assert segs[0].kind == "nodata" and (segs[0].start, segs[0].end) == (DAY - 86400, DAY)     # yesterday was not saved
    assert segs[-1].kind == "nodata" and segs[-1].end == nxt + 2 * 86400
    night = [s for s in segs if s.kind == "outage" and s.start == DAY + 19.5 * 3600][0]
    assert night.end == nxt + 2 * 3600                                                          # 19:30 -> 02:00 next day, one zone


def test_history_keeps_every_day_it_has_seen(tmp_path):
    h = History(tmp_path / "h.db")
    d = schedule.parse_page(page(HOURS))
    assert h.schedule_put("odesa", d.days, d.update) == 2                    # two groups saved
    got = h.schedule_days("odesa", "4.1", DAY, DAY + 86400)
    assert got == {DAY: "NFYYYYYYYYNNFYYYYYYSNNNN"}
    assert h.schedule_days("odesa", "4.1", DAY + 5 * 86400, DAY + 6 * 86400) == {}
    assert h.schedule_days("kyiv", "4.1", DAY, DAY + 86400) == {}            # other regions are kept apart
    later = {DAY: {"4.1": "Y" * 24}}
    h.schedule_put("odesa", later, "21.11.2026 18:00")                         # a revised schedule replaces the old one
    assert h.schedule_days("odesa", "4.1", DAY, DAY + 86400) == {DAY: "Y" * 24}


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self.content = status, body.encode("utf-8")


class FakeSession:
    def __init__(self, status, body):
        self.resp, self.calls = FakeResp(status, body), []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        return self.resp


def test_fetch_ok_blocked_and_broken_pages():
    ok = schedule.fetch("odesa", FakeSession(200, page(HOURS)))
    assert ok.days[DAY]["4.1"].startswith("NF")
    sess = FakeSession(200, page(HOURS))
    schedule.fetch("odesa", sess)
    url, headers = sess.calls[0]
    assert url == "https://www.dtek-oem.com.ua/ua/shutdowns" and headers["Accept-Language"] == "uk"
    challenge = '<html><script src="/_Incapsula_Resource?SWJIYLWA=1"></script></html>'     # what the other DTEK sites answer
    with pytest.raises(schedule.ScheduleError, match="bot protection"):
        schedule.fetch("odesa", FakeSession(200, challenge))
    with pytest.raises(schedule.ScheduleError, match="HTTP 503"):
        schedule.fetch("odesa", FakeSession(503, ""))
    with pytest.raises(schedule.ScheduleError, match="Unknown region"):
        schedule.fetch("moon")
    assert isinstance(schedule.ScheduleError("x"), OSError)                    # so workers catch it with network errors


def test_groups_and_regions_listed():
    assert len(schedule.GROUPS) == 12 and schedule.GROUPS[0] == "1.1" and schedule.GROUPS[-1] == "6.2"
    assert "odesa" in schedule.REGIONS and time.time() > 0
