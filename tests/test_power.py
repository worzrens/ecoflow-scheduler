from datetime import datetime

from ecoflow_app.power import Segment, grid_segments, outage_seconds, state_of, state_since
from ecoflow_app.util import soc_color


def test_state_of():
    assert state_of(99.9, 258, 244, True) == "full"
    assert state_of(80, 900, 300, True) == "charging"
    assert state_of(80, 0, 256, False) == "discharging"          # outage
    assert state_of(60, 300, 600, True) == "discharging"         # limit below load: battery helps
    assert state_of(60, 300, 298, True) == "ongrid"
    assert state_of(50, 200, 100, False) == "charging"           # solar only


def test_state_hysteresis_no_flicker():
    prev = "full"
    for soc in (99.4, 99.6, 99.3, 99.45):
        prev = state_of(soc, 258, 250, True, prev)
        assert prev == "full"
    assert state_of(97, 258, 250, True, "full") != "full"        # really left full
    prev = "charging"
    assert state_of(80, 302, 300, True, prev) == "charging"      # tiny net, stays charging
    assert state_of(80, 302, 300, True, None) == "ongrid"


def test_soc_color_gradient():
    assert soc_color(100) == soc_color(80) == "#2ee68a"            # green
    assert soc_color(5) == soc_color(0) == "#ef4444"               # red
    assert soc_color(45) == "#facc15"                              # yellow
    assert soc_color(25) == "#fb923c"                              # orange
    assert soc_color(35) not in ("#facc15", "#fb923c")             # blended between


def row(ts, grid, soc=80, in_w=100, out_w=100):
    return (ts, soc, in_w, out_w, in_w, out_w, 300, 28, grid)


def test_state_since_finds_start_of_current_run():
    rows = [row(100, 1, 100, 258, 250), row(130, 1, 100, 258, 250), row(160, 0, 99, 0, 250), row(190, 0, 98, 0, 250),
            row(220, 0, 98, 0, 250)]
    s, since = state_since(rows)
    assert s == "discharging" and since == 160


def test_legacy_rows_without_grid_flag_use_ac_input():
    rows = [(100, 90, 250, 250, 250, 250, 300, 28, None), (130, 90, 0, 250, 0, 250, 300, 28, None)]
    segs = grid_segments(rows, 100, 190, now=190)
    assert [s.kind for s in segs][:2] == ["grid", "outage"]


def test_segments_cover_range_with_outage_and_gap():
    # samples every 30 s: mains until 300, outage 300..600, then app off until 2000, mains again 2000..2090
    rows = [row(t, 1) for t in range(0, 300, 30)] + [row(t, 0, out_w=200) for t in range(300, 600, 30)] \
        + [row(600, 1)] + [row(t, 1) for t in range(2000, 2100, 30)]
    segs = grid_segments(rows, 0, 2100, now=5000)
    kinds = [s.kind for s in segs]
    assert kinds == ["grid", "outage", "grid", "nodata", "grid"], kinds
    assert segs[0].start == 0 and segs[1].start == 300 and segs[1].end == 600
    assert abs(outage_seconds(segs) - 300) < 1
    # energy: 200 W for 300 s = 16.67 Wh
    assert abs(segs[1].out_kwh - 200 * 300 / 3.6e6) < 1e-6
    # no holes: consecutive segments touch
    for a, b in zip(segs, segs[1:]):
        assert abs(a.end - b.start) <= 1


def test_ongoing_state_extends_to_now_only_if_recent():
    rows = [row(0, 0), row(30, 0)]
    assert grid_segments(rows, 0, 1000, now=60)[-1].kind == "outage"      # fresh: outage continues to now
    stale = grid_segments(rows, 0, 1000, now=900)
    assert stale[-1].kind == "nodata" and stale[0].kind == "outage"


def test_fill_gaps_estimates_from_neighbours():
    from ecoflow_app.power import fill_gaps, outage_count, slice_segments
    # grid 0-300, no data 300-900, grid 900-1000
    segs = [Segment(0, 300, "grid", 0.3, 0.3), Segment(300, 900, "nodata"), Segment(900, 1000, "grid", 0.1, 0.1)]
    out = fill_gaps(segs)
    assert [s.kind for s in out] == ["grid", "grid", "grid"] and out[1].guessed and not out[0].guessed
    assert out[1].out_kwh > 0                                   # estimated energy from neighbouring average power
    # mains before, outage after: power failed right after the last data -> the outage fills the whole gap
    segs = [Segment(0, 300, "grid"), Segment(300, 900, "nodata"), Segment(900, 1000, "outage")]
    out = fill_gaps(segs)
    assert [(s.kind, s.guessed) for s in out] == [("grid", False), ("outage", True), ("outage", False)]
    assert outage_count(out) == 1                               # estimated + real outage touch -> one outage
    assert abs(outage_seconds(out) - 700) < 1 and abs(outage_seconds(out, only_guessed=True) - 600) < 1
    # outage before, mains after: outage lasts until data resumes
    out = fill_gaps([Segment(0, 300, "outage"), Segment(300, 900, "nodata"), Segment(900, 1000, "grid")])
    assert [s.kind for s in out] == ["outage", "outage", "grid"]


def test_fill_gaps_leading_gap_and_long_trailing_gap_stay_unknown():
    from ecoflow_app.power import fill_gaps
    segs = [Segment(0, 500, "nodata"), Segment(500, 600, "grid"), Segment(600, 600 + 4 * 3600, "nodata")]
    out = fill_gaps(segs)
    assert out[0].kind == "nodata" and out[-1].kind == "nodata"     # nothing to extrapolate from / gap too long
    short = fill_gaps([Segment(0, 100, "outage"), Segment(100, 1000, "nodata")])
    assert short[-1].kind == "outage" and short[-1].guessed          # unit offline for a moment: keep last state


def test_slice_segments_scales_energy():
    from ecoflow_app.power import slice_segments
    s = [Segment(0, 1000, "grid", 1.0, 2.0)]
    a, = slice_segments(s, 250, 750)
    assert (a.start, a.end) == (250, 750) and abs(a.out_kwh - 0.5) < 1e-9 and abs(a.in_kwh - 1.0) < 1e-9


def test_merge_same_kind_combines_real_and_estimated():
    from ecoflow_app.power import fill_gaps, merge_same_kind, outage_count, slice_segments
    segs = [Segment(0, 1000, "grid", 1.0, 1.0), Segment(1000, 1600, "nodata"), Segment(1600, 2000, "grid", 0.4, 0.4)]
    merged = merge_same_kind(fill_gaps(segs))
    assert len(merged) == 1 and merged[0].kind == "grid"
    z = merged[0]
    assert (z.start, z.end) == (0, 2000) and abs(z.est_seconds - 600) < 1 and z.seconds == 2000
    part = slice_segments(merged, 900, 1300)[0]                       # estimated span is clipped with the slice
    assert abs(part.est_seconds - 300) < 1 and part.seconds == 400
    out = merge_same_kind([Segment(0, 100, "outage"), Segment(100, 200, "outage", est_spans=[(100, 200)]),
                           Segment(200, 300, "grid")])
    assert [s.kind for s in out] == ["outage", "grid"] and outage_count(out) == 1 and out[0].est_seconds == 100


def test_input_breakdown_matches_the_ecoflow_example():
    from ecoflow_app.power import input_breakdown
    assert input_breakdown(815, 515) == (300, 515, 815)       # 815 W total = 515 W usage + 300 W charging
    assert input_breakdown(307, 310) == (0, 307, 307)         # full battery, pass-through: nothing charging
    assert input_breakdown(0, 250) == (0, 0, 0)               # no input
