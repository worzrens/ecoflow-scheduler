"""Manual marks of stretches without data: newest wins, recorded data wins over marks, shared between installs."""
import time

from ecoflow_app import shared, sync
from ecoflow_app.power import (apply_marks, fill_gaps, grid_segments, link_battery, merge_same_kind, outage_seconds,
                               resolve_marks, slice_segments)
from ecoflow_app.storage import History

SN = "DCEBTEST0001"


def row(ts, grid, soc=80.0):
    return (ts, soc, 300 if grid else 0, 100, 300 if grid else 0, 100, 300, 28, int(grid))


def timeline(rows, marks, t1):
    raw = grid_segments(rows, 0, t1, now=t1)
    return link_battery(merge_same_kind(fill_gaps(apply_marks(raw, resolve_marks(marks)))))


def test_newest_mark_wins_and_clear_removes():
    marks = [(0, 100, "grid", 1, "a"), (40, 60, "outage", 2, "b"), (90, 200, "clear", 3, "a")]
    assert resolve_marks(marks[::-1]) == [(0, 40, "grid"), (40, 60, "outage"), (60, 90, "grid")]


def test_mark_decides_a_gap_and_recorded_data_stays():
    rows = [row(0, True, 90), row(60, True, 90), row(3000, True, 60), row(3060, True, 60)]
    assert outage_seconds(timeline(rows, [], 3090)) == 0              # estimated: mains on both sides
    segs = timeline(rows, [(0, 3090, "outage", 5, "pc")], 3090)       # marked wider than the gap
    assert [s.kind for s in segs] == ["grid", "outage", "grid"]
    out = segs[1]
    assert (out.start, out.end) == (120, 3000) and out.manual_seconds == out.seconds and not out.guessed
    assert (round(out.soc_start), round(out.soc_end)) == (90, 60) and out.battery(True) == "~90→60%"
    assert slice_segments(segs, 0, 1000)[1].manual_seconds == 880


def test_mark_on_a_leading_gap_without_any_neighbour_before():
    rows = [row(5000, True), row(5060, True)]
    assert timeline(rows, [], 5090)[0].kind == "nodata"
    first = timeline(rows, [(0, 5000, "grid", 1, "pc")], 5090)
    assert [s.kind for s in first] == ["grid"] and first[0].manual_seconds == 5000


def test_marks_travel_between_installs(tmp_path):
    a, b = History(tmp_path / "a.db"), History(tmp_path / "b.db")
    now = int(time.time())
    root = tmp_path / "shared"
    a.add_marks([(now - 7200, now - 3600, "outage", now - 60.0, "A")], own=True)
    sync.sync_once(a, str(root), SN, "A")
    res = sync.sync_once(b, str(root), SN, "B")
    assert res.marks == 1 and not res.error and b.marks() == a.marks()
    assert shared.marks_doc(b) is None                                # imported marks are not published again
    b.add_marks([(now - 7200, now - 3600, "clear", now - 10.0, "B")], own=True)
    sync.sync_once(b, str(root), SN, "B")
    sync.sync_once(a, str(root), SN, "A")
    assert resolve_marks(a.marks()) == resolve_marks(b.marks()) == []


def test_damaged_marks_are_ignored(tmp_path):
    a = History(tmp_path / "a.db")
    bad = b'{"marks":[{"start":5,"end":1,"kind":"grid","at":1},{"start":1,"end":5,"kind":"x","at":1},{"end":5},7]}'
    assert shared.apply_marks_doc(a, bad) == 0
