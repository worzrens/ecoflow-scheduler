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
    c = RulesConfig(schedule=[], dynamic=Dynamic(True, 80, 1500, 300, hysteresis=2, soc_low=0))
    below = False
    seq = []
    for soc in [50, 79, 80, 81, 82, 81, 79]:
        w, _, below = effective_watts(c, D(12), soc, below)
        seq.append(w)
    assert seq == [1500, 1500, 1500, 1500, 300, 300, 1500]


def test_schedule_beats_dynamic():
    c = night_cfg(dynamic=Dynamic(True, 80, 1500, 300, soc_low=0))
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


def test_three_dynamic_tiers():
    c = RulesConfig(schedule=[], dynamic=Dynamic())          # 0-60 % 1800 W, 60-85 % 1200 W, 85-100 % 300 W
    w = lambda soc, st=0, cur=None: effective_watts(c, D(12), soc, st, cur)
    assert [w(s)[0] for s in (10, 59, 63, 80, 84, 89, 100)] == [1800, 1800, 1200, 1200, 1200, 300, 300]
    # inside a band the device value decides, so two copies never flip-flop
    assert w(61, 0, 1800)[0] == 1800 and w(61, 2, 1200)[0] == 1200
    assert w(86, 0, 1200)[0] == 1200 and w(86, 0, 300)[0] == 300
    assert "SOC < 60%" in w(10)[1] and "SOC < 85%" in w(70)[1] and "SOC >= 85%" in w(95)[1]
    from ecoflow_app.rules import describe_rules
    text = describe_rules(c, D(12), 70.0, 1)[2][1]
    assert "1800 W" in text and "1200 W" in text and "300 W" in text


def test_old_saved_dynamic_gets_the_new_tier():
    c = RulesConfig.from_dict({"dynamic": {"enabled": True, "soc_threshold": 85, "watts_below": 1200, "watts_above": 300}})
    assert c.dynamic.soc_low == 60 and c.dynamic.watts_low == 1800
