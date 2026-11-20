import time
from datetime import datetime

from ecoflow_app.rules import Dynamic, RulesConfig, ScheduleEntry, Temporary, effective_watts

D = lambda h, m=0, day=20: datetime(2026, 11, day, h, m)  # 2026-11-20 is a Friday


def night_cfg(**kw):
    kw.setdefault("dynamic", Dynamic(enabled=False))
    return RulesConfig(default_watts=1000, schedule=[ScheduleEntry("23:00", "09:00", 300)], **kw)


def test_overnight_window_boundaries():
    c = night_cfg()
    w = lambda t: effective_watts(c, t, 50)[0]
    assert w(D(22, 59)) == 1000
    assert w(D(23, 0)) == 300
    assert w(D(3, 0)) == 300
    assert w(D(8, 59)) == 300
    assert w(D(9, 0)) == 1000
    assert w(D(12, 0)) == 1000


def test_overnight_days_refer_to_start_day():
    # window starts Friday (4) only: Fri 23:30 and Sat 02:00 are inside, Fri 02:00 is not
    c = RulesConfig(default_watts=1000, schedule=[ScheduleEntry("23:00", "09:00", 300, days=[4])],
                    dynamic=Dynamic(enabled=False))
    assert effective_watts(c, D(23, 30, 20), 50)[0] == 300       # Fri night
    assert effective_watts(c, D(2, 0, 21), 50)[0] == 300         # Sat early morning
    assert effective_watts(c, D(2, 0, 20), 50)[0] == 1000        # Fri early morning
    assert effective_watts(c, D(23, 30, 21), 50)[0] == 1000      # Sat night


def test_temporary_overrides_schedule_then_expires():
    now = D(3)
    c = night_cfg(temporary=Temporary(2000, now.timestamp() + 60))
    assert effective_watts(c, now, 50)[0] == 2000
    c.temporary = Temporary(2000, now.timestamp() - 1)
    assert effective_watts(c, D(3), 50)[0] == 300


def test_dynamic_with_hysteresis():
    c = RulesConfig(schedule=[], dynamic=Dynamic(True, 80, 1500, 300, hysteresis=2))
    below = False
    seq = []
    for soc in [50, 79, 80, 81, 82, 81, 79]:
        w, _, below = effective_watts(c, D(12), soc, below)
        seq.append(w)
    assert seq == [1500, 1500, 1500, 1500, 300, 300, 1500]


def test_schedule_beats_dynamic():
    c = night_cfg(dynamic=Dynamic(True, 80, 1500, 300))
    assert effective_watts(c, D(3), 10)[0] == 300
    assert effective_watts(c, D(12), 10)[0] == 1500


def test_clamp_and_roundtrip():
    c = RulesConfig(default_watts=50, schedule=[], dynamic=Dynamic(enabled=False))
    assert effective_watts(c, D(12), None)[0] == 200
    c2 = RulesConfig.from_dict(night_cfg(temporary=Temporary(500, 1.0)).to_dict())
    assert c2.schedule[0].watts == 300 and c2.temporary.watts == 500


def test_short_reason_icons():
    from ecoflow_app.rules import short_reason
    assert short_reason("Default").endswith("Default")
    assert "09:00" in short_reason("Schedule 23:00-09:00") and "SOC" not in short_reason("Dynamic (SOC >= 85%)")
    assert short_reason("Dynamic (SOC >= 85%)").endswith("\u226585%")
    assert short_reason("Dynamic (SOC < 85%)").endswith("<85%")
    assert "Temporary" in short_reason("Temporary rule")
