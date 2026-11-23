"""Two installs share power history through a folder: gaps get filled, nothing echoes, nothing conflicts."""
import time
from pathlib import Path

from ecoflow_app import sync
from ecoflow_app.api import Telemetry
from ecoflow_app.storage import MIN_INTERVAL, History, SRC_IDX

SN = "DCEBTEST0001"


def tel(soc=80.0, out_w=250.0, grid=True):
    return Telemetry(0, soc, out_w, out_w, out_w, out_w, 300, 28, 900, 0, grid=grid)


def fill(h: History, start: float, end: float, step: int = 40, **kw):
    t = start
    while t <= end:
        h.add(tel(**kw), ts=t)
        h._last_ts = 0      # allow dense fake data
        t += step


def new(tmp: Path, name: str) -> History:
    return History(tmp / f"{name}.db")


def test_gaps_are_filled_from_the_other_device_and_empty_stays_empty(tmp_path):
    now = time.time()
    root = tmp_path / "shared"
    a, b = new(tmp_path, "a"), new(tmp_path, "b")
    # A recorded hours -6..-3 and -1..0; B recorded -4..-1.5 -> A has a hole -3..-1, B fills it; nobody has -8..-6
    fill(a, now - 6 * 3600, now - 3 * 3600)
    fill(a, now - 1 * 3600, now, soc=75.0)         # a different level than before the hole (a battery never repeats exactly)
    fill(b, now - 4 * 3600 + 7, now - 1.5 * 3600, soc=70.0)     # +7 s: real devices never share exact timestamps
    assert sync.sync_once(a, str(root), SN, "A").exported > 0
    assert sync.sync_once(b, str(root), SN, "B").exported > 0
    resa = sync.sync_once(a, str(root), SN, "A")          # A now reads what B shared
    assert resa.imported > 0 and resa.peers
    c = sync.coverage(a, days=1, now=now)
    only_a = new(tmp_path, "only_a")
    fill(only_a, now - 6 * 3600, now - 3 * 3600)
    fill(only_a, now - 1 * 3600, now, soc=75.0)
    before = sync.coverage(only_a, days=1, now=now)
    assert c["covered_pct"] > before["covered_pct"] + 5     # B adds -3..-1.5 h (1.5 h = 6 points of the 24 h window)
    assert 1.3 < c["filled_by_peers_h"] < 1.7 and 0.8 < c["both_h"] < 1.2
    assert c["empty_h"] > 15                                # 24 h window: still nothing for the night before -6 h
    assert before["filled_by_peers_h"] == 0


def test_no_echo_idempotent_and_own_files_only(tmp_path):
    now = time.time()
    root = tmp_path / "shared"
    a, b = new(tmp_path, "a"), new(tmp_path, "b")
    fill(a, now - 3600, now - 1800)
    fill(b, now - 1700, now - 900)
    for _ in range(2):
        sync.sync_once(a, str(root), SN, "A")
        sync.sync_once(b, str(root), SN, "B")
    n_b_before = len(b.range(0))
    again_a, again_b = sync.sync_once(a, str(root), SN, "A"), sync.sync_once(b, str(root), SN, "B")
    assert again_a.exported == again_a.imported == again_b.exported == again_b.imported == 0   # idempotent
    assert len(b.range(0)) == n_b_before
    # A's DB holds B's rows tagged with B's id, and they were not re-shared by A
    assert {r[SRC_IDX] for r in a.range(0)} == {None, "B"}
    files = {p.parent.name for p in (root / sync.ROOT_NAME / SN).glob("*/*.jsonl")}
    assert files == {"A", "B"}
    a_rows_in_a_files = sum(1 for p in (root / sync.ROOT_NAME / SN / "A").glob("*.jsonl") for _ in open(p))
    assert a_rows_in_a_files == len(a.local_since(0))        # A's files contain only A's own samples


def test_half_written_line_is_picked_up_later_and_other_devices_are_isolated(tmp_path):
    now = time.time()
    root = tmp_path / "shared"
    a = new(tmp_path, "a")
    d = sync.own_dir(root, SN, "B")
    d.mkdir(parents=True)
    day = sync._day(now - 100)
    good = f"[{int(now - 200)},80,250,250,250,250,300,28,1]\n"
    partial = f"[{int(now - 100)},79,2"                     # peer is still writing this line
    (d / f"{day}.jsonl").write_text(good + partial, "utf-8")
    other_unit = sync.device_dir(root, "OTHERSN") / "C"
    other_unit.mkdir(parents=True)
    (other_unit / f"{day}.jsonl").write_text(f"[{int(now - 50)},10,1,1,1,1,300,28,1]\n", "utf-8")
    r1 = sync.sync_once(a, str(root), SN, "A")
    assert r1.imported == 1                                  # only the complete line; the other unit's data is ignored
    (d / f"{day}.jsonl").write_text(good + f"[{int(now - 100)},79,250,250,250,250,300,28,1]\n", "utf-8")
    r2 = sync.sync_once(a, str(root), SN, "A")
    assert r2.imported == 1 and len(a.range(0)) == 2


def test_old_history_and_min_interval_are_not_affected_by_peer_rows(tmp_path):
    now = time.time()
    h = new(tmp_path, "h")
    h.add_peer_rows([(int(now - 10), 80, 1, 1, 1, 1, 300, 28, 1)], "B")
    assert h.add(tel(), ts=now) is True                      # a peer sample 10 s ago must not throttle our own recording
    h.add(tel(), ts=now + 1)
    assert len([r for r in h.range(0) if r[SRC_IDX] is None]) == 1   # MIN_INTERVAL still applies to local samples
    assert h.add_peer_rows([(int(now - 20 * 86400), 80, 1, 1, 1, 1, 300, 28, 1)], "B") == 0   # past the retention
    assert MIN_INTERVAL == 30
