"""Settings (newest change wins) and the outage schedule travel through the same store as the history."""
import json
import time

from ecoflow_app import shared, sync
from ecoflow_app.rules import Dynamic, RulesConfig, Temporary
from ecoflow_app.storage import History

SN = "DCEBTEST0001"


def new(tmp, name):
    return History(tmp / f"{name}.db")


def values(rules, region="", group=""):
    return shared.current_values(rules, region, group)


def doc(history):
    return {shared.SETTINGS_FILE: shared.settings_doc(shared.load_state(history))}


def exchange(root, a, b):
    sync.sync_once(a, str(root), SN, "A", docs=doc(a))
    res_b = sync.sync_once(b, str(root), SN, "B", docs=doc(b))
    res_a = sync.sync_once(a, str(root), SN, "A", docs=doc(a))
    return res_a, res_b


def test_newest_change_wins_per_section(tmp_path):
    now = time.time()
    a, b = new(tmp_path, "a"), new(tmp_path, "b")
    ra = RulesConfig(default_watts=900, dynamic=Dynamic(watts_low=1500))
    rb = RulesConfig(default_watts=1100)
    # A saved its rules an hour ago; B never changed rules but chose the outage group more recently
    shared.note_changes(a, values(ra), "A", first_seen={"rules": now - 3600, "automation": now - 3600, "temporary": now - 3600})
    shared.note_changes(b, values(rb, "odesa", "4.1"), "B", first_seen={"outage": now - 60})
    res_a, res_b = exchange(tmp_path / "shared", a, b)

    got_b = shared.newer_sections(shared.load_state(b), res_b.peer_settings)
    assert set(got_b) == {"rules", "automation", "temporary"}
    merged = shared.apply_to_rules(rb, got_b)
    assert merged.default_watts == 900 and merged.dynamic.watts_low == 1500 and merged.automation_enabled
    got_a = shared.newer_sections(shared.load_state(a), res_a.peer_settings)
    assert set(got_a) == {"outage"} and got_a["outage"]["value"] == {"region": "odesa", "group": "4.1"}

    # a later change on B overrides A's older one
    shared.note_changes(b, values(RulesConfig(default_watts=700), "odesa", "4.1"), "B", now=now + 10)
    res_a, _ = exchange(tmp_path / "shared", a, b)
    assert shared.newer_sections(shared.load_state(a), res_a.peer_settings, now=now + 20)["rules"]["value"]["default_watts"] == 700


def test_defaults_never_override_and_expiry_is_not_a_change(tmp_path):
    now = time.time()
    a = new(tmp_path, "a")
    r = RulesConfig(temporary=Temporary(500, now + 60))
    s1 = shared.note_changes(a, values(r), "A", now=now)
    assert all(e["at"] == 0 for e in s1.values())                      # nothing was ever saved on this install
    assert shared.newer_sections({}, [{"sections": s1}]) == {}
    expired = RulesConfig()                                            # the engine dropped the expired rule
    s2 = shared.note_changes(a, values(expired), "A", now=now + 120)
    assert s2["temporary"]["at"] == 0


def test_damaged_or_hostile_values_are_ignored():
    bad = [{"sections": {"rules": {"at": 10, "by": "x", "value": {"default_watts": "lots"}},
                         "automation": {"at": 10, "value": "yes"},
                         "outage": {"at": 10, "value": {"region": "mars", "group": "9.9"}},
                         "temporary": {"at": "soon", "value": None}}}, {"sections": 5}, []]
    assert shared.newer_sections({}, bad) == {}


def test_schedule_is_shared_and_newer_publication_wins(tmp_path):
    day = int(time.time() // 86400 * 86400)
    a, b = new(tmp_path, "a"), new(tmp_path, "b")
    a.schedule_put("odesa", {day: {"4.1": "N" * 24}}, "21.11.2026 12:00")
    root = tmp_path / "shared"
    sync.sync_once(a, str(root), SN, "A")
    res = sync.sync_once(b, str(root), SN, "B")
    assert res.schedule_rows == 1 and not res.error
    assert b.schedule_days("odesa", "4.1", day, day + 86400) == {day: "N" * 24}
    # B fetches a revision; A takes it over, and A's older copy does not come back to B
    b.schedule_put("odesa", {day: {"4.1": "Y" * 24}}, "21.11.2026 15:00")
    sync.sync_once(b, str(root), SN, "B")
    sync.sync_once(a, str(root), SN, "A")
    sync.sync_once(b, str(root), SN, "B")
    for h in (a, b):
        assert h.schedule_days("odesa", "4.1", day, day + 86400) == {day: "Y" * 24}


def test_unchanged_documents_are_not_written_again(tmp_path):
    a = new(tmp_path, "a")
    root = tmp_path / "shared"
    sync.sync_once(a, str(root), SN, "A", docs=doc(a))
    f = root / "ecoflow-history" / SN / "A" / shared.SETTINGS_FILE
    before = f.stat().st_mtime_ns
    time.sleep(0.02)
    sync.sync_once(a, str(root), SN, "A", docs=doc(a))
    assert f.stat().st_mtime_ns == before and json.loads(f.read_text())["v"] == 1
