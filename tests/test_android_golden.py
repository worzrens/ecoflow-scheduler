"""If the desktop's timeline logic changes, the Android port (checked against golden.json) must be updated too."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_android_reference_data_matches_current_logic():
    spec = importlib.util.spec_from_file_location("make_android_golden", ROOT / "tools" / "make_android_golden.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    saved = json.loads(mod.OUT.read_text("utf-8"))
    assert saved == json.loads(json.dumps(mod.build())), \
        "power.py/schedule.py changed: port it to Segments.java, then run tools/make_android_golden.py"
