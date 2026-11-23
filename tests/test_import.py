import json
import urllib.request

import pytest

from ecoflow_app import importer, schedule

HOURS = {str(h): "yes" for h in range(1, 25)}
HOURS["1"] = "no"
FACT = {"update": "21.11.2026 12:51", "data": {"1795219200": {"GPV4.1": HOURS}}}


def test_parse_text_variants():
    for text in (json.dumps(FACT), json.dumps({"fact": FACT}),
                 "<script>DisconSchedule.fact = " + json.dumps(FACT) + ";</script>"):
        d = schedule.parse_text(text)
        assert d.days[1795219200]["4.1"].startswith("N") and d.update == "21.11.2026 12:51"
    with pytest.raises(schedule.ScheduleError):
        schedule.parse_text("hello")
    with pytest.raises(schedule.ScheduleError):
        schedule.parse_text("{}")


def test_listener_round_trip():
    got = []
    srv = importer.start(0, lambda t: got.append(t) or "ok")
    assert srv is not None
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/schedule"
        r = urllib.request.urlopen(urllib.request.Request(url, data=b"abc", method="POST"), timeout=5)
        assert r.read() == b"ok" and r.headers["Access-Control-Allow-Origin"] == "*" and got == ["abc"]
    finally:
        srv.shutdown()
